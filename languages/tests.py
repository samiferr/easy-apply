"""Spoken languages of a profile (UC-03.3)."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile

from .models import Language, UserLanguage

User = get_user_model()


def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class LanguageManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="l@example.com", password="pw12345678")
        self.profile = Profile.objects.get(user=self.user)
        self.client.force_login(self.user)

    def add(self, name, proficiency=UserLanguage.FLUENT):
        return self.client.post(
            reverse("languages:add"), {"language_name": name, "proficiency": proficiency}
        )

    def test_adding_a_language_records_it_against_the_profile(self):
        response = self.add("Spanish")
        self.assertRedirects(response, reverse("languages:list"), fetch_redirect_response=False)
        entry = UserLanguage.objects.get(profile=self.profile)
        self.assertEqual((entry.language.name, entry.proficiency), ("Spanish", "fluent"))
        self.assertEqual(flash(response), ["Added Spanish to your languages."])

    def test_language_names_are_shared_and_matched_case_insensitively(self):
        existing = Language.objects.create(name="Spanish")
        self.add("sPANISH")
        self.assertEqual(Language.objects.count(), 1)
        self.assertEqual(UserLanguage.objects.get(profile=self.profile).language, existing)

    def test_the_same_language_cannot_be_added_twice(self):
        self.add("Spanish")
        response = self.add("spanish")
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "language_name", "You've already added this language."
        )
        self.assertEqual(UserLanguage.objects.filter(profile=self.profile).count(), 1)

    def test_two_profiles_may_each_have_the_language(self):
        other = User.objects.create_user(email="l2@example.com", password="pw12345678")
        self.add("Spanish")
        self.client.force_login(other)
        self.add("Spanish")
        self.assertEqual(UserLanguage.objects.count(), 2)
        self.assertEqual(Language.objects.count(), 1)

    def test_editing_changes_proficiency_and_can_rename(self):
        self.add("Spanish", UserLanguage.BASIC)
        entry = UserLanguage.objects.get()
        response = self.client.post(
            reverse("languages:edit", args=[entry.pk]),
            {"language_name": "Catalan", "proficiency": UserLanguage.NATIVE},
        )
        entry.refresh_from_db()
        self.assertEqual((entry.language.name, entry.proficiency), ("Catalan", "native"))
        self.assertEqual(flash(response)[-1:], ["Language updated."])

    def test_deleting_says_what_was_removed(self):
        self.add("Spanish")
        entry = UserLanguage.objects.get()
        response = self.client.post(reverse("languages:delete", args=[entry.pk]))
        self.assertFalse(UserLanguage.objects.exists())
        self.assertEqual(flash(response)[-1:], ["Removed Spanish."])

    def test_the_list_is_alphabetical_and_private_to_the_profile(self):
        other = User.objects.create_user(email="l3@example.com", password="pw12345678")
        UserLanguage.objects.create(
            profile=Profile.objects.get(user=other),
            language=Language.objects.create(name="Zulu"),
        )
        self.add("Spanish")
        self.add("Arabic")
        entries = self.client.get(reverse("languages:list")).context["user_languages"]
        self.assertEqual([entry.language.name for entry in entries], ["Arabic", "Spanish"])

    def test_another_profiles_entry_is_a_404(self):
        other = User.objects.create_user(email="l4@example.com", password="pw12345678")
        theirs = UserLanguage.objects.create(
            profile=Profile.objects.get(user=other),
            language=Language.objects.create(name="Zulu"),
        )
        self.assertEqual(self.client.post(reverse("languages:delete", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("languages:edit", args=[theirs.pk])).status_code, 404)
