"""Smoke tests: every route renders under the new layout, in both languages."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from jobs.models import JobPost
from jobs.services.importer import apply_analysis

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
            "skills:list",
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
