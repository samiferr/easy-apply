from datetime import date
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from experience.models import ExperienceHighlight, WorkExperience
from jobs.models import JobElement, JobPost, JobSection
from skills.models import SkillCategory, UserSkill

from .models import TailoredResume
from .services.pdf import markdown_to_flowables, render_markdown_pdf
from .services.tailored import (
    EDUCATION,
    EXPERIENCE,
    LANGUAGES,
    SKILLS,
    SUMMARY,
    build_job_payload,
    generate_tailored_resume,
    load_template_sections,
    render_markdown,
)

User = get_user_model()

# Tests always run with DEBUG=False, where the manifest static-files storage
# insists on a `collectstatic` having been run; plain storage keeps the
# template-rendering tests below independent of the build step.
TEST_STORAGES = {
    **settings.STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

AI_RESPONSE = {
    "professional_summary": "Backend engineer with five years building Django services.",
    "skills": [
        {"group": "Programming", "items": ["Python", "Django"]},
        {"group": "Empty group", "items": []},
    ],
    "experience": [
        {
            "job_title": "Backend Engineer",
            "company": "Acme Corp",
            "location": "Montreal, QC",
            "dates": "Jan 2020 – Present",
            "highlights": ["Built a payments API serving 2M requests a day."],
        }
    ],
    "education": [
        {
            "title": "BSc Computer Science",
            "organization": "McGill University",
            "dates": "2015 – 2019",
            "details": "",
        }
    ],
    "languages": ["English — Native", "French — Fluent"],
    "_model": "deepseek-test",
}


class TailoredResumeTestMixin:
    def setUp(self):
        self.user = User.objects.create_user(
            email="jane@example.com", password="pw-for-tests-123", first_name="Jane", last_name="Doe"
        )
        Profile.objects.update_or_create(
            user=self.user, defaults={"phone": "+1 555 0100", "location": "Montreal, QC"}
        )
        self.user.refresh_from_db()
        self.job = JobPost.objects.create(
            user=self.user,
            source_url="https://example.com/job",
            status=JobPost.STATUS_COMPLETED,
            title="Senior Backend Engineer",
            company_name="Globex",
        )
        section = JobSection.objects.create(
            job=self.job, key="required_technical_skills"
        )
        JobElement.objects.create(
            section=section,
            text="5+ years of Python",
            match_status=JobElement.STRONG,
            match_evidence="5 years as Backend Engineer at Acme Corp.",
        )

    def add_profile_content(self):
        skill_category, _ = SkillCategory.objects.get_or_create(
            name="Programming Languages", kind=SkillCategory.TECHNICAL
        )
        UserSkill.objects.create(
            user=self.user, category=skill_category, name="Python", level=UserSkill.EXPERT
        )
        experience = WorkExperience.objects.create(
            user=self.user,
            job_title="Backend Engineer",
            company="Acme Corp",
            location="Montreal, QC",
            start_date=date(2020, 1, 1),
            is_current=True,
        )
        ExperienceHighlight.objects.create(experience=experience, text="Built a payments API.")


class TemplateSectionTests(TestCase):
    def test_sections_come_from_the_template_file(self):
        self.assertEqual(
            load_template_sections(),
            [
                (SUMMARY, "PROFESSIONAL SUMMARY"),
                (SKILLS, "SKILLS"),
                (EXPERIENCE, "WORKING EXPERIENCE"),
                (EDUCATION, "EDUCATION & PROFESSIONAL DEVELOPMENT"),
                (LANGUAGES, "LANGUAGES"),
            ],
        )


class RenderMarkdownTests(TailoredResumeTestMixin, TestCase):
    def test_header_and_sections_follow_the_template(self):
        markdown = render_markdown(self.user, AI_RESPONSE)

        self.assertTrue(markdown.startswith("**Jane Doe**"))
        self.assertIn("Montreal, QC  |  +1 555 0100  |  jane@example.com", markdown)

        headings = [line for line in markdown.splitlines() if line.startswith("## ")]
        self.assertEqual(
            headings,
            [
                "## **PROFESSIONAL SUMMARY**",
                "## **SKILLS**",
                "## **WORKING EXPERIENCE**",
                "## **EDUCATION & PROFESSIONAL DEVELOPMENT**",
                "## **LANGUAGES**",
            ],
        )
        self.assertIn("- **Programming:** Python, Django", markdown)
        self.assertNotIn("Empty group", markdown)
        self.assertIn("### **Backend Engineer** — Acme Corp", markdown)
        self.assertIn("*Jan 2020 – Present · Montreal, QC*", markdown)
        self.assertIn("- Built a payments API serving 2M requests a day.", markdown)
        self.assertIn("- English — Native", markdown)

    def test_sections_without_content_are_dropped(self):
        markdown = render_markdown(self.user, {"professional_summary": "Just a summary."})

        self.assertIn("## **PROFESSIONAL SUMMARY**", markdown)
        self.assertNotIn("## **SKILLS**", markdown)
        self.assertNotIn("## **LANGUAGES**", markdown)

    def test_malformed_ai_content_is_ignored_rather_than_rendered(self):
        markdown = render_markdown(
            self.user,
            {
                "professional_summary": 42,
                "skills": "not a list",
                "experience": [None, {"highlights": ["orphan"]}],
                "languages": ["", None, "English — Native"],
            },
        )

        self.assertNotIn("42", markdown)
        self.assertNotIn("orphan", markdown)
        self.assertIn("- English — Native", markdown)


class BuildJobPayloadTests(TailoredResumeTestMixin, TestCase):
    def test_requirements_carry_their_profile_match(self):
        payload = build_job_payload(self.job)

        self.assertEqual(payload["title"], "Senior Backend Engineer")
        self.assertEqual(payload["company"], "Globex")
        self.assertEqual(len(payload["requirements"]), 1)
        requirement = payload["requirements"][0]
        self.assertEqual(requirement["text"], "5+ years of Python")
        self.assertEqual(requirement["profile_match"], "strong")
        # Categories now come from the fixed section enum, not free-form AI names.
        self.assertEqual(requirement["category"], "Required Technical Skills")


class GenerateTailoredResumeTests(TailoredResumeTestMixin, TestCase):
    def test_empty_profile_is_skipped_before_calling_the_ai(self):
        with patch("resume.services.tailored.call_deepseek_json") as call:
            result = generate_tailored_resume(self.job, self.user)

        call.assert_not_called()
        self.assertEqual(result, {"skipped": "empty_profile"})
        self.assertFalse(TailoredResume.objects.exists())

    def test_draft_is_stored_as_markdown(self):
        self.add_profile_content()
        with patch(
            "resume.services.tailored.call_deepseek_json", return_value=dict(AI_RESPONSE)
        ) as call:
            result = generate_tailored_resume(self.job, self.user)

        call.assert_called_once()
        tailored_resume = result["tailored_resume"]
        self.assertEqual(tailored_resume.job, self.job)
        self.assertEqual(tailored_resume.ai_model, "deepseek-test")
        self.assertFalse(tailored_resume.edited_by_user)
        self.assertIn("## **PROFESSIONAL SUMMARY**", tailored_resume.markdown)
        self.assertIsNotNone(tailored_resume.generated_at)

    def test_regenerating_replaces_the_existing_draft(self):
        self.add_profile_content()
        TailoredResume.objects.create(
            user=self.user, job=self.job, markdown="old draft", edited_by_user=True
        )

        with patch("resume.services.tailored.call_deepseek_json", return_value=dict(AI_RESPONSE)):
            generate_tailored_resume(self.job, self.user)

        self.assertEqual(TailoredResume.objects.count(), 1)
        tailored_resume = TailoredResume.objects.get()
        self.assertNotIn("old draft", tailored_resume.markdown)
        self.assertFalse(tailored_resume.edited_by_user)


class MarkdownPDFTests(TestCase):
    MARKDOWN = (
        "**Jane Doe**\n\n"
        "Montreal, QC  |  jane@example.com\n\n"
        "## **PROFESSIONAL SUMMARY**\n\n"
        "Backend engineer & problem solver.\n\n"
        "## **WORKING EXPERIENCE**\n\n"
        "### **Backend Engineer** — Acme Corp\n"
        "*Jan 2020 – Present*\n\n"
        "- Built a payments API.\n"
        "- See [the docs](https://example.com/docs).\n"
    )

    def test_renders_a_pdf_document(self):
        pdf_bytes = render_markdown_pdf(self.MARKDOWN, title="Resume", author="Jane Doe")

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_pdf_contains_the_resume_text(self):
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(render_markdown_pdf(self.MARKDOWN)))
        text = "\n".join(page.extract_text() for page in reader.pages)

        self.assertIn("Jane Doe", text)
        self.assertIn("PROFESSIONAL SUMMARY", text)
        self.assertIn("Backend engineer & problem solver.", text)
        self.assertIn("Built a payments API.", text)

    def test_markup_characters_do_not_leak_into_the_page(self):
        story = markdown_to_flowables("## **SKILLS**\n\n- **Python** and *Django*\n")
        rendered = " ".join(getattr(flowable, "text", "") for flowable in story)

        self.assertIn("SKILLS", rendered)
        self.assertIn("<b>Python</b>", rendered)
        self.assertIn("<i>Django</i>", rendered)
        self.assertNotIn("**", rendered)

    def test_empty_markdown_still_produces_a_pdf(self):
        self.assertTrue(render_markdown_pdf("   ").startswith(b"%PDF"))

    def test_unbalanced_markup_falls_back_to_plain_text(self):
        # `*one **two* three**` converts to overlapping tags; the export
        # must still succeed rather than 500 on a hand-edited line.
        with self.assertLogs("resume.services.pdf", level="WARNING"):
            pdf_bytes = render_markdown_pdf("*one **two* three**\n\n## SKILLS\n")

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_html_in_the_markdown_is_escaped(self):
        story = markdown_to_flowables("Sales <b>up</b> & to the right\n")
        rendered = " ".join(getattr(flowable, "text", "") for flowable in story)

        self.assertIn("&amp;", rendered)
        self.assertNotIn("<b>up</b>", rendered)


