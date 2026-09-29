"""Job preferences and the benefit list (UC-03.6)."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from core.testing import pin_language

from .models import BenefitPreference, JobPreference
from .services import SEED_BENEFITS, get_or_create_preference

User = get_user_model()


def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class PreferenceSeedingTests(TestCase):
    def setUp(self):
        pin_language(self)
        user = User.objects.create_user(email="pref@example.com", password="pw12345678")
        self.profile = Profile.objects.get(user=user)

    def test_the_first_visit_seeds_twelve_starter_benefits_as_nice_to_have(self):
        preference = get_or_create_preference(self.profile)
        self.assertEqual(len(SEED_BENEFITS), 12)
        benefits = list(preference.benefits.all())
        self.assertEqual(len(benefits), 12)
        self.assertEqual({b.importance for b in benefits}, {BenefitPreference.NICE_TO_HAVE})
        self.assertIn("Dental care", {b.name for b in benefits})

    def test_a_second_call_neither_duplicates_nor_reseeds(self):
        preference = get_or_create_preference(self.profile)
        preference.benefits.filter(name="Dental care").delete()
        again = get_or_create_preference(self.profile)
        self.assertEqual(again.pk, preference.pk)
        self.assertEqual(again.benefits.count(), 11)
        self.assertEqual(JobPreference.objects.filter(profile=self.profile).count(), 1)

    def test_each_profile_gets_its_own(self):
        second = Profile.objects.create(user=self.profile.user, name="Second", language="en")
        self.assertNotEqual(
            get_or_create_preference(self.profile).pk, get_or_create_preference(second).pk
        )


class PreferenceScreenTests(TestCase):
    def setUp(self):
        pin_language(self)
        self.user = User.objects.create_user(email="pref2@example.com", password="pw12345678")
        self.profile = Profile.objects.get(user=self.user)
        self.client.force_login(self.user)
        self.url = reverse("preferences:detail")

    def test_the_screen_shows_the_form_and_the_benefits(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preference"].profile, self.profile)
        self.assertEqual(response.context["benefits"].count(), 12)

    def test_saving_stores_the_scalars_and_confirms(self):
        response = self.client.post(
            self.url,
            {"desired_salary_min": "90000", "desired_salary_max": "120000",
             "salary_currency": "EUR", "salary_period": "year",
             "preferred_locations": "Paris\nRemote", "remote_ok": "on",
             "timezone_preference": "CET"},
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        preference = JobPreference.objects.get(profile=self.profile)
        self.assertEqual(
            (preference.desired_salary_min, preference.desired_salary_max, preference.salary_currency),
            (90000, 120000, "EUR"),
        )
        self.assertEqual(preference.preferred_locations_list, ["Paris", "Remote"])
        self.assertTrue(preference.remote_ok)
        self.assertFalse(preference.hybrid_ok)
        self.assertEqual(flash(response), ["Job preferences saved."])

    def test_a_target_below_the_minimum_is_refused(self):
        response = self.client.post(
            self.url, {"desired_salary_min": "120000", "desired_salary_max": "90000", "salary_period": "year"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("desired_salary_max", response.context["form"].errors)
        self.assertIsNone(JobPreference.objects.get(profile=self.profile).desired_salary_min)

    def test_adding_a_benefit(self):
        response = self.client.post(
            reverse("preferences:benefit_add"),
            {"name": "Company car", "importance": "must_have", "notes": "electric"},
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        benefit = BenefitPreference.objects.get(name="Company car")
        self.assertEqual((benefit.importance, benefit.notes), ("must_have", "electric"))
        self.assertEqual(benefit.preference.profile, self.profile)
        self.assertEqual(flash(response), ["Added “Company car” to your preferences."])

    def test_a_benefit_already_listed_is_refused_whatever_its_case(self):
        response = self.client.post(
            reverse("preferences:benefit_add"), {"name": "dental CARE", "importance": "nice_to_have"}
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(BenefitPreference.objects.filter(name__iexact="dental care").count(), 1)
        self.assertEqual(flash(response), ["“dental CARE” is already in your preferences."])

    def test_a_blank_benefit_is_refused(self):
        response = self.client.post(
            reverse("preferences:benefit_add"), {"name": "   ", "importance": "nice_to_have"}
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(flash(response), ["This field is required."])

    def test_changing_a_benefits_importance(self):
        preference = get_or_create_preference(self.profile)
        benefit = preference.benefits.get(name="Dental care")
        response = self.client.post(
            reverse("preferences:benefit_update", args=[benefit.pk]), {"importance": "must_have"}
        )
        self.assertRedirects(response, f"{self.url}#benefits", fetch_redirect_response=False)
        benefit.refresh_from_db()
        self.assertEqual(benefit.importance, "must_have")

    def test_an_unknown_importance_changes_nothing_but_still_redirects(self):
        preference = get_or_create_preference(self.profile)
        benefit = preference.benefits.get(name="Dental care")
        response = self.client.post(
            reverse("preferences:benefit_update", args=[benefit.pk]), {"importance": "whatever"}
        )
        self.assertRedirects(response, f"{self.url}#benefits", fetch_redirect_response=False)
        benefit.refresh_from_db()
        self.assertEqual(benefit.importance, "nice_to_have")

    def test_deleting_a_benefit_says_what_was_removed(self):
        preference = get_or_create_preference(self.profile)
        benefit = preference.benefits.get(name="Dental care")
        response = self.client.post(reverse("preferences:benefit_delete", args=[benefit.pk]))
        self.assertFalse(BenefitPreference.objects.filter(pk=benefit.pk).exists())
        self.assertEqual(flash(response), ["Removed “Dental care”."])

    def test_another_profiles_benefit_is_a_404(self):
        other = User.objects.create_user(email="pref3@example.com", password="pw12345678")
        theirs = get_or_create_preference(Profile.objects.get(user=other)).benefits.first()
        for name, method in (
            ("preferences:benefit_update", self.client.post),
            ("preferences:benefit_delete", self.client.post),
            ("preferences:benefit_delete", self.client.get),
        ):
            with self.subTest(name=name, method=method.__name__):
                self.assertEqual(method(reverse(name, args=[theirs.pk])).status_code, 404)
        self.assertTrue(BenefitPreference.objects.filter(pk=theirs.pk).exists())

    def test_the_empty_flag_ignores_benefits_marked_not_important(self):
        preference = get_or_create_preference(self.profile)
        self.assertFalse(preference.is_empty, "the seeded benefits count as something")
        BenefitPreference.objects.filter(preference=preference).update(importance="not_important")
        self.assertTrue(JobPreference.objects.get(pk=preference.pk).is_empty)
