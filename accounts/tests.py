"""Profiles as workspaces: creation, language enforcement, switching, isolation."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from accounts.services import ACTIVE_PROFILE_SESSION_KEY
from education.models import Certificate, Degree
from experience.models import WorkExperience
from jobs.models import JobPost
from languages.models import Language, UserLanguage
from preferences.models import get_or_create_preference
from resume.models import TailoredResume
from skills.models import SkillCategory, UserSkill

User = get_user_model()


def make_user(email="jane@example.com", **profile_fields):
    user = User.objects.create_user(email=email, password="pw12345678")
    profile = Profile.objects.get(user=user)
    for field, value in {"name": "Main", "language": "en", **profile_fields}.items():
        setattr(profile, field, value)
    profile.save()
    return user, profile


class RegistrationTests(TestCase):
    def test_signing_up_creates_one_profile_in_the_chosen_language(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "new@example.com",
                "profile_language": "fr",
                "password1": "a-strong-passphrase-42",
                "password2": "a-strong-passphrase-42",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new@example.com")
        profiles = Profile.objects.filter(user=user)
        self.assertEqual(profiles.count(), 1)
        self.assertEqual(profiles.get().language, "fr")

    def test_the_language_must_be_chosen(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "nolang@example.com",
                "profile_language": "",
                "password1": "a-strong-passphrase-42",
                "password2": "a-strong-passphrase-42",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "profile_language", "This field is required."
        )
        self.assertFalse(User.objects.filter(email="nolang@example.com").exists())


class ProfileCreationTests(TestCase):
    def setUp(self):
        self.user, self.profile = make_user()
        self.client.force_login(self.user)

    def test_creating_a_profile_requires_a_language(self):
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "Data analyst", "language": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "language", "This field is required.")
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)

    def test_an_unsupported_language_is_rejected(self):
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "Data analyst", "language": "de"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)

    def test_a_new_profile_becomes_the_active_one(self):
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "Analyste (FR)", "language": "fr"}
        )
        created = Profile.objects.get(user=self.user, name="Analyste (FR)")
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(self.client.session[ACTIVE_PROFILE_SESSION_KEY], created.pk)

    def test_names_are_unique_per_user(self):
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "main", "language": "en"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)

    def test_the_language_cannot_be_changed_afterwards(self):
        response = self.client.post(
            reverse("accounts:profile_rename", args=[self.profile.pk]),
            {"name": "Renamed", "language": "fr"},
        )
        self.assertRedirects(response, reverse("accounts:profile_list"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.name, "Renamed")
        self.assertEqual(self.profile.language, "en", "the language must be immutable")


class ProfileSwitchingTests(TestCase):
    def setUp(self):
        self.user, self.english = make_user()
        self.french = Profile.objects.create(user=self.user, name="Analyste", language="fr")
        self.client.force_login(self.user)

    def test_switching_changes_the_active_profile_and_the_interface_language(self):
        response = self.client.post(
            reverse("accounts:profile_switch", args=[self.french.pk]),
            {"next": reverse("core:dashboard")},
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertEqual(self.client.session[ACTIVE_PROFILE_SESSION_KEY], self.french.pk)
        self.assertEqual(self.client.cookies["django_language"].value, "fr")

    def test_another_users_profile_cannot_be_activated(self):
        other, other_profile = make_user(email="mallory@example.com")
        response = self.client.post(
            reverse("accounts:profile_switch", args=[other_profile.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(
            self.client.session.get(ACTIVE_PROFILE_SESSION_KEY), other_profile.pk
        )

    def test_an_offsite_next_url_falls_back_to_the_dashboard(self):
        response = self.client.post(
            reverse("accounts:profile_switch", args=[self.french.pk]),
            {"next": "https://evil.test/steal"},
        )
        self.assertRedirects(response, reverse("core:dashboard"))

    def test_a_stale_session_profile_falls_back_to_a_real_one(self):
        session = self.client.session
        session[ACTIVE_PROFILE_SESSION_KEY] = 99999
        session.save()
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_profile"], self.english)


class ProfileDeletionTests(TestCase):
    def setUp(self):
        self.user, self.first = make_user()
        self.client.force_login(self.user)

    def test_the_last_profile_cannot_be_deleted(self):
        response = self.client.post(reverse("accounts:profile_delete", args=[self.first.pk]))
        self.assertRedirects(response, reverse("accounts:profile_list"))
        self.assertTrue(Profile.objects.filter(pk=self.first.pk).exists())

    def test_deleting_a_profile_takes_its_content_with_it(self):
        second = Profile.objects.create(user=self.user, name="Second", language="en")
        JobPost.objects.create(profile=second, source_url="https://x.test/j")
        self.client.post(reverse("accounts:profile_delete", args=[second.pk]))
        self.assertFalse(Profile.objects.filter(pk=second.pk).exists())
        self.assertFalse(JobPost.objects.filter(profile_id=second.pk).exists())

    def test_deleting_the_active_profile_activates_another(self):
        second = Profile.objects.create(user=self.user, name="Second", language="en")
        self.client.post(
            reverse("accounts:profile_switch", args=[second.pk]),
            {"next": reverse("core:dashboard")},
        )
        self.client.post(reverse("accounts:profile_delete", args=[second.pk]))
        self.assertEqual(self.client.session[ACTIVE_PROFILE_SESSION_KEY], self.first.pk)


class ProfileIsolationTests(TestCase):
    """Two profiles on one account never see each other's content."""

    def setUp(self):
        self.user, self.backend = make_user()
        self.backend.name = "Backend"
        self.backend.save(update_fields=["name"])
        self.analyst = Profile.objects.create(user=self.user, name="Analyst", language="fr")
        self.category = SkillCategory.objects.create(
            name="Programming", kind=SkillCategory.TECHNICAL
        )
        self.client.force_login(self.user)

    def activate(self, profile):
        self.client.post(
            reverse("accounts:profile_switch", args=[profile.pk]),
            {"next": reverse("core:dashboard")},
        )

    def test_content_created_in_one_profile_is_absent_from_the_other(self):
        UserSkill.objects.create(profile=self.backend, category=self.category, name="Python")
        JobPost.objects.create(
            profile=self.backend, source_url="https://x.test/backend", title="Backend Engineer"
        )

        self.activate(self.analyst)
        skills = self.client.get(reverse("skills:list")).content.decode()
        self.assertNotIn("Python", skills)
        jobs = self.client.get(reverse("jobs:list")).content.decode()
        self.assertNotIn("Backend Engineer", jobs)

        self.activate(self.backend)
        self.assertIn("Python", self.client.get(reverse("skills:list")).content.decode())
        self.assertIn(
            "Backend Engineer", self.client.get(reverse("jobs:list")).content.decode()
        )

    def test_a_job_from_another_profile_is_not_reachable(self):
        job = JobPost.objects.create(profile=self.backend, source_url="https://x.test/j")
        self.activate(self.analyst)
        self.assertEqual(self.client.get(job.get_absolute_url()).status_code, 404)

    def test_the_same_skill_can_exist_once_per_profile(self):
        UserSkill.objects.create(profile=self.backend, category=self.category, name="Python")
        UserSkill.objects.create(profile=self.analyst, category=self.category, name="Python")
        self.assertEqual(UserSkill.objects.filter(name="Python").count(), 2)

    def test_writes_land_in_the_active_profile(self):
        self.activate(self.analyst)
        self.client.post(
            reverse("skills:add", args=[SkillCategory.TECHNICAL]),
            {"category": self.category.pk, "name": "SQL", "level": UserSkill.ADVANCED},
        )
        self.assertTrue(UserSkill.objects.filter(profile=self.analyst, name="SQL").exists())
        self.assertFalse(UserSkill.objects.filter(profile=self.backend, name="SQL").exists())

    def test_each_profile_keeps_its_own_preferences(self):
        backend_preference = get_or_create_preference(self.backend)
        analyst_preference = get_or_create_preference(self.analyst)
        self.assertNotEqual(backend_preference.pk, analyst_preference.pk)

    def test_every_content_model_is_owned_by_a_profile(self):
        """A regression guard: nothing may go back to hanging off the account."""
        for model in (
            UserSkill, UserLanguage, WorkExperience, Degree, Certificate,
            JobPost, TailoredResume,
        ):
            with self.subTest(model=model.__name__):
                field_names = {f.name for f in model._meta.get_fields()}
                self.assertIn("profile", field_names)
                self.assertNotIn("user", field_names)


class RecapLanguageTests(TestCase):
    """The Markdown recap is written in the profile's language, not the UI's."""

    def setUp(self):
        self.user, self.profile = make_user(name="Analyste", language="fr")
        language = Language.objects.create(name="Français")
        UserLanguage.objects.create(
            profile=self.profile, language=language, proficiency=UserLanguage.NATIVE
        )
        self.client.force_login(self.user)

    def test_recap_is_french_even_when_the_interface_is_english(self):
        from core.utils import generate_markdown_recap

        self.client.cookies["django_language"] = "en"
        recap = generate_markdown_recap(self.profile)
        self.assertIn("## Langues", recap)
        self.assertNotIn("## Languages", recap)
        self.assertIn("Natif / bilingue", recap)
