"""Smoke tests: every route renders under the new layout, in both languages."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
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
        job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
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
        JobPost.objects.create(profile=self.profile, source_url="https://x.test/a")
        JobPost.objects.create(profile=self.profile, source_url="https://x.test/b")
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
        for needle in ["Ne devinez plus", "Trois étapes vers un CV personnalisé", "Créez votre compte"]:
            self.assertIn(needle, body, f"missing French string: {needle}")
        self.assertNotIn("Stop guessing whether you fit the job.", body)

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
        job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
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
        self.assertIn("Stop guessing whether you fit the job.", body)


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
        job = JobPost.objects.create(
            profile=self.profile, source_url="https://x.test/j", title="Backend Engineer"
        )
        url = reverse("jobs:delete", args=[job.pk])

        response = self.client.get(url)
        self.assertConfirmPage(response, contains=["Backend Engineer"])
        self.assertTrue(JobPost.objects.filter(pk=job.pk).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("jobs:list"))
        self.assertFalse(JobPost.objects.filter(pk=job.pk).exists())

    def test_job_post_delete_warns_about_its_tailored_resume(self):
        job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
        TailoredResume.objects.create(profile=self.profile, job=job, markdown="# CV")
        response = self.client.get(reverse("jobs:delete", args=[job.pk]))
        self.assertContains(response, "tailored resume")

    def test_deleting_a_job_post_cascades_to_its_tailored_resume(self):
        job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
        TailoredResume.objects.create(profile=self.profile, job=job, markdown="# CV")
        self.client.post(reverse("jobs:delete", args=[job.pk]))
        self.assertFalse(TailoredResume.objects.filter(job_id=job.pk).exists())

    def test_tailored_resume_delete_has_a_confirm_page(self):
        job = JobPost.objects.create(
            profile=self.profile, source_url="https://x.test/j", title="Data Analyst"
        )
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
