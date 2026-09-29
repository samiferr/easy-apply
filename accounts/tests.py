"""Profiles as workspaces: creation, language enforcement, switching, isolation."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from accounts.services import ACTIVE_PROFILE_SESSION_KEY
from education.models import Certificate, Degree
from experience.models import WorkExperience
from jobs.models import JobPost
from languages.models import Language, UserLanguage
from preferences.services import get_or_create_preference
from resume.models import TailoredResume
from skills.models import SkillCategory, UserSkill
from staffportal.models import Plan, Subscription
from staffportal.domain import runtime_settings

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
        JobPost.objects.create(profile=second)
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
        JobPost.objects.create(profile=self.backend, title="Backend Engineer")

        self.activate(self.analyst)
        skills = self.client.get(reverse("skills:list", args=["technical"])).content.decode()
        self.assertNotIn("Python", skills)
        jobs = self.client.get(reverse("jobs:list")).content.decode()
        self.assertNotIn("Backend Engineer", jobs)

        self.activate(self.backend)
        self.assertIn(
            "Python",
            self.client.get(reverse("skills:list", args=["technical"])).content.decode(),
        )
        self.assertIn(
            "Backend Engineer", self.client.get(reverse("jobs:list")).content.decode()
        )

    def test_a_job_from_another_profile_is_not_reachable(self):
        job = JobPost.objects.create(profile=self.backend)
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
        from core.services import generate_markdown_recap

        self.client.cookies["django_language"] = "en"
        recap = generate_markdown_recap(self.profile)
        self.assertIn("## Langues", recap)
        self.assertNotIn("## Languages", recap)
        self.assertIn("Natif / bilingue", recap)


# ---------------------------------------------------------------------------
# Characterization tests — pin the use cases before they move into services.py
# ---------------------------------------------------------------------------
def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


REGISTRATION = {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "flow@example.com",
    "profile_language": "en",
    "password1": "a-strong-passphrase-42",
    "password2": "a-strong-passphrase-42",
}


class RegistrationFlowTests(TestCase):
    """UC-01.1: an account, its first workspace, its plan, and a session."""

    def setUp(self):
        runtime_settings.invalidate()
        self.addCleanup(runtime_settings.invalidate)

    def test_a_new_account_is_signed_in_and_greeted(self):
        response = self.client.post(reverse("accounts:register"), REGISTRATION)
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        user = User.objects.get(email="flow@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(
            flash(response), ["Welcome to Easy Apply, Jane! Let's build your recap."]
        )

    def test_a_new_account_is_put_on_the_default_plan(self):
        free = Plan.objects.create(slug="free", name="Free", price_cents=0, is_default=True)
        self.client.post(reverse("accounts:register"), REGISTRATION)
        user = User.objects.get(email="flow@example.com")
        self.assertEqual(Subscription.objects.get(user=user).plan, free)

    def test_the_first_profile_is_named_and_in_the_chosen_language(self):
        self.client.post(reverse("accounts:register"), {**REGISTRATION, "profile_language": "fr"})
        profile = Profile.objects.get(user__email="flow@example.com")
        self.assertEqual(profile.language, "fr")
        self.assertTrue(profile.name)

    def assertSignupsPaused(self, response):
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertEqual(
            flash(response), ["New sign-ups are paused right now. Please check back shortly."]
        )

    def test_the_form_is_closed_when_sign_ups_are_switched_off(self):
        runtime_settings.set_value("signups_enabled", False)
        self.assertSignupsPaused(self.client.get(reverse("accounts:register")))

    def test_a_post_cannot_sneak_past_the_switch(self):
        runtime_settings.set_value("signups_enabled", False)
        self.assertSignupsPaused(self.client.post(reverse("accounts:register"), REGISTRATION))
        self.assertFalse(User.objects.filter(email="flow@example.com").exists())

    def test_someone_already_signed_in_is_sent_to_the_dashboard(self):
        user, _profile = make_user("already@example.com")
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:register"))
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_an_email_that_is_taken_is_a_form_error(self):
        make_user("flow@example.com")
        response = self.client.post(reverse("accounts:register"), REGISTRATION)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "email", "An account with this email already exists."
        )
        self.assertEqual(User.objects.filter(email="flow@example.com").count(), 1)


class LoginFlowTests(TestCase):
    """UC-01.2: email + password, and whether the session outlives the browser."""

    def setUp(self):
        make_user("login@example.com")

    def login(self, **extra):
        return self.client.post(
            reverse("accounts:login"),
            {"username": "login@example.com", "password": "pw12345678", **extra},
        )

    def test_without_remember_me_the_session_ends_with_the_browser(self):
        response = self.login()
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_with_remember_me_the_session_is_kept(self):
        self.login(remember_me="on")
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_wrong_credentials_redisplay_the_form(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "login@example.com", "password": "not-the-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_suspended_account_cannot_sign_in(self):
        User.objects.filter(email="login@example.com").update(is_active=False)
        self.login()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_login_lands_on_the_next_url(self):
        response = self.login(next=reverse("jobs:list"))
        self.assertRedirects(response, reverse("jobs:list"), fetch_redirect_response=False)


class LogoutFlowTests(TestCase):
    def setUp(self):
        self.user, _profile = make_user("bye@example.com")
        self.client.force_login(self.user)

    def test_the_confirmation_page_changes_nothing(self):
        self.assertEqual(self.client.get(reverse("accounts:logout_confirm")).status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

    def test_posting_ends_the_session(self):
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)


class PersonalInfoTests(TestCase):
    """UC-02.3: the name lives on the account, everything else on the profile."""

    def setUp(self):
        self.user, self.profile = make_user("info@example.com")
        self.client.force_login(self.user)

    def payload(self, **overrides):
        data = {
            "first_name": "Jane", "last_name": "Roe", "headline": "Staff engineer",
            "phone": "+1 555 0100", "location": "Montreal", "bio": "Hello.",
            "linkedin_url": "", "portfolio_url": "", "github_url": "",
        }
        data.update(overrides)
        return data

    def test_saving_updates_the_account_name_and_the_active_profile(self):
        response = self.client.post(reverse("accounts:profile"), self.payload())
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Jane", "Roe"))
        self.assertEqual(self.profile.headline, "Staff engineer")
        self.assertEqual(flash(response), ["Your profile has been updated."])

    def test_only_the_active_profile_changes(self):
        second = Profile.objects.create(user=self.user, name="Second", language="en")
        self.client.post(reverse("accounts:profile"), self.payload())
        second.refresh_from_db()
        self.assertEqual(second.headline, "")

    def test_a_bad_link_redisplays_the_form_unsaved(self):
        response = self.client.post(
            reverse("accounts:profile"), self.payload(linkedin_url="not a url")
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.headline, "")


class SecurityFlowTests(TestCase):
    """UC-01.4 and UC-01.6: change the password, or erase the account."""

    def setUp(self):
        self.user, self.profile = make_user("secure@example.com")
        self.client.force_login(self.user)

    def test_changing_the_password_keeps_the_session(self):
        response = self.client.post(
            reverse("accounts:security"),
            {
                "change_password": "1",
                "old_password": "pw12345678",
                "new_password1": "another-strong-phrase-77",
                "new_password2": "another-strong-phrase-77",
            },
        )
        self.assertRedirects(response, reverse("accounts:security"), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Your password has been changed successfully."])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("another-strong-phrase-77"))
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

    def test_a_wrong_old_password_changes_nothing(self):
        response = self.client.post(
            reverse("accounts:security"),
            {
                "change_password": "1",
                "old_password": "wrong",
                "new_password1": "another-strong-phrase-77",
                "new_password2": "another-strong-phrase-77",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["password_form"].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pw12345678"))

    def test_deleting_the_account_erases_it_and_signs_out(self):
        JobPost.objects.create(profile=self.profile, title="Mine")
        response = self.client.post(
            reverse("accounts:security"),
            {"delete_account": "1", "password": "pw12345678", "confirm": "on"},
        )
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertEqual(
            flash(response), ["Your account and all associated data have been deleted."]
        )
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(JobPost.objects.filter(title="Mine").exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_wrong_password_or_no_confirmation_deletes_nothing(self):
        for data in (
            {"delete_account": "1", "password": "wrong", "confirm": "on"},
            {"delete_account": "1", "password": "pw12345678"},
        ):
            with self.subTest(data=data):
                response = self.client.post(reverse("accounts:security"), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_an_unrecognised_post_is_bounced_back(self):
        response = self.client.post(reverse("accounts:security"), {"something": "else"})
        self.assertRedirects(response, reverse("accounts:security"), fetch_redirect_response=False)


class ProfileLimitTests(TestCase):
    """UC-02.1: workspaces are a ceiling set by the plan, once quotas are enforced."""

    def setUp(self):
        runtime_settings.invalidate()
        self.addCleanup(runtime_settings.invalidate)
        Plan.objects.create(
            slug="free", name="Free", price_cents=0, is_default=True, max_profiles=1
        )
        self.user, self.first = make_user("limit@example.com")
        self.client.force_login(self.user)

    def test_quotas_off_means_no_ceiling(self):
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "Second", "language": "en"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 2)

    def test_the_plan_limit_blocks_another_profile_once_enforced(self):
        runtime_settings.set_value("enforce_quotas", True)
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "Second", "language": "en"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            flash(response),
            ["Your plan allows 1 profile(s). Delete one, or upgrade, to add another."],
        )

    def test_a_created_profile_is_announced_and_becomes_active(self):
        response = self.client.post(
            reverse("accounts:profile_create"), {"name": "Analyste", "language": "fr"}
        )
        created = Profile.objects.get(name="Analyste")
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.assertEqual(self.client.session[ACTIVE_PROFILE_SESSION_KEY], created.pk)
        self.assertEqual(
            flash(response), ["Created “Analyste” (Français). You're now working in it."]
        )


class ProfileRenameTests(TestCase):
    """UC-02.4: renaming never touches the language."""

    def setUp(self):
        self.user, self.profile = make_user("rename@example.com", language="fr")
        self.client.force_login(self.user)

    def test_renaming_keeps_the_language(self):
        response = self.client.post(
            reverse("accounts:profile_rename", args=[self.profile.pk]), {"name": "Renamed"}
        )
        self.assertRedirects(
            response, reverse("accounts:profile_list"), fetch_redirect_response=False
        )
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.name, self.profile.language), ("Renamed", "fr"))
        self.assertEqual(flash(response), ["Profile renamed."])

    def test_a_name_already_in_use_is_refused(self):
        Profile.objects.create(user=self.user, name="Taken", language="en")
        response = self.client.post(
            reverse("accounts:profile_rename", args=[self.profile.pk]), {"name": "taken"}
        )
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.name, "Main")

    def test_someone_elses_profile_is_a_404(self):
        _other_user, other_profile = make_user("intruder@example.com")
        response = self.client.post(
            reverse("accounts:profile_rename", args=[other_profile.pk]), {"name": "Mine now"}
        )
        self.assertEqual(response.status_code, 404)


class ProfileSwitchLanguageTests(TestCase):
    """UC-02.2: the interface follows the workspace into its language."""

    def test_switching_sets_the_interface_language_cookie(self):
        user, _first = make_user("cookie@example.com")
        french = Profile.objects.create(user=user, name="Analyste", language="fr")
        self.client.force_login(user)
        response = self.client.post(reverse("accounts:profile_switch", args=[french.pk]))
        self.assertEqual(response.cookies["django_language"].value, "fr")
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Switched to “Analyste”."])
