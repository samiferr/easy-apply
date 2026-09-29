"""Smoke tests: every route renders under the new layout, in both languages."""

import json
import re
import shutil
import tempfile
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy

from accounts.models import Profile
from core.ai import AIConfigError, AIServiceError, call_deepseek_json
from core.language import language_clause
from core.models import AITask
from core.prompts import PLACEHOLDER, PromptError, load_prompt
from core.tasks import is_retryable
from core.testing import fake_deepseek, pin_language
from core.utils import (
    build_profile_slice,
    build_profile_snapshot,
    build_resume_snapshot,
    empty_slice_hint,
    generate_markdown_recap,
    profile_slice_is_empty,
    profile_snapshot_is_empty,
    recap_filename,
)
from jobs.models import JobPost
from jobs.services.importer import apply_analysis
from resume.models import TailoredResume

User = get_user_model()


def make_profile(email, *, language="en", name="Main"):
    user = User.objects.create_user(email=email, password="pw12345678")
    profile = Profile.objects.get(user=user)
    profile.name = name
    profile.language = language
    profile.save(update_fields=["name", "language"])
    return profile


class PublicPagesTests(TestCase):
    def test_marketing_and_legal_pages_render(self):
        for name in [
            "core:home",
            "legal:privacy",
            "legal:terms",
            "legal:cookies",
            "legal:notice",
            "legal:contact",
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_pages_render_in_french(self):
        self.client.cookies["django_language"] = "fr"
        for name in ["core:home", "legal:privacy"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_language_switcher_sets_the_cookie(self):
        response = self.client.post(
            reverse("set_language"), {"language": "fr", "next": reverse("core:home")}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies["django_language"].value, "fr")


class AuthenticatedPagesTests(TestCase):
    def setUp(self):
        self.profile = make_profile("s@example.com")
        self.client.force_login(self.profile.user)

    def test_every_app_screen_renders(self):
        for name in [
            "core:dashboard",
            "jobs:list",
            "jobs:add",
            "preferences:detail",
            "experience:list",
            "education:list",
            "languages:list",
            "resume:upload",
            "resume:tailored_list",
            "accounts:profile",
            "accounts:profile_list",
            "accounts:profile_create",
            "accounts:security",
            "core:export_preview",
        ]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200, f"{name} did not render")

        # Soft and technical skills are two screens, one per sidebar entry.
        for kind in ["soft", "technical"]:
            with self.subTest(kind=kind):
                url = reverse("skills:list", args=[kind])
                self.assertEqual(self.client.get(url).status_code, 200, f"{url} did not render")

    def test_dashboard_renders_in_french(self):
        self.client.cookies["django_language"] = "fr"
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

    def test_job_detail_renders_all_thirteen_sections(self):
        job = JobPost.objects.create(profile=self.profile)
        apply_analysis(
            job,
            {
                "title": "Engineer",
                "summary": "Build things.",
                "sections": [
                    {"key": "overview", "body": "Build things.", "elements": []},
                    {"key": "required_technical_skills", "body": "", "elements": ["Python"]},
                ],
            },
            "raw",
        )
        response = self.client.get(job.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        # The rail always shows the full canonical list, even for absent sections.
        content = response.content.decode()
        for label in ["Overview", "Possible red flags", "Worth noting", "How to Apply"]:
            self.assertIn(label, content, f"rail is missing {label}")

    def test_preferences_seeds_a_starter_benefit_list(self):
        self.client.get(reverse("preferences:detail"))
        self.assertTrue(self.profile.job_preference.benefits.exists())


class DashboardChartTests(TestCase):
    def setUp(self):
        self.profile = make_profile("t@example.com")
        self.client.force_login(self.profile.user)

    def test_chart_handles_an_empty_month(self):
        response = self.client.get(reverse("core:dashboard"))
        chart = response.context["chart"]
        self.assertFalse(chart["has_data"])
        self.assertEqual(chart["total"], 0)
        self.assertTrue(all(bar["percent"] == 0 for bar in chart["bars"]))

    def test_chart_counts_jobs_for_the_current_month(self):
        JobPost.objects.create(profile=self.profile)
        JobPost.objects.create(profile=self.profile)
        chart = self.client.get(reverse("core:dashboard")).context["chart"]
        self.assertTrue(chart["has_data"])
        self.assertEqual(chart["total"], 2)
        self.assertEqual(chart["peak"], 2)


class FrenchCatalogueTests(TestCase):
    """The FR catalogue must actually reach the rendered page, not just compile."""

    def setUp(self):
        self.profile = make_profile("fr@example.com", language="fr")
        self.user = self.profile.user
        self.client.cookies["django_language"] = "fr"

    def test_marketing_page_is_translated(self):
        body = self.client.get(reverse("core:home")).content.decode()
        for needle in ["C’est bien d’être", "paresseux", "Trois étapes vers un CV personnalisé", "Créer un compte"]:
            self.assertIn(needle, body, f"missing French string: {needle}")
        self.assertNotIn("It's OK to be", body)

    def test_privacy_policy_is_translated(self):
        body = self.client.get(reverse("legal:privacy")).content.decode()
        for needle in ["Politique de confidentialité", "Traitement par IA", "Vos droits"]:
            self.assertIn(needle, body, f"missing French string: {needle}")

    def test_app_shell_and_dashboard_are_translated(self):
        self.client.force_login(self.user)
        body = self.client.get(reverse("core:dashboard")).content.decode()
        for needle in ["Tableau de bord", "Analyser une offre", "Importer un CV", "Aller au contenu"]:
            self.assertIn(needle, body, f"missing French string: {needle}")

    def test_job_sections_are_translated(self):
        self.client.force_login(self.user)
        job = JobPost.objects.create(profile=self.profile)
        apply_analysis(job, {"title": "X", "sections": [{"key": "overview", "body": "b", "elements": []}]}, "raw")
        body = self.client.get(job.get_absolute_url()).content.decode()
        for needle in ["Vue d’ensemble", "Rémunération et avantages", "Signaux d’alerte possibles"]:
            self.assertIn(needle, body, f"missing French section label: {needle}")

    def test_seeded_benefits_are_translated(self):
        self.client.force_login(self.user)
        body = self.client.get(reverse("preferences:detail")).content.decode()
        self.assertIn("Soins dentaires", body)
        self.assertIn("Congés payés", body)

    def test_english_is_unaffected(self):
        self.client.cookies["django_language"] = "en"
        body = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("It's OK to be", body)
        self.assertIn("lazy", body)


class ResponsiveContractTests(TestCase):
    """Guards the layout rules that are easy to regress silently."""

    def setUp(self):
        self.profile = make_profile("r@example.com")
        self.client.force_login(self.profile.user)

    def test_every_form_widget_carries_the_shared_classes(self):
        """An unstyled widget falls back to the browser's intrinsic width and
        overflows on a phone — this is how the preferences textareas broke."""
        from jobs.profile_targets import ADD_TARGETS
        from preferences.forms import BenefitPreferenceForm, JobPreferenceForm
        from preferences.models import get_or_create_preference

        preference = get_or_create_preference(self.profile)
        forms_to_check = [
            JobPreferenceForm(instance=preference),
            BenefitPreferenceForm(preference=preference),
        ]
        for target in ADD_TARGETS.values():
            forms_to_check.append(target.form_class(profile=self.profile, element=None))

        for form in forms_to_check:
            for name, field in form.fields.items():
                with self.subTest(form=type(form).__name__, field=name):
                    css = field.widget.attrs.get("class", "")
                    self.assertTrue(
                        css, f"{type(form).__name__}.{name} has no CSS class"
                    )

    def test_the_shell_has_no_top_bar_and_the_sidebar_carries_the_account_controls(self):
        """The sidebar is the app's only chrome: everything the top bar used to
        hold has to be reachable from inside it, or it is unreachable."""
        body = self.client.get(reverse("core:dashboard")).content.decode()
        sidebar = body.split('id="app-sidebar"', 1)
        self.assertEqual(len(sidebar), 2, "the app shell must render the sidebar")
        sidebar = sidebar[1].split("</aside>", 1)[0]

        for needle in [
            reverse("accounts:profile"),          # personal info
            reverse("accounts:profile_list"),     # profiles
            reverse("core:export_preview"),       # recap export
            reverse("accounts:logout_confirm"),   # log out
            reverse("set_language"),              # FR / EN
            "toggleTheme()",                      # theme
        ]:
            self.assertIn(needle, sidebar, f"the sidebar is missing {needle}")

        # The drawer opens from a floating button, not from a bar spanning the top.
        self.assertIn("Open navigation", body)

    def test_the_screen_reader_chart_table_is_wrapped(self):
        """sr-only on a <table> does not clamp its height (display:table treats
        it as a minimum), so the table must sit inside a block wrapper."""
        body = self.client.get(reverse("core:dashboard")).content.decode()
        self.assertIn('<div class="sr-only">', body)
        self.assertNotIn('<table class="sr-only">', body)


class ProfileCompletionVisibilityTests(TestCase):
    """The completion readouts are a to-do list — they go away once it's done."""

    def setUp(self):
        self.profile = make_profile("done@example.com")
        self.client.force_login(self.profile.user)

    def complete_everything(self):
        from datetime import date

        from education.models import Degree
        from experience.models import ExperienceHighlight, WorkExperience
        from languages.models import Language, UserLanguage
        from preferences.models import get_or_create_preference
        from skills.models import SkillCategory, UserSkill

        self.profile.headline = "Backend developer"
        self.profile.phone = "+1 555 0100"
        self.profile.location = "Montreal, QC"
        self.profile.bio = "Ships things."
        self.profile.linkedin_url = "https://linkedin.com/in/x"
        self.profile.avatar = "avatars/user_1/x.png"
        self.profile.save()

        preference = get_or_create_preference(self.profile)
        preference.remote_ok = True
        preference.save()

        for kind in (SkillCategory.SOFT, SkillCategory.TECHNICAL):
            category = SkillCategory.objects.filter(kind=kind).first()
            UserSkill.objects.create(profile=self.profile, category=category, name=f"X{kind}")
        UserLanguage.objects.create(
            profile=self.profile,
            language=Language.objects.create(name="English"),
            proficiency=UserLanguage.NATIVE,
        )
        Degree.objects.create(profile=self.profile, school="McGill", degree="BSc")
        experience = WorkExperience.objects.create(
            profile=self.profile, job_title="Dev", company="Acme",
            start_date=date(2020, 1, 1), is_current=True,
        )
        ExperienceHighlight.objects.create(experience=experience, text="Shipped things.")

    def test_an_incomplete_profile_is_nudged(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertFalse(response.context["profile_is_complete"])
        self.assertContains(response, ">Profile completion<")
        self.assertContains(response, "% complete")
        self.assertContains(self.client.get(reverse("accounts:profile")), "% complete")

    def test_a_complete_profile_is_left_alone(self):
        self.complete_everything()

        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.context["completion_percent"], 100)
        self.assertTrue(response.context["profile_is_complete"])
        self.assertNotContains(response, ">Profile completion<")
        self.assertNotContains(response, "% complete")
        self.assertNotContains(self.client.get(reverse("accounts:profile")), "% complete")


class ConfirmDeleteTests(TestCase):
    """Every destructive action gets a real confirmation page instead of a
    native `confirm()` popup: GET shows the page and changes nothing, POST
    (only) performs the delete."""

    def setUp(self):
        self.profile = make_profile("del@example.com")
        self.client.force_login(self.profile.user)

    def assertConfirmPage(self, response, *, contains=()):
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/confirm_delete.html")
        self.assertContains(response, "btn-danger")
        for needle in contains:
            self.assertContains(response, needle)

    def test_skill_delete_has_a_confirm_page(self):
        from skills.models import SkillCategory, UserSkill

        category = SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).first()
        skill = UserSkill.objects.create(profile=self.profile, category=category, name="Rust")
        url = reverse("skills:delete", args=[skill.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Rust"])
        self.assertTrue(UserSkill.objects.filter(pk=skill.pk).exists())

        response = self.client.post(url)
        # The categories are tabs, so a delete returns to the one it was in.
        self.assertRedirects(
            response,
            f'{reverse("skills:list", args=["technical"])}#category-{category.pk}',
        )
        self.assertFalse(UserSkill.objects.filter(pk=skill.pk).exists())

    def test_language_delete_has_a_confirm_page(self):
        from languages.models import Language, UserLanguage

        language = Language.objects.create(name="Klingon")
        ul = UserLanguage.objects.create(
            profile=self.profile, language=language, proficiency=UserLanguage.FLUENT
        )
        url = reverse("languages:delete", args=[ul.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Klingon"])
        self.assertTrue(UserLanguage.objects.filter(pk=ul.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("languages:list"))
        self.assertFalse(UserLanguage.objects.filter(pk=ul.pk).exists())

    def test_degree_delete_has_a_confirm_page(self):
        from education.models import Degree

        degree = Degree.objects.create(profile=self.profile, school="McGill", degree="BSc")
        url = reverse("education:degree_delete", args=[degree.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["McGill"])
        self.assertTrue(Degree.objects.filter(pk=degree.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("education:list"))
        self.assertFalse(Degree.objects.filter(pk=degree.pk).exists())

    def test_certificate_delete_has_a_confirm_page(self):
        from education.models import Certificate

        cert = Certificate.objects.create(
            profile=self.profile, name="AWS SAA", issuing_organization="Amazon"
        )
        url = reverse("education:certificate_delete", args=[cert.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["AWS SAA"])
        self.assertTrue(Certificate.objects.filter(pk=cert.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("education:list"))
        self.assertFalse(Certificate.objects.filter(pk=cert.pk).exists())

    def test_experience_delete_has_a_confirm_page(self):
        from datetime import date

        from experience.models import WorkExperience

        exp = WorkExperience.objects.create(
            profile=self.profile, job_title="Dev", company="Acme",
            start_date=date(2020, 1, 1), is_current=True,
        )
        url = reverse("experience:delete", args=[exp.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Acme"])
        self.assertTrue(WorkExperience.objects.filter(pk=exp.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("experience:list"))
        self.assertFalse(WorkExperience.objects.filter(pk=exp.pk).exists())

    def test_job_post_delete_has_a_confirm_page(self):
        job = JobPost.objects.create(profile=self.profile, title="Backend Engineer")
        url = reverse("jobs:delete", args=[job.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Backend Engineer"])
        self.assertTrue(JobPost.objects.filter(pk=job.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("jobs:list"))
        self.assertFalse(JobPost.objects.filter(pk=job.pk).exists())

    def test_job_post_delete_warns_about_its_tailored_resume(self):
        job = JobPost.objects.create(profile=self.profile)
        TailoredResume.objects.create(profile=self.profile, job=job, markdown="# CV")
        response = self.client.get(reverse("jobs:delete", args=[job.pk]))
        self.assertContains(response, "tailored resume")

    def test_deleting_a_job_post_cascades_to_its_tailored_resume(self):
        job = JobPost.objects.create(profile=self.profile)
        TailoredResume.objects.create(profile=self.profile, job=job, markdown="# CV")
        self.client.post(reverse("jobs:delete", args=[job.pk]))
        self.assertFalse(TailoredResume.objects.filter(job_id=job.pk).exists())

    def test_tailored_resume_delete_has_a_confirm_page(self):
        job = JobPost.objects.create(profile=self.profile, title="Data Analyst")
        TailoredResume.objects.create(profile=self.profile, job=job, markdown="# CV")
        url = reverse("resume:tailored_delete", args=[job.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Data Analyst"])
        self.assertTrue(TailoredResume.objects.filter(job=job).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("jobs:detail", args=[job.pk]))
        self.assertFalse(TailoredResume.objects.filter(job=job).exists())

    def test_benefit_delete_has_a_confirm_page(self):
        from preferences.models import BenefitPreference, get_or_create_preference

        preference = get_or_create_preference(self.profile)
        benefit = BenefitPreference.objects.create(preference=preference, name="Gym membership")
        url = reverse("preferences:benefit_delete", args=[benefit.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Gym membership"])
        self.assertTrue(BenefitPreference.objects.filter(pk=benefit.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, f"{reverse('preferences:detail')}#benefits")
        self.assertFalse(BenefitPreference.objects.filter(pk=benefit.pk).exists())

    def test_profile_delete_has_a_confirm_page(self):
        second = Profile.objects.create(user=self.profile.user, name="Second", language="en")
        url = reverse("accounts:profile_delete", args=[second.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Second"])
        self.assertTrue(Profile.objects.filter(pk=second.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("accounts:profile_list"))
        self.assertFalse(Profile.objects.filter(pk=second.pk).exists())

    def test_the_last_profile_shows_no_confirm_page(self):
        """Nothing to confirm — deleting it can only fail, so GET redirects
        straight to the same error post() gives, instead of a doomed button."""
        url = reverse("accounts:profile_delete", args=[self.profile.pk])
        response = self.client.get(url, follow=True)
        self.assertRedirects(response, reverse("accounts:profile_list"))
        self.assertContains(response, "only profile")
        self.assertTrue(Profile.objects.filter(pk=self.profile.pk).exists())

    def test_confirm_page_text_follows_the_request_language(self):
        """Regression guard: a translatable string assigned as a class
        attribute (`warning = _("...")`) is evaluated once, at import time,
        in whatever language happens to be active then — not per request.
        Every piece of text on this page must come from a method or the
        template, both of which re-evaluate on each request."""
        from skills.models import SkillCategory, UserSkill

        category = SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).first()
        skill = UserSkill.objects.create(profile=self.profile, category=category, name="Rust")
        self.client.cookies["django_language"] = "fr"

        body = self.client.get(reverse("skills:delete", args=[skill.pk])).content.decode()
        self.assertIn("Supprimer cette compétence", body)
        self.assertIn("Cette action est irréversible", body)
        self.assertNotIn("This can't be undone.", body)

    def test_delete_links_are_not_bare_get_forms(self):
        """Regression guard: the trigger must be a plain link to the confirm
        page, not a POST form with a JS confirm() (unstyled, easy to click
        through, invisible to assistive tech until the dialog is already open)."""
        from skills.models import SkillCategory, UserSkill

        category = SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).first()
        skill = UserSkill.objects.create(profile=self.profile, category=category, name="Go")
        body = self.client.get(reverse("skills:list", args=["technical"])).content.decode()
        self.assertNotIn("onsubmit=\"return confirm(", body)
        self.assertIn(f'href="{reverse("skills:delete", args=[skill.pk])}"', body)


# ---------------------------------------------------------------------------
# Characterization tests
#
# Written against the code as it stood *before* the services refactor, and kept
# afterwards: they pin what each use case does, so moving the code cannot
# quietly change it.
# ---------------------------------------------------------------------------
def make_rich_profile(*, language="en"):
    """One profile with something in every part of it, for the recap and the
    profile slices."""
    from education.models import Certificate, Degree
    from experience.models import ExperienceHighlight, WorkExperience
    from languages.models import Language, UserLanguage
    from preferences.models import get_or_create_preference
    from skills.models import SkillCategory, UserSkill

    user = User.objects.create_user(
        email="ada@example.com", password="pw12345678", first_name="Ada", last_name="Lovelace"
    )
    profile = Profile.objects.get(user=user)
    profile.name = "Backend"
    profile.language = language
    profile.headline = "Staff engineer"
    profile.phone = "+1 555 0100"
    profile.location = "Montreal, QC"
    profile.bio = " Builds reliable systems. "
    profile.linkedin_url = "https://linkedin.com/in/ada"
    profile.portfolio_url = "https://ada.dev"
    profile.github_url = "https://github.com/ada"
    profile.save()

    databases = SkillCategory.objects.get_or_create(name="Databases", kind="technical")[0]
    runtimes = SkillCategory.objects.get_or_create(name="Languages & Runtimes", kind="technical")[0]
    leadership = SkillCategory.objects.get_or_create(name="Leadership", kind="soft")[0]
    UserSkill.objects.create(profile=profile, category=databases, name="PostgreSQL", level=4)
    UserSkill.objects.create(profile=profile, category=runtimes, name="Python", level=3)
    UserSkill.objects.create(profile=profile, category=leadership, name="Mentoring", level=2)

    UserLanguage.objects.create(
        profile=profile, language=Language.objects.create(name="French"), proficiency="professional"
    )
    UserLanguage.objects.create(
        profile=profile, language=Language.objects.create(name="English"), proficiency="native"
    )

    current = WorkExperience.objects.create(
        profile=profile, job_title="Staff Engineer", company="Acme", location="Remote",
        employment_type="full_time", start_date=date(2021, 3, 1), is_current=True,
    )
    ExperienceHighlight.objects.create(experience=current, text="Cut deploy time by 40%.", order=0)
    ExperienceHighlight.objects.create(experience=current, text="Mentored 6 engineers.", order=1)
    WorkExperience.objects.create(
        profile=profile, job_title="Engineer", company="Globex",
        start_date=date(2018, 1, 1), end_date=date(2021, 2, 1),
    )

    Degree.objects.create(
        profile=profile, school="McGill", degree="BSc", field_of_study="CS",
        start_date=date(2014, 9, 1), end_date=date(2018, 5, 1), grade="First",
        description="Honours thesis.",
    )
    Degree.objects.create(
        profile=profile, school="MIT", degree="MSc", is_current=True, start_date=date(2022, 9, 1)
    )
    Certificate.objects.create(
        profile=profile, name="AWS SAA", issuing_organization="Amazon",
        issue_date=date(2023, 1, 15), expiry_date=date(2026, 1, 15),
        credential_id="ABC123", credential_url="https://aws.example/abc",
    )
    Certificate.objects.create(
        profile=profile, name="CKA", issuing_organization="CNCF",
        issue_date=date(2022, 6, 1), does_not_expire=True,
    )

    with translation.override("en"):  # the seeded benefit names follow the active language
        preference = get_or_create_preference(profile)
    preference.desired_salary_min = 100000
    preference.desired_salary_max = 140000
    preference.salary_currency = "CAD"
    preference.remote_ok = True
    preference.hybrid_ok = True
    preference.preferred_locations = "Montreal\nRemote (Canada)"
    preference.timezone_preference = "EST"
    preference.max_travel_percentage = 10
    preference.save()
    dental = preference.benefits.get(name="Dental care")
    dental.importance = "must_have"
    dental.save()
    vision = preference.benefits.get(name="Vision care")
    vision.importance = "not_important"
    vision.save()
    return profile


ENGLISH_RECAP = """# Ada Lovelace
*Staff engineer*

- **Email:** ada@example.com
- **Phone:** +1 555 0100
- **Location:** Montreal, QC
- **LinkedIn:** https://linkedin.com/in/ada
- **Portfolio:** https://ada.dev
- **GitHub:** https://github.com/ada

## About

Builds reliable systems.

## Soft Skills

### Leadership
- **Mentoring** — Intermediate

## Technical Skills

### Databases
- **PostgreSQL** — Expert

### Languages & Runtimes
- **Python** — Advanced

## Languages

- **English** — Native / bilingual
- **French** — Professional working proficiency

## Work Experience

### Staff Engineer — Acme
*Mar 2021 – Present · Remote · Full-time*
- Cut deploy time by 40%.
- Mentored 6 engineers.

### Engineer — Globex
*Jan 2018 – Feb 2021*

## Education

### MSc — MIT
*September 2022 – Present*

### BSc — McGill
*CS · September 2014 – May 2018 · Grade: First*

Honours thesis.

## Certificates

### AWS SAA
*Amazon · Issued January 2023 · Expires January 2026*

Credential ID: ABC123
[View credential](https://aws.example/abc)

### CKA
*CNCF · Issued June 2022 · No expiration*
"""


class MarkdownRecapTests(TestCase):
    """Every recorded part of a profile shows up in its Markdown recap."""

    def test_the_recap_lists_everything_the_profile_holds(self):
        profile = make_rich_profile()
        recap = generate_markdown_recap(profile)
        body, footer = recap.split("\n---\n")
        self.assertEqual(body.strip("\n"), ENGLISH_RECAP.strip("\n"))
        self.assertTrue(footer.strip().startswith("_Generated with Easy Apply on "))

    def test_an_empty_profile_still_gets_a_header_and_a_footer(self):
        profile = make_profile("bare@example.com")
        recap = generate_markdown_recap(profile)
        self.assertTrue(recap.startswith("# bare\n"))
        self.assertIn("- **Email:** bare@example.com", recap)
        for heading in ("## About", "## Soft Skills", "## Work Experience", "## Education"):
            self.assertNotIn(heading, recap)
        self.assertIn("\n---\n_Generated with Easy Apply on ", recap)

    def test_the_recap_follows_the_profile_language_not_the_interface(self):
        profile = make_rich_profile(language="fr")
        with translation.override("en"):
            recap = generate_markdown_recap(profile)
        for heading in (
            "## À propos", "## Compétences comportementales", "## Compétences techniques",
            "## Langues", "## Expérience professionnelle", "## Formation", "## Certificats",
        ):
            self.assertIn(heading, recap)
        self.assertIn("Aujourd’hui", recap)
        self.assertNotIn("## Work Experience", recap)

    def test_the_filename_is_a_slug_of_the_person_and_the_profile(self):
        profile = make_rich_profile()
        self.assertEqual(recap_filename(profile), "ada-lovelace-backend-easy-apply-recap.md")

    def test_the_filename_falls_back_to_the_email_when_there_is_no_name(self):
        profile = make_profile("jane.doe@example.com", name="Main")
        self.assertEqual(recap_filename(profile), "jane.doe-main-easy-apply-recap.md")

    def test_download_is_a_markdown_attachment(self):
        profile = make_rich_profile()
        self.client.force_login(profile.user)
        response = self.client.get(reverse("core:export_markdown"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="ada-lovelace-backend-easy-apply-recap.md"',
        )
        self.assertTrue(response.content.decode().startswith("# Ada Lovelace\n"))

    def test_preview_shows_the_same_recap(self):
        profile = make_rich_profile()
        self.client.force_login(profile.user)
        response = self.client.get(reverse("core:export_preview"))
        self.assertEqual(response.status_code, 200)
        recap = response.context["markdown_content"]
        self.assertEqual(recap.split("\n---\n")[0], generate_markdown_recap(profile).split("\n---\n")[0])

    def test_anonymous_visitors_cannot_export(self):
        for name in ("core:export_markdown", "core:export_preview"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)


class ProfileSliceTests(TestCase):
    """A match call is sent ONLY the part of the profile its section maps to."""

    def setUp(self):
        self.profile = make_rich_profile()

    def keys(self, section_key):
        return set(build_profile_slice(self.profile, section_key))

    def test_each_matched_section_maps_to_its_own_slice(self):
        self.assertEqual(
            self.keys("location_arrangement"),
            {
                "preferred_locations", "acceptable_work_arrangements",
                "max_onsite_days_per_week", "willing_to_relocate", "max_travel_percentage",
                "timezone_preference", "employment_types", "availability_notes",
            },
        )
        self.assertEqual(
            self.keys("compensation_benefits"),
            {"desired_salary_min", "desired_salary_max", "salary_currency", "salary_period",
             "benefits_wanted"},
        )
        self.assertEqual(self.keys("responsibilities"), {"experience", "technical_skills"})
        self.assertEqual(self.keys("required_technical_skills"), {"technical_skills"})
        self.assertEqual(self.keys("desirable_technical_skills"), {"technical_skills"})
        self.assertEqual(self.keys("desirable_soft_skills"), {"soft_skills"})
        self.assertEqual(self.keys("languages"), {"languages"})
        self.assertEqual(self.keys("education_certifications"), {"degrees", "certificates"})

    def test_sections_that_are_never_matched_have_no_slice(self):
        for key in ("overview", "company", "how_to_apply", "worth_noting", "red_flags", "nope"):
            with self.subTest(key=key):
                self.assertEqual(build_profile_slice(self.profile, key), {})

    def test_a_slice_never_leaks_another_slices_data(self):
        payload = json.dumps(build_profile_slice(self.profile, "required_technical_skills"))
        self.assertIn("PostgreSQL", payload)
        for private in ("Mentoring", "French", "MIT", "100000", "Dental care"):
            self.assertNotIn(private, payload)

    def test_benefits_the_candidate_does_not_care_about_are_left_out(self):
        wanted = build_profile_slice(self.profile, "compensation_benefits")["benefits_wanted"]
        names = {b["name"] for b in wanted}
        self.assertIn("Dental care", names)
        self.assertNotIn("Vision care", names)
        dental = next(b for b in wanted if b["name"] == "Dental care")
        self.assertEqual(dental["importance"], "Must have")

    def test_the_slice_carries_display_strings_in_the_profile_language(self):
        french = make_profile("fr-slice@example.com", language="fr")
        from languages.models import Language, UserLanguage

        UserLanguage.objects.create(
            profile=french, language=Language.objects.get_or_create(name="English")[0],
            proficiency="native",
        )
        with translation.override("en"):
            languages = build_profile_slice(french, "languages")["languages"]
        self.assertEqual(languages, [{"name": "English", "proficiency": "Natif / bilingue"}])

    def test_emptiness(self):
        for empty in ({}, {"languages": []}, {"a": None, "b": False, "c": "  ", "d": {}, "e": 0}):
            with self.subTest(empty=empty):
                self.assertTrue(profile_slice_is_empty(empty))
        for filled in ({"l": [1]}, {"d": {"a": 1}}, {"s": "x"}, {"n": 5}, {"b": True}):
            with self.subTest(filled=filled):
                self.assertFalse(profile_slice_is_empty(filled))

    def test_a_bare_profile_has_only_empty_slices(self):
        bare = make_profile("bare-slice@example.com")
        for key in ("required_technical_skills", "desirable_soft_skills", "languages",
                    "education_certifications", "responsibilities"):
            with self.subTest(key=key):
                self.assertTrue(profile_slice_is_empty(build_profile_slice(bare, key)))

    def test_every_matched_section_has_a_specific_hint(self):
        expected = {
            "location_arrangement": "No location or work-arrangement preferences recorded yet.",
            "compensation_benefits": "No salary or benefit preferences recorded yet.",
            "responsibilities": "No work experience or technical skills recorded yet.",
            "required_technical_skills": "No technical skills recorded in your profile yet.",
            "desirable_technical_skills": "No technical skills recorded in your profile yet.",
            "desirable_soft_skills": "No soft skills recorded in your profile yet.",
            "languages": "No languages recorded in your profile yet.",
            "education_certifications": "No degrees or certificates recorded in your profile yet.",
            "something_else": "Nothing in your profile covers this yet.",
        }
        with translation.override("en"):
            for key, hint in expected.items():
                with self.subTest(key=key):
                    self.assertEqual(str(empty_slice_hint(key)), hint)


class ProfileSnapshotTests(TestCase):
    """The tailored-resume path legitimately gets everything."""

    def setUp(self):
        self.profile = make_rich_profile()

    def test_the_profile_snapshot_gathers_every_recorded_part(self):
        snapshot = build_profile_snapshot(self.profile)
        self.assertEqual(
            set(snapshot),
            {"headline", "bio", "soft_skills", "technical_skills", "languages",
             "experience", "degrees", "certificates"},
        )
        self.assertEqual(snapshot["headline"], "Staff engineer")
        self.assertEqual(
            snapshot["technical_skills"][0],
            {"name": "PostgreSQL", "category": "Databases", "level": "Expert"},
        )
        current = snapshot["experience"][0]
        self.assertEqual(current["duration"], "Mar 2021 – Present")
        self.assertEqual(current["highlights"], ["Cut deploy time by 40%.", "Mentored 6 engineers."])

    def test_the_resume_snapshot_adds_contact_details_and_dates(self):
        snapshot = build_resume_snapshot(self.profile)
        self.assertEqual(
            snapshot["contact"],
            {
                "full_name": "Ada Lovelace", "first_name": "Ada", "last_name": "Lovelace",
                "email": "ada@example.com", "phone": "+1 555 0100", "location": "Montreal, QC",
                "linkedin_url": "https://linkedin.com/in/ada",
                "portfolio_url": "https://ada.dev", "github_url": "https://github.com/ada",
            },
        )
        role = snapshot["experience"][0]
        self.assertEqual(role["location"], "Remote")
        self.assertTrue(role["is_current"])
        degree = next(d for d in snapshot["degrees"] if d["degree"] == "BSc")
        self.assertEqual(degree["dates"], "September 2014 – May 2018")
        self.assertEqual(degree["grade"], "First")
        certificate = next(c for c in snapshot["certificates"] if c["name"] == "AWS SAA")
        self.assertEqual(certificate["credential_id"], "ABC123")

    def test_emptiness_of_a_snapshot(self):
        self.assertFalse(profile_snapshot_is_empty(build_profile_snapshot(self.profile)))
        bare = make_profile("bare-snap@example.com")
        self.assertTrue(profile_snapshot_is_empty(build_profile_snapshot(bare)))


class DashboardContextTests(TestCase):
    def setUp(self):
        self.profile = make_profile("dash@example.com")
        self.client.force_login(self.profile.user)

    def context(self):
        return self.client.get(reverse("core:dashboard")).context

    def test_the_checklist_starts_undone_and_follows_the_profile(self):
        from skills.models import SkillCategory, UserSkill

        checklist = self.context()["checklist"]
        self.assertEqual(
            [str(label) for label, _done, _url in checklist],
            [
                "Complete your profile", "Set your job preferences", "Add a technical skill",
                "Add a soft skill", "Add a language", "Add your work experience",
                "Add your education or a certificate",
            ],
        )
        self.assertFalse(any(done for _label, done, _url in checklist))
        self.assertEqual(self.context()["completion_percent"], 0)

        category = SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).first()
        UserSkill.objects.create(profile=self.profile, category=category, name="Go")
        context = self.context()
        done = {str(label): flag for label, flag, _url in context["checklist"]}
        self.assertTrue(done["Add a technical skill"])
        self.assertFalse(done["Add a soft skill"])
        self.assertEqual(context["completion_percent"], 14)

    def test_the_checklist_links_to_the_screen_that_fixes_it(self):
        urls = [url for _label, _done, url in self.context()["checklist"]]
        self.assertEqual(
            urls,
            [
                reverse("accounts:profile"), reverse("preferences:detail"),
                reverse("skills:list", args=["technical"]), reverse("skills:list", args=["soft"]),
                reverse("languages:list"), reverse("experience:list"), reverse("education:list"),
            ],
        )

    def test_recent_jobs_are_this_profiles_five_newest(self):
        other = make_profile("other-dash@example.com")
        JobPost.objects.create(profile=other, title="Someone else's")
        for index in range(7):
            JobPost.objects.create(profile=self.profile, title=f"Job {index}")
        context = self.context()
        titles = [job.title for job in context["recent_jobs"]]
        self.assertEqual(titles, ["Job 6", "Job 5", "Job 4", "Job 3", "Job 2"])
        self.assertEqual(context["job_post_count"], 7)

    def test_only_live_tasks_of_this_profile_are_shown_and_at_most_four(self):
        other = make_profile("other-live@example.com")
        foreign_job = JobPost.objects.create(profile=other)
        AITask.start_for(other, AITask.JOB_ANALYSIS, foreign_job)
        for index in range(5):
            job = JobPost.objects.create(profile=self.profile, title=f"J{index}")
            AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job)
        finished = JobPost.objects.create(profile=self.profile, title="done")
        AITask.start_for(self.profile, AITask.JOB_ANALYSIS, finished).mark_done()

        running = list(self.context()["running_tasks"])
        self.assertEqual(len(running), 4)
        self.assertTrue(all(t.profile_id == self.profile.pk for t in running))
        self.assertTrue(all(t.state in (AITask.QUEUED, AITask.RUNNING) for t in running))

    def test_a_signed_in_visitor_is_sent_from_the_landing_page_to_the_dashboard(self):
        self.assertRedirects(self.client.get(reverse("core:home")), reverse("core:dashboard"))


class TaskStatusEndpointTests(TestCase):
    """The polling contract every AI path reports through."""

    def setUp(self):
        self.profile = make_profile("poll@example.com")
        self.client.force_login(self.profile.user)
        self.job = JobPost.objects.create(profile=self.profile)

    def status(self, task):
        response = self.client.get(reverse("core:task_status", args=[task.pk]))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_payload_shape(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job, steps_total=4)
        task.mark_running("Reading the job posting")
        task.advance("Read the posting")
        payload = self.status(task)
        self.assertEqual(
            payload,
            {
                "id": task.pk, "kind": "job_analysis", "state": "running", "percent": 25,
                "indeterminate": False, "current_step": "Read the posting", "steps_done": 1,
                "steps_total": 4, "error_message": "", "is_terminal": False, "redirect_url": None,
            },
        )

    def test_a_finished_resume_import_points_at_its_review_page(self):
        from resume.models import ResumeImport

        upload = ResumeImport.objects.create(profile=self.profile, file="resumes/x.txt")
        task = AITask.start_for(self.profile, AITask.RESUME_IMPORT, upload, steps_total=2)
        task.mark_done()
        payload = self.status(task)
        self.assertTrue(payload["is_terminal"])
        self.assertEqual(payload["percent"], 100)
        self.assertEqual(payload["redirect_url"], reverse("resume:review", args=[upload.pk]))

    def test_a_finished_tailored_resume_points_at_its_editor(self):
        tailored = TailoredResume.objects.create(profile=self.profile, job=self.job, markdown="# CV")
        task = AITask.start_for(self.profile, AITask.TAILORED_RESUME, tailored)
        task.mark_done()
        self.assertEqual(
            self.status(task)["redirect_url"], reverse("resume:tailored", args=[self.job.pk])
        )

    def test_other_kinds_and_unfinished_tasks_have_nowhere_to_go(self):
        analysis = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        analysis.mark_done()
        self.assertIsNone(self.status(analysis)["redirect_url"])

        tailored = TailoredResume.objects.create(profile=self.profile, job=self.job, markdown="x")
        running = AITask.start_for(self.profile, AITask.TAILORED_RESUME, tailored)
        running.mark_running("Writing")
        self.assertIsNone(self.status(running)["redirect_url"])

    def test_a_failed_task_reports_its_message_and_is_terminal(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        task.mark_failed("The AI analysis took too long and timed out. Please try again.")
        payload = self.status(task)
        self.assertEqual(payload["state"], "failed")
        self.assertTrue(payload["is_terminal"])
        self.assertIn("timed out", payload["error_message"])
        self.assertIsNone(payload["redirect_url"])

    def test_someone_elses_task_is_a_404_and_anonymous_is_redirected(self):
        other = make_profile("intruder@example.com")
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        self.client.force_login(other.user)
        self.assertEqual(self.client.get(reverse("core:task_status", args=[task.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("core:task_status", args=[task.pk])).status_code, 302)


class AITaskLifecycleTests(TestCase):
    """The state machine every progress bar in the product is drawn from."""

    def setUp(self):
        self.profile = make_profile("life@example.com")
        self.job = JobPost.objects.create(profile=self.profile)

    def test_a_new_task_is_queued_and_owned_by_the_profile(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job, steps_total=3, step="Queued")
        self.assertEqual(task.state, AITask.QUEUED)
        self.assertEqual(task.user, self.profile.user)
        self.assertEqual(task.profile, self.profile)
        self.assertEqual(task.target, self.job)
        self.assertEqual(task.current_step, "Queued")
        self.assertEqual(AITask.latest_for(self.job, AITask.JOB_ANALYSIS), task)
        self.assertIsNone(AITask.latest_for(self.job, AITask.JOB_MATCH))

    def test_starting_again_cancels_the_live_task_for_the_same_target_and_kind(self):
        first = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        other_kind = AITask.start_for(self.profile, AITask.JOB_MATCH, self.job)
        second = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        first.refresh_from_db()
        other_kind.refresh_from_db()
        self.assertEqual(first.state, AITask.CANCELED)
        self.assertEqual(other_kind.state, AITask.QUEUED)
        self.assertEqual(second.state, AITask.QUEUED)

    def test_progress(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job, steps_total=4)
        self.assertFalse(task.is_indeterminate)
        self.assertEqual(task.percent, 0)
        task.mark_running("Reading", steps_total=5)
        self.assertEqual((task.state, task.steps_total, task.attempts), (AITask.RUNNING, 5, 1))
        self.assertIsNotNone(task.started_at)
        task.advance("Read")
        task.advance("Extracted")
        self.assertEqual((task.steps_done, task.percent, task.current_step), (2, 40, "Extracted"))
        task.set_step("Matching")
        self.assertEqual(task.current_step, "Matching")
        task.mark_done("Analysis complete")
        self.assertEqual((task.state, task.steps_done, task.percent), (AITask.DONE, 5, 100))
        self.assertTrue(task.is_terminal)
        self.assertIsNotNone(task.finished_at)

    def test_a_single_step_task_is_indeterminate(self):
        task = AITask.start_for(self.profile, AITask.TAILORED_RESUME, self.job, steps_total=1)
        self.assertTrue(task.is_indeterminate)
        self.assertEqual(task.percent, 0)

    def test_advancing_never_overshoots_the_total(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job, steps_total=2)
        for _ in range(5):
            task.advance("again")
        self.assertEqual(task.steps_done, 2)

    def test_failure_keeps_a_bounded_message(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        task.mark_failed("x" * 5000)
        self.assertEqual(task.state, AITask.FAILED)
        self.assertEqual(len(task.error_message), 2000)
        self.assertTrue(task.is_terminal)
        self.assertFalse(task.is_running)


class RetryPolicyTests(TestCase):
    """Only transient failures are worth another attempt."""

    def test_transient_provider_failures_are_retryable(self):
        for message in (
            "The AI analysis took too long and timed out. Please try again.",
            "The AI analysis service is rate-limiting us. Please try again shortly.",
            "Couldn't reach the AI analysis service. Please try again.",
            "The AI analysis service returned an error (HTTP 503).",
        ):
            with self.subTest(message=message):
                self.assertTrue(is_retryable(AIServiceError(message)))

    def test_deterministic_failures_are_not(self):
        for exc in (
            AIConfigError("no key"),
            AIServiceError("The AI analysis service rejected our API key."),
            AIServiceError("The AI analysis service returned invalid JSON."),
            AIServiceError("The AI analysis service returned an error (HTTP 400)."),
            ValueError("boom"),
        ):
            with self.subTest(exc=exc):
                self.assertFalse(is_retryable(exc))


class DeepSeekBoundaryTests(TestCase):
    """`call_deepseek_json` is the only door to the provider."""

    def test_it_sends_both_messages_and_returns_the_parsed_json_with_the_model(self):
        with fake_deepseek(lambda request: {"ok": True}) as calls:
            data = call_deepseek_json("SYSTEM", "USER", temperature=0.5)
        self.assertEqual(data, {"ok": True, "_model": "deepseek-test"})
        self.assertEqual((calls[0].system, calls[0].user, calls[0].temperature), ("SYSTEM", "USER", 0.5))

    def test_provider_failures_become_messages_that_are_safe_to_show(self):
        cases = {
            401: "rejected our API key",
            429: "rate-limiting",
            500: "(HTTP 500)",
        }
        for status, fragment in cases.items():
            with self.subTest(status=status):
                with fake_deepseek(lambda request, status=status: status):
                    with self.assertRaises(AIServiceError) as raised:
                        call_deepseek_json("s", "u")
                self.assertIn(fragment, str(raised.exception))

    def test_a_timeout_and_an_unreachable_provider_are_told_apart(self):
        def times_out(request):
            raise requests.exceptions.Timeout()

        def unreachable(request):
            raise requests.exceptions.ConnectionError()

        with fake_deepseek(times_out):
            with self.assertRaisesMessage(AIServiceError, "timed out"):
                call_deepseek_json("s", "u")
        with fake_deepseek(unreachable):
            with self.assertRaisesMessage(AIServiceError, "Couldn't reach"):
                call_deepseek_json("s", "u")

    def test_a_missing_api_key_is_a_config_error(self):
        with override_settings(DEEPSEEK_API_KEY=""):
            with self.assertRaises(AIConfigError):
                call_deepseek_json("s", "u")

    def test_a_non_object_reply_is_rejected(self):
        with fake_deepseek(lambda request: ["not", "an", "object"]):
            with self.assertRaisesMessage(AIServiceError, "unexpected response"):
                call_deepseek_json("s", "u")


class SweepStuckAITasksCommandTests(TestCase):
    """Run on worker start-up so a killed worker never leaves a permanent spinner."""

    def setUp(self):
        self.profile = make_profile("sweep@example.com")

    def task(self, kind=AITask.JOB_ANALYSIS, *, idle_for=timedelta(0), state=None):
        job = JobPost.objects.create(profile=self.profile)
        task = AITask.start_for(self.profile, kind, job)
        if state == AITask.RUNNING:
            task.mark_running("Working")
        AITask.objects.filter(pk=task.pk).update(updated_at=timezone.now() - idle_for)
        return task

    def test_stale_queued_and_running_tasks_are_failed_and_fresh_ones_are_left(self):
        stale_queued = self.task(idle_for=timedelta(hours=2))
        stale_running = self.task(idle_for=timedelta(hours=2), state=AITask.RUNNING)
        fresh = self.task(idle_for=timedelta(minutes=5))
        out = StringIO()

        call_command("sweep_stuck_ai_tasks", seconds=3600, stdout=out)

        for task in (stale_queued, stale_running):
            task.refresh_from_db()
            self.assertEqual(task.state, AITask.FAILED)
            self.assertEqual(task.error_message, "This run was interrupted. Please try again.")
            self.assertIsNotNone(task.finished_at)
        fresh.refresh_from_db()
        self.assertEqual(fresh.state, AITask.QUEUED)
        self.assertIn("Swept 2 stuck AI task(s).", out.getvalue())

    def test_finished_tasks_are_never_touched(self):
        done = self.task(idle_for=timedelta(days=3))
        done.mark_done()
        AITask.objects.filter(pk=done.pk).update(updated_at=timezone.now() - timedelta(days=3))
        call_command("sweep_stuck_ai_tasks", seconds=60, stdout=StringIO())
        done.refresh_from_db()
        self.assertEqual(done.state, AITask.DONE)

    def test_the_window_defaults_to_the_setting(self):
        stale = self.task(idle_for=timedelta(seconds=120))
        with override_settings(AI_TASK_STALE_AFTER=60):
            call_command("sweep_stuck_ai_tasks", stdout=StringIO())
        stale.refresh_from_db()
        self.assertEqual(stale.state, AITask.FAILED)


class PruneAITasksCommandTests(TestCase):
    def setUp(self):
        self.profile = make_profile("prune@example.com")

    def finished(self, *, days_ago, state=AITask.DONE):
        job = JobPost.objects.create(profile=self.profile)
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job)
        task.mark_done() if state == AITask.DONE else task.mark_failed("nope")
        AITask.objects.filter(pk=task.pk).update(finished_at=timezone.now() - timedelta(days=days_ago))
        return task

    def test_old_finished_tasks_go_and_recent_or_live_ones_stay(self):
        old_done = self.finished(days_ago=45)
        old_failed = self.finished(days_ago=45, state=AITask.FAILED)
        recent = self.finished(days_ago=3)
        live = AITask.start_for(
            self.profile, AITask.JOB_ANALYSIS, JobPost.objects.create(profile=self.profile)
        )
        out = StringIO()

        call_command("prune_ai_tasks", days=30, stdout=out)

        remaining = set(AITask.objects.values_list("pk", flat=True))
        self.assertNotIn(old_done.pk, remaining)
        self.assertNotIn(old_failed.pk, remaining)
        self.assertIn(recent.pk, remaining)
        self.assertIn(live.pk, remaining)
        self.assertIn("Deleted 2 AI task(s).", out.getvalue())

    def test_a_dry_run_only_reports(self):
        old = self.finished(days_ago=45)
        out = StringIO()
        call_command("prune_ai_tasks", days=30, dry_run=True, stdout=out)
        self.assertTrue(AITask.objects.filter(pk=old.pk).exists())
        self.assertIn("Would delete 1 AI task(s) finished before ", out.getvalue())

    def test_the_window_defaults_to_the_setting(self):
        old = self.finished(days_ago=10)
        with override_settings(AI_TASK_RETENTION_DAYS=5):
            call_command("prune_ai_tasks", stdout=StringIO())
        self.assertFalse(AITask.objects.filter(pk=old.pk).exists())


class PromptLoaderTests(TestCase):
    """`load_prompt` fills `{{ placeholders }}` and touches nothing else."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        override = override_settings(PROMPTS_DIR=self.directory)
        override.enable()
        self.addCleanup(override.disable)

    def write(self, name, text):
        path = self.directory / f"{name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def test_a_prompt_without_placeholders_is_returned_exactly_as_written(self):
        text = 'Line one — “quoted”.\n\n{"key": {"nested": [1, 2]}} costs $5 \\n and {braces}\n'
        self.write("plain", text)
        self.assertEqual(load_prompt("plain"), text)

    def test_placeholders_are_filled_wherever_they_appear_however_they_are_spaced(self):
        self.write("spaced", "a={{x}} b={{ x }} c={{   x }} d={{ y }}")
        self.assertEqual(load_prompt("spaced", x="1", y="2"), "a=1 b=1 c=1 d=2")

    def test_only_a_well_formed_placeholder_is_a_placeholder(self):
        self.write("odd", '{{ }} {{1x}} {{ a b }} {"a": {"b": 1}} {{ ok }}')
        self.assertEqual(
            load_prompt("odd", ok="!"), '{{ }} {{1x}} {{ a b }} {"a": {"b": 1}} !'
        )

    def test_values_are_inserted_verbatim_and_never_reinterpreted(self):
        self.write("verbatim", "[{{ first }}] [{{ second }}]")
        result = load_prompt("verbatim", first="{{ second }} \\1 $x", second="B")
        self.assertEqual(result, "[{{ second }} \\1 $x] [B]")

    def test_values_are_converted_to_text(self):
        self.write("kinds", "{{ n }} / {{ label }}")
        with translation.override("en"):
            self.assertEqual(load_prompt("kinds", n=3, label=gettext_lazy("Overview")), "3 / Overview")

    def test_prompts_can_live_in_subdirectories(self):
        self.write("jobs/nested", "deep")
        self.assertEqual(load_prompt("jobs/nested"), "deep")

    def test_a_placeholder_without_a_value_is_an_error(self):
        self.write("needs", "{{ a }} {{ b }}")
        with self.assertRaisesMessage(PromptError, "no value for b"):
            load_prompt("needs", a="1")

    def test_a_value_the_prompt_never_uses_is_an_error(self):
        self.write("uses", "{{ a }}")
        with self.assertRaisesMessage(PromptError, "unused variable(s) typo"):
            load_prompt("uses", a="1", typo="2")
        self.write("none", "nothing to fill")
        with self.assertRaisesMessage(PromptError, "unused variable(s) extra"):
            load_prompt("none", extra="x")

    def test_a_missing_file_is_an_error_naming_the_file(self):
        with self.assertRaisesMessage(PromptError, "missing.txt"):
            load_prompt("missing")


class ShippedPromptTests(TestCase):
    """The prompts in `prompts/` follow the conventions the README promises."""

    def files(self):
        return sorted(Path(settings.PROMPTS_DIR).rglob("*.txt"))

    def name(self, path):
        return path.relative_to(settings.PROMPTS_DIR).with_suffix("").as_posix()

    def test_there_are_prompts_to_check(self):
        self.assertGreaterEqual(len(self.files()), 6)

    def test_every_prompt_loads_and_leaves_no_placeholder_unfilled(self):
        for path in self.files():
            with self.subTest(prompt=self.name(path)):
                variables = {name: "x" for name in PLACEHOLDER.findall(path.read_text(encoding="utf-8"))}
                text = load_prompt(self.name(path), **variables)
                self.assertTrue(text.strip())
                self.assertIsNone(PLACEHOLDER.search(text))

    def test_files_are_utf8_with_lf_endings_and_one_final_newline(self):
        for path in self.files():
            with self.subTest(prompt=self.name(path)):
                raw = path.read_bytes()
                raw.decode("utf-8")
                self.assertNotIn(b"\r", raw)
                self.assertTrue(raw.endswith(b"\n"))
                self.assertFalse(raw.endswith(b"\n\n"))

    def test_every_variable_a_prompt_declares_is_documented_in_the_readme(self):
        readme = (Path(settings.PROMPTS_DIR) / "README.md").read_text(encoding="utf-8")
        for path in self.files():
            with self.subTest(prompt=self.name(path)):
                self.assertIn(f"`{self.name(path)}.txt`", readme)
                for variable in PLACEHOLDER.findall(path.read_text(encoding="utf-8")):
                    self.assertIn(f"`{variable}`", readme)

    def test_the_dev_server_is_told_to_watch_the_prompt_directory(self):
        from core.apps import watch_prompt_files

        watched = []

        class Reloader:
            def watch_dir(self, path, glob):
                watched.append((path, glob))

        watch_prompt_files(Reloader())
        self.assertEqual(watched, [(settings.PROMPTS_DIR, "**/*.txt")])


class LanguageClauseTests(TestCase):
    def test_it_names_the_profile_language_twice_and_carries_no_stray_whitespace(self):
        for code, name in (("en", "English"), ("fr", "French")):
            with self.subTest(code=code):
                clause = language_clause(code)
                self.assertEqual(clause.count(f"in {name}"), 2)
                self.assertEqual(clause, clause.strip())
                self.assertNotIn("\n", clause)

    def test_anything_unsupported_falls_back_to_english(self):
        for code in (None, "", "xx", "  "):
            with self.subTest(code=code):
                self.assertEqual(language_clause(code), language_clause("en"))
        self.assertEqual(language_clause("fr-CA"), language_clause("fr"))