@override_settings(STORAGES=TEST_STORAGES)
class TailoredResumeViewTests(TailoredResumeTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.add_profile_content()
        self.client.force_login(self.user)

    def generate(self):
        with patch("resume.services.tailored.call_deepseek_json", return_value=dict(AI_RESPONSE)):
            return self.client.post(reverse("resume:tailored_generate", args=[self.job.pk]))

    def test_generate_redirects_to_the_editor(self):
        response = self.generate()

        self.assertRedirects(response, reverse("resume:tailored", args=[self.job.pk]))
        self.assertTrue(TailoredResume.objects.filter(job=self.job).exists())

    def test_generate_requires_a_completed_analysis(self):
        self.job.status = JobPost.STATUS_FAILED
        self.job.save(update_fields=["status"])

        response = self.client.post(reverse("resume:tailored_generate", args=[self.job.pk]))

        self.assertRedirects(response, self.job.get_absolute_url())
        self.assertFalse(TailoredResume.objects.exists())

    def test_editing_marks_the_draft_as_user_edited(self):
        self.generate()

        response = self.client.post(
            reverse("resume:tailored", args=[self.job.pk]),
            {"markdown": "**Jane Doe**\n\n## **SKILLS**\n\n- Python\n", "action": "save"},
        )

        self.assertRedirects(response, reverse("resume:tailored", args=[self.job.pk]))
        tailored_resume = TailoredResume.objects.get(job=self.job)
        self.assertTrue(tailored_resume.edited_by_user)
        self.assertIn("- Python", tailored_resume.markdown)

    def test_save_and_export_returns_the_pdf_of_the_edited_text(self):
        self.generate()

        response = self.client.post(
            reverse("resume:tailored", args=[self.job.pk]),
            {"markdown": "**Jane Doe**\n\n## **SKILLS**\n\n- Rust\n", "action": "pdf"},
        )

        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("- Rust", TailoredResume.objects.get(job=self.job).markdown)

    def test_empty_markdown_is_rejected(self):
        self.generate()

        response = self.client.post(
            reverse("resume:tailored", args=[self.job.pk]), {"markdown": "   ", "action": "save"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "can&#x27;t be empty")

    def test_pdf_and_markdown_downloads(self):
        self.generate()

        pdf = self.client.get(reverse("resume:tailored_pdf", args=[self.job.pk]))
        markdown = self.client.get(reverse("resume:tailored_markdown", args=[self.job.pk]))

        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(pdf["Content-Disposition"], 'attachment; filename="jane-doe-globex-resume.pdf"')
        self.assertEqual(markdown["Content-Type"], "text/markdown; charset=utf-8")
        self.assertIn(b"## **PROFESSIONAL SUMMARY**", markdown.content)

    def test_another_users_resume_is_not_reachable(self):
        self.generate()
        other = User.objects.create_user(email="mallory@example.com", password="pw-for-tests-123")
        self.client.force_login(other)

        for name in ("resume:tailored", "resume:tailored_pdf", "resume:tailored_markdown"):
            self.assertEqual(self.client.get(reverse(name, args=[self.job.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("resume:tailored_generate", args=[self.job.pk])).status_code, 404
        )

    def test_login_is_required(self):
        self.client.logout()

        response = self.client.get(reverse("resume:tailored", args=[self.job.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
