"""Tests for the fixed-section refactor.

The AI is always stubbed: these assert our contract with it (the closed enum,
the scoped slices, the empty-slice short circuit), never the model's output.
"""

import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.utils import timezone, translation
from django.urls import reverse

from accounts.models import Profile
from core.models import AITask
from core.testing import fake_deepseek, pin_language
from core.utils import build_profile_slice, profile_slice_is_empty
from education.models import Certificate, Degree
from experience.models import ExperienceHighlight, WorkExperience
from jobs.models import JobElement, JobPost, JobSection
from jobs.sections import MATCHED_SECTION_KEYS, SECTION_KEYS
from jobs.services.importer import apply_analysis, normalize_sections
from languages.models import Language, UserLanguage
from preferences.models import BenefitPreference, get_or_create_preference
from resume.models import TailoredResume
from skills.models import SkillCategory, UserSkill
from staffportal.models import Plan, UsageMetric, UsageRecord
from staffportal.services import runtime_settings

JOB_TEXT = (
    "Senior Backend Engineer at Acme. You will design and ship Python "
    "services, own the payments API, mentor engineers and work with product. "
    "Requirements: 5+ years of Python, PostgreSQL, Celery and cloud "
    "infrastructure. Remote-friendly, salary 90k-120k EUR."
)

User = get_user_model()


def make_profile(email, *, language="en", name="Main"):
    """A user with one profile — the shape every screen assumes."""
    user = User.objects.create_user(email=email, password="pw12345678")
    profile = Profile.objects.filter(user=user).first()
    profile.name = name
    profile.language = language
    profile.save(update_fields=["name", "language"])
    return profile


def ai_payload(**overrides):
    data = {
        "title": "Senior Backend Engineer",
        "company_name": "Globex",
        "summary": "Build APIs.",
        "sections": [
            {"key": "overview", "body": "Build APIs.", "elements": []},
            {"key": "required_technical_skills", "body": "", "elements": ["Python", "PostgreSQL"]},
            {"key": "languages", "body": "", "elements": ["French — professional"]},
        ],
    }
    data.update(overrides)
    return data


class SectionEnumTests(TestCase):
    def test_thirteen_sections_in_canonical_order(self):
        self.assertEqual(len(SECTION_KEYS), 13)
        self.assertEqual(SECTION_KEYS[0], "overview")
        self.assertEqual(SECTION_KEYS[-1], "red_flags")

    def test_worth_noting_and_red_flags_are_separate(self):
        self.assertIn("worth_noting", SECTION_KEYS)
        self.assertIn("red_flags", SECTION_KEYS)

    def test_unmatched_sections_are_never_matched(self):
        for key in ("overview", "company", "how_to_apply", "worth_noting", "red_flags"):
            self.assertNotIn(key, MATCHED_SECTION_KEYS)


class NormalizeSectionsTests(TestCase):
    def test_invented_section_is_discarded(self):
        data = ai_payload(sections=[
            {"key": "required_technical_skills", "body": "", "elements": ["Python"]},
            {"key": "perks_and_vibes", "body": "Free snacks", "elements": ["Ping pong"]},
            {"key": "TOTALLY_MADE_UP", "body": "", "elements": ["x"]},
        ])
        keys = [entry["key"] for entry in normalize_sections(data)]
        self.assertEqual(keys, ["required_technical_skills"])

    def test_duplicate_keys_are_merged(self):
        data = ai_payload(sections=[
            {"key": "required_technical_skills", "body": "", "elements": ["Python"]},
            {"key": "required_technical_skills", "body": "", "elements": ["Go"]},
        ])
        result = normalize_sections(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["elements"], ["Python", "Go"])

    def test_prose_section_never_keeps_elements(self):
        data = ai_payload(sections=[{"key": "overview", "body": "Text", "elements": ["nope"]}])
        self.assertEqual(normalize_sections(data)[0]["elements"], [])

    def test_row_section_never_keeps_prose(self):
        data = ai_payload(sections=[
            {"key": "languages", "body": "should be dropped", "elements": ["French"]}
        ])
        self.assertEqual(normalize_sections(data)[0]["body"], "")


class ApplyAnalysisTests(TestCase):
    def setUp(self):
        self.profile = make_profile("a@example.com")
        self.job = JobPost.objects.create(profile=self.profile)

    def test_only_valid_sections_are_created(self):
        data = ai_payload(sections=[
            {"key": "required_technical_skills", "body": "", "elements": ["Python"]},
            {"key": "made_up_section", "body": "", "elements": ["x"]},
        ])
        apply_analysis(self.job, data, "raw text")
        keys = set(self.job.sections.values_list("key", flat=True))
        self.assertIn("required_technical_skills", keys)
        self.assertNotIn("made_up_section", keys)
        self.assertTrue(keys.issubset(set(SECTION_KEYS)))

    def test_reanalysis_replaces_previous_sections(self):
        apply_analysis(self.job, ai_payload(), "raw")
        first = set(self.job.sections.values_list("id", flat=True))
        apply_analysis(self.job, ai_payload(), "raw")
        second = set(self.job.sections.values_list("id", flat=True))
        self.assertFalse(first & second)

    def test_match_summary_ignores_prose_sections(self):
        apply_analysis(self.job, ai_payload(), "raw")
        JobElement.objects.filter(section__key="required_technical_skills").update(
            match_status=JobElement.STRONG
        )
        summary = self.job.element_match_summary()
        # Overview is prose — its rows (there are none) must not be counted.
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["strong"], 2)


class ProfileSliceTests(TestCase):
    def setUp(self):
        self.profile = make_profile("b@example.com")
        category = SkillCategory.objects.create(name="Programming", kind=SkillCategory.TECHNICAL)
        UserSkill.objects.create(profile=self.profile, category=category, name="Python", level=4)

    def test_technical_section_gets_only_technical_skills(self):
        data = build_profile_slice(self.profile, "required_technical_skills")
        self.assertIn("technical_skills", data)
        for forbidden in ("soft_skills", "languages", "degrees", "experience", "benefits_wanted"):
            self.assertNotIn(forbidden, data, f"{forbidden} leaked into the technical slice")

    def test_languages_section_gets_only_languages(self):
        data = build_profile_slice(self.profile, "languages")
        self.assertEqual(set(data.keys()), {"languages"})

    def test_responsibilities_gets_experience_and_technical_skills(self):
        data = build_profile_slice(self.profile, "responsibilities")
        self.assertEqual(set(data.keys()), {"experience", "technical_skills"})

    def test_prose_section_gets_nothing(self):
        self.assertEqual(build_profile_slice(self.profile, "overview"), {})

    def test_compensation_slice_has_no_skills(self):
        get_or_create_preference(self.profile)
        data = build_profile_slice(self.profile, "compensation_benefits")
        self.assertNotIn("technical_skills", data)
        self.assertIn("benefits_wanted", data)


class EmptySliceShortCircuitTests(TestCase):
    def setUp(self):
        self.profile = make_profile("c@example.com")
        self.job = JobPost.objects.create(profile=self.profile)
        apply_analysis(self.job, ai_payload(), "raw")

    def test_empty_slice_never_calls_the_api(self):
        from jobs.services.matcher import match_section_to_profile

        section = self.job.sections.get(key="languages")
        with patch("jobs.services.deepseek_client.call_deepseek_json") as mocked:
            result = match_section_to_profile(section)
        mocked.assert_not_called()
        self.assertEqual(result["skipped"], "empty_slice")
        for element in section.elements.all():
            self.assertEqual(element.match_status, JobElement.NONE)
            self.assertTrue(element.match_evidence)

    def test_populated_slice_sends_only_its_own_data(self):
        from jobs.services.matcher import match_section_to_profile

        category = SkillCategory.objects.create(name="Programming", kind=SkillCategory.TECHNICAL)
        UserSkill.objects.create(profile=self.profile, category=category, name="Python", level=4)
        section = self.job.sections.get(key="required_technical_skills")

        captured = {}

        def fake_call(system_prompt, user_content, **kwargs):
            captured["payload"] = user_content
            ids = list(section.elements.values_list("id", flat=True))
            return {"matches": [
                {"element_id": i, "status": "strong", "evidence": "Python listed as Expert."}
                for i in ids
            ]}

        with patch("core.ai.call_deepseek_json", side_effect=fake_call), \
             patch("jobs.services.deepseek_client.call_deepseek_json", side_effect=fake_call):
            match_section_to_profile(section)

        payload = captured["payload"]
        self.assertIn("technical_skills", payload)
        self.assertNotIn("soft_skills", payload)
        self.assertNotIn("degrees", payload)
        section.refresh_from_db()
        self.assertEqual(section.match_state, JobSection.DONE)


class ReadJobTextTests(TestCase):
    """Step 1 of the pipeline reads the pasted text and never touches the network."""

    def setUp(self):
        self.profile = make_profile("read@example.com")

    def test_it_hands_the_pasted_description_to_the_next_step(self):
        from jobs.tasks import read_job_text

        job = JobPost.objects.create(profile=self.profile, description_text=f"  {JOB_TEXT}  ")
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job, steps_total=2)
        payload = read_job_text.run(job.pk, task.pk)

        self.assertFalse(payload["failed"])
        self.assertEqual(payload["raw_text"], JOB_TEXT)
        job.refresh_from_db()
        self.assertEqual(job.status, JobPost.STATUS_PROCESSING)

    def test_a_job_with_no_text_fails_with_a_message_instead_of_raising(self):
        from jobs.tasks import read_job_text

        job = JobPost.objects.create(profile=self.profile, description_text="")
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job, steps_total=2)
        payload = read_job_text.run(job.pk, task.pk)

        self.assertTrue(payload["failed"])
        job.refresh_from_db()
        self.assertEqual(job.status, JobPost.STATUS_FAILED)
        self.assertTrue(job.error_message, "the user must be told why")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ViewsNeverCallAITests(TestCase):
    def setUp(self):
        self.profile = make_profile("d@example.com")
        self.client.force_login(self.profile.user)

    def test_submitting_a_job_enqueues_and_redirects(self):
        with patch("jobs.tasks.read_job_text.apply_async") as _read, \
             patch("celery.canvas._chain.apply_async") as chain_apply:
            chain_apply.return_value = type("R", (), {"id": "fake-id"})()
            response = self.client.post(
                reverse("jobs:add"),
                {"description_text": JOB_TEXT},
            )
        self.assertEqual(response.status_code, 302)
        job = JobPost.objects.get()
        task = AITask.latest_for(job, AITask.JOB_ANALYSIS)
        self.assertIsNotNone(task, "submitting a job must create an AITask")
        self.assertEqual(task.state, AITask.QUEUED)

    def test_the_pasted_text_is_what_gets_stored(self):
        with patch("jobs.tasks.read_job_text.apply_async"), \
             patch("celery.canvas._chain.apply_async") as chain_apply:
            chain_apply.return_value = type("R", (), {"id": "fake-id"})()
            self.client.post(reverse("jobs:add"), {"description_text": JOB_TEXT})
        self.assertEqual(JobPost.objects.get().description_text, JOB_TEXT)

    def test_a_job_post_cannot_be_submitted_without_its_text(self):
        """There is no URL to fall back on — an empty or stub paste is the one
        thing the form has to catch, since the pipeline has nothing to read."""
        for payload in [{}, {"description_text": "   "}, {"description_text": "Backend dev"}]:
            with self.subTest(payload=payload):
                response = self.client.post(reverse("jobs:add"), payload)
                self.assertEqual(response.status_code, 200, "the form must redisplay")
                self.assertTrue(response.context["form"].errors)
                self.assertFalse(JobPost.objects.exists())

    def test_task_status_endpoint_is_owner_scoped(self):
        job = JobPost.objects.create(profile=self.profile)
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, job, steps_total=3)
        response = self.client.get(reverse("core:task_status", args=[task.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["steps_total"], 3)

        other = User.objects.create_user(email="e@example.com", password="pw12345678")
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("core:task_status", args=[task.pk])).status_code, 404
        )


class AITaskProgressTests(TestCase):
    def setUp(self):
        self.profile = make_profile("f@example.com")
        self.job = JobPost.objects.create(profile=self.profile)

    def test_single_step_task_is_indeterminate(self):
        task = AITask.start_for(self.profile, AITask.TAILORED_RESUME, self.job, steps_total=1)
        self.assertTrue(task.is_indeterminate)
        self.assertEqual(task.percent, 0)

    def test_percent_tracks_steps(self):
        task = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job, steps_total=4)
        task.advance("one")
        task.advance("two")
        self.assertEqual(task.percent, 50)
        task.mark_done()
        self.assertEqual(task.percent, 100)
        self.assertTrue(task.is_terminal)

    def test_starting_a_new_task_cancels_the_previous_one(self):
        first = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        first.refresh_from_db()
        self.assertEqual(first.state, AITask.CANCELED)


class BrokerDownTests(TestCase):
    """A broker outage must never reach the view as an exception.

    The failure is simulated rather than produced by a dead port: Celery's own
    reconnect loop takes ~13s per call, which does not belong in a test suite.
    What matters is that `core.tasks.dispatch` catches it and leaves the user a
    failed AITask with a Retry button.
    """

    def setUp(self):
        self.profile = make_profile("nw@example.com")
        self.client.force_login(self.profile.user)

    @staticmethod
    def _broker_down():
        from kombu.exceptions import OperationalError

        return patch(
            "celery.canvas._chain.apply_async",
            side_effect=OperationalError("Cannot connect to redis://localhost:6379/0"),
        )

    def test_enqueue_does_not_raise_when_the_broker_is_down(self):
        from jobs.tasks import enqueue_job_analysis

        job = JobPost.objects.create(profile=self.profile)
        # The message is stored already translated, so pin the language rather
        # than depending on whatever a previous test left active.
        with translation.override("en"), self._broker_down():
            task = enqueue_job_analysis(job)  # must not raise

        job.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(task.state, AITask.FAILED)
        self.assertIn("unavailable", task.error_message.lower())
        self.assertEqual(job.status, JobPost.STATUS_FAILED)
        self.assertTrue(job.error_message, "the user must be told why")

    def test_the_submit_view_returns_a_redirect_not_a_500(self):
        with self._broker_down():
            response = self.client.post(
                reverse("jobs:add"),
                {"description_text": JOB_TEXT},
            )
        self.assertEqual(response.status_code, 302)

    def test_pages_still_render(self):
        for name in ["core:dashboard", "jobs:list"]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class ProfileLanguageTests(TestCase):
    """The profile's language — not the browser's — drives every AI call."""

    def setUp(self):
        self.profile = make_profile("lang@example.com", language="fr", name="Analyste")
        self.job = JobPost.objects.create(profile=self.profile)
        apply_analysis(self.job, ai_payload(), "raw", language="fr")

    def test_extraction_asks_for_the_profile_language(self):
        from jobs.services.deepseek_client import analyze_job_text

        captured = {}

        def fake_call(system_prompt, user_content, **kwargs):
            captured["payload"] = user_content
            return {}

        with patch("core.ai.call_deepseek_json", side_effect=fake_call), \
             patch("jobs.services.deepseek_client.call_deepseek_json", side_effect=fake_call):
            analyze_job_text("raw posting", language=self.profile.language)

        self.assertIn("in French", captured["payload"])
        self.assertNotIn("in English", captured["payload"])

    def test_matching_uses_the_profile_language_even_under_an_english_ui(self):
        from jobs.services.matcher import match_section_to_profile

        category = SkillCategory.objects.create(name="Programming", kind=SkillCategory.TECHNICAL)
        UserSkill.objects.create(profile=self.profile, category=category, name="Python", level=4)
        section = self.job.sections.get(key="required_technical_skills")

        captured = {}

        def fake_call(system_prompt, user_content, **kwargs):
            captured["payload"] = user_content
            return {"matches": [
                {"element_id": e.id, "status": "strong", "evidence": "Python."}
                for e in section.elements.all()
            ]}

        with translation.override("en"), \
             patch("core.ai.call_deepseek_json", side_effect=fake_call), \
             patch("jobs.services.deepseek_client.call_deepseek_json", side_effect=fake_call):
            match_section_to_profile(section)

        payload = captured["payload"]
        self.assertIn("in French", payload)
        # The section label and the profile's own display strings travel in the
        # same payload, so they have to be French too.
        self.assertIn("Compétences techniques requises", payload)
        self.assertIn("Expert", payload)

    def test_an_empty_slice_writes_its_hint_in_the_profile_language(self):
        from jobs.services.matcher import match_section_to_profile

        section = self.job.sections.get(key="languages")
        with translation.override("en"):
            match_section_to_profile(section)

        evidence = section.elements.first().match_evidence
        self.assertIn("Aucune langue", evidence)

    def test_two_profiles_analyze_the_same_job_in_their_own_languages(self):
        english = Profile.objects.create(
            user=self.profile.user, name="Backend", language="en"
        )
        english_job = JobPost.objects.create(profile=english)
        apply_analysis(english_job, ai_payload(), "raw", language="en")

        seen = []

        def fake_call(system_prompt, user_content, **kwargs):
            seen.append(user_content)
            return {"matches": []}

        from jobs.services.matcher import match_section_to_profile

        category = SkillCategory.objects.create(name="Programming", kind=SkillCategory.TECHNICAL)
        UserSkill.objects.create(profile=self.profile, category=category, name="Python", level=4)
        UserSkill.objects.create(profile=english, category=category, name="Python", level=4)

        with patch("core.ai.call_deepseek_json", side_effect=fake_call), \
             patch("jobs.services.deepseek_client.call_deepseek_json", side_effect=fake_call):
            match_section_to_profile(self.job.sections.get(key="required_technical_skills"))
            match_section_to_profile(
                english_job.sections.get(key="required_technical_skills")
            )

        self.assertIn("in French", seen[0])
        self.assertIn("in English", seen[1])


# ---------------------------------------------------------------------------
# Characterization tests — pin the use cases before they move into services.py.
#
# These run the real Celery tasks eagerly and stub only the HTTP call to the AI
# provider (`core.testing.fake_deepseek`), so they say nothing about where the
# code lives.
# ---------------------------------------------------------------------------
def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


EXTRACTION = {
    "title": "Senior Backend Engineer",
    "company_name": "Globex",
    "summary": "Build APIs.",
    "work_arrangement": "hybrid",
    "sections": [
        {"key": "overview", "body": "Build APIs.", "elements": []},
        {"key": "required_technical_skills", "body": "", "elements": ["Python", "PostgreSQL"]},
        {"key": "languages", "body": "", "elements": ["French — professional"]},
    ],
}


def is_match_call(request):
    return '"candidate_profile"' in request.user


def match_payload(request):
    """The JSON the matcher sent: the section label, its rows and the profile slice."""
    return json.loads(request.user.split("\n\n", 1)[1])


def answering(status="strong", evidence="Covered by the profile.", *, extraction=None):
    """A model that extracts `extraction` and gives every row the same verdict."""

    def reply(request):
        if is_match_call(request):
            return {
                "matches": [
                    {"element_id": row["id"], "status": status, "evidence": evidence}
                    for row in match_payload(request)["elements"]
                ]
            }
        return dict(extraction or EXTRACTION)

    return reply


def add_python(profile, level=4):
    category = SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).first()
    return UserSkill.objects.create(profile=profile, category=category, name="Python", level=level)


def make_job(profile, **fields):
    return JobPost.objects.create(
        profile=profile, description_text=fields.pop("description_text", JOB_TEXT), **fields
    )


FULL_ANALYSIS = {
    "title": "Senior Backend Engineer",
    "company_name": "Globex",
    "sections": [
        {"key": "overview", "body": "Build APIs.", "elements": []},
        {"key": "location_arrangement", "body": "", "elements": ["Remote (Canada)"]},
        {"key": "compensation_benefits", "body": "", "elements": ["Dental care"]},
        {"key": "responsibilities", "body": "", "elements": ["Design and run APIs"]},
        {"key": "required_technical_skills", "body": "", "elements": ["Python", "PostgreSQL"]},
        {"key": "desirable_soft_skills", "body": "", "elements": ["Mentoring"]},
        {"key": "languages", "body": "", "elements": ["French — professional"]},
        {"key": "education_certifications", "body": "", "elements": ["BSc in Computer Science"]},
    ],
}


def analyzed_job(profile, **fields):
    job = make_job(profile, status=JobPost.STATUS_COMPLETED, **fields)
    apply_analysis(job, dict(FULL_ANALYSIS), JOB_TEXT, language=profile.language)
    return job


def element_of(job, key, text=None):
    elements = JobElement.objects.filter(section__job=job, section__key=key)
    return elements.get(text=text) if text else elements.first()


class AnalysisPipelineTests(TestCase):
    """UC-05.1 to UC-05.5 through the real tasks: read, extract, fan out, match, finalize."""

    def setUp(self):
        from jobs.tasks import enqueue_job_analysis

        pin_language(self)  # the tasks store translated messages
        self.enqueue = enqueue_job_analysis
        self.profile = make_profile("pipe@example.com")
        add_python(self.profile)
        self.job = make_job(self.profile)

    def run_pipeline(self, reply):
        with fake_deepseek(reply) as calls:
            task = self.enqueue(self.job)
        self.job.refresh_from_db()
        task.refresh_from_db()
        return task, calls

    def test_a_pasted_posting_ends_as_matched_sections(self):
        task, _calls = self.run_pipeline(answering())

        self.assertEqual(self.job.status, JobPost.STATUS_COMPLETED)
        self.assertEqual((self.job.title, self.job.company_name), ("Senior Backend Engineer", "Globex"))
        self.assertEqual(self.job.analysis_language, "en")
        self.assertEqual(self.job.ai_model, "deepseek-test")
        self.assertIsNotNone(self.job.analyzed_at)
        self.assertIsNotNone(self.job.profile_matched_at)
        skills = self.job.sections.get(key="required_technical_skills")
        self.assertEqual(skills.match_state, JobSection.DONE)
        self.assertEqual(
            {e.text: e.match_status for e in skills.elements.all()},
            {"Python": "strong", "PostgreSQL": "strong"},
        )
        self.assertEqual(self.job.sections.get(key="overview").match_state, JobSection.IDLE)
        self.assertEqual(self.job.element_match_summary()["strong"], 2)
        self.assertEqual((task.state, task.percent, task.current_step), (AITask.DONE, 100, "Analysis complete"))

    def test_progress_counts_the_two_reading_steps_and_one_per_matched_section(self):
        task, _calls = self.run_pipeline(answering())
        matched = self.job.sections.filter(key__in=MATCHED_SECTION_KEYS, elements__isnull=False)
        self.assertEqual(task.steps_total, 2 + matched.distinct().count())
        self.assertEqual(task.steps_done, task.steps_total)

    def test_only_sections_with_something_to_compare_reach_the_model(self):
        """Extraction is one call; a section whose profile slice is empty costs nothing."""
        _task, calls = self.run_pipeline(answering())
        self.assertEqual(len(calls), 2, "one extraction + one match (languages/location are empty)")
        extraction, match = calls
        self.assertFalse(is_match_call(extraction))
        self.assertTrue(is_match_call(match))
        self.assertEqual(match_payload(match)["section"], "Required Technical Skills")
        languages = self.job.sections.get(key="languages")
        self.assertEqual(languages.match_state, JobSection.DONE)
        self.assertEqual(languages.elements.get().match_status, JobElement.NONE)
        self.assertIn("No languages recorded", languages.elements.get().match_evidence)

    def test_the_two_kinds_of_call_use_their_own_prompt_and_temperature(self):
        _task, (extraction, match) = self.run_pipeline(answering())
        self.assertIn("expert job-post analyst", extraction.system)
        self.assertIn("expert technical recruiter", match.system)
        self.assertEqual((extraction.temperature, match.temperature), (0.2, 0.1))
        self.assertIn("--- Job posting text ---", extraction.user)
        self.assertIn(JOB_TEXT, extraction.user)

    def test_the_posting_is_truncated_before_it_is_sent(self):
        self.job.description_text = "A" * 30000
        self.job.save()
        _task, (extraction, _match) = self.run_pipeline(answering())
        self.assertEqual(extraction.user.count("A"), 18000)

    def test_the_profile_language_drives_every_call(self):
        french = make_profile("pipe-fr@example.com", language="fr", name="Analyste")
        add_python(french)
        self.job = make_job(french)
        _task, calls = self.run_pipeline(answering())
        self.assertTrue(all("in French" in call.user for call in calls))
        self.assertEqual(self.job.analysis_language, "fr")

    def test_an_unreadable_answer_fails_the_job_without_a_retry(self):
        task, calls = self.run_pipeline(lambda request: "this is not json")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.job.status, JobPost.STATUS_FAILED)
        self.assertIn("invalid JSON", self.job.error_message)
        self.assertEqual(task.state, AITask.FAILED)
        self.assertIn("invalid JSON", task.error_message)
        self.assertFalse(self.job.sections.exists())

    def test_a_rejected_key_fails_the_job_without_a_retry(self):
        task, calls = self.run_pipeline(lambda request: 401)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.job.status, JobPost.STATUS_FAILED)
        self.assertEqual(task.state, AITask.FAILED)
        self.assertIn("rejected our API key", task.error_message)

    def test_a_missing_api_key_is_reported_not_raised(self):
        with override_settings(DEEPSEEK_API_KEY=""):
            task = self.enqueue(self.job)
        self.job.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(self.job.status, JobPost.STATUS_FAILED)
        self.assertIn("DEEPSEEK_API_KEY", self.job.error_message)
        self.assertEqual(task.state, AITask.FAILED)

    def test_a_posting_with_no_text_fails_before_calling_the_model(self):
        self.job.description_text = "   "
        self.job.save()
        task, calls = self.run_pipeline(answering())
        self.assertEqual(calls, [])
        self.assertEqual(self.job.status, JobPost.STATUS_FAILED)
        self.assertEqual(self.job.error_message, "This job post has no description text to analyze.")
        self.assertEqual(task.state, AITask.FAILED)

    def test_a_section_that_cannot_be_matched_fails_alone(self):
        """UC-05.5: the other sections finish, and the task still completes."""
        UserLanguage.objects.create(
            profile=self.profile,
            language=Language.objects.create(name="French"),
            proficiency=UserLanguage.NATIVE,
        )

        def reply(request):
            if is_match_call(request) and match_payload(request)["section"] == "Languages":
                return 401
            return answering()(request)

        task, _calls = self.run_pipeline(reply)

        languages = self.job.sections.get(key="languages")
        self.assertEqual(languages.match_state, JobSection.FAILED)
        self.assertIn("rejected our API key", languages.match_error)
        skills = self.job.sections.get(key="required_technical_skills")
        self.assertEqual(skills.match_state, JobSection.DONE)
        self.assertEqual(self.job.status, JobPost.STATUS_COMPLETED)
        self.assertEqual(task.state, AITask.DONE)

    def test_when_every_section_fails_the_task_is_marked_failed(self):
        only_skills = {
            "title": "Only skills",
            "sections": [{"key": "required_technical_skills", "body": "", "elements": ["Python"]}],
        }

        def reply(request):
            return 401 if is_match_call(request) else dict(only_skills)

        task, _calls = self.run_pipeline(reply)

        self.assertEqual(task.state, AITask.FAILED)
        self.assertEqual(task.error_message, "Every section failed to match. Please try again.")
        self.assertEqual(
            self.job.sections.get(key="required_technical_skills").match_state, JobSection.FAILED
        )
        self.assertEqual(self.job.status, JobPost.STATUS_COMPLETED)

    def test_sections_with_empty_slices_count_as_matched_even_when_another_fails(self):
        def reply(request):
            return 401 if is_match_call(request) else dict(EXTRACTION)

        task, _calls = self.run_pipeline(reply)

        self.assertEqual(task.state, AITask.DONE)
        self.assertEqual(self.job.sections.get(key="languages").match_state, JobSection.DONE)

    def test_a_reanalysis_replaces_the_sections(self):
        self.run_pipeline(answering())
        first_ids = set(self.job.sections.values_list("pk", flat=True))
        replacement = {**EXTRACTION, "sections": [
            {"key": "required_technical_skills", "body": "", "elements": ["Go"]},
        ]}
        self.run_pipeline(answering(extraction=replacement))
        self.assertTrue(first_ids.isdisjoint(self.job.sections.values_list("pk", flat=True)))
        self.assertEqual(
            [e.text for e in element_of(self.job, "required_technical_skills").section.elements.all()],
            ["Go"],
        )

    def test_a_second_run_cancels_the_first_progress_record(self):
        first = self.enqueue(self.job)
        second = self.enqueue(self.job)
        first.refresh_from_db()
        self.assertNotEqual(first.pk, second.pk)
        self.assertIn(first.state, (AITask.CANCELED, AITask.FAILED, AITask.DONE))

    def test_the_broker_being_down_does_not_raise(self):
        from kombu.exceptions import OperationalError

        with translation.override("en"), patch(
            "celery.canvas._chain.apply_async", side_effect=OperationalError("down")
        ):
            task = self.enqueue(self.job)
        self.job.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual((task.state, self.job.status), (AITask.FAILED, JobPost.STATUS_FAILED))
        self.assertIn("unavailable", task.error_message.lower())


class JobListTests(TestCase):
    def setUp(self):
        self.profile = make_profile("list@example.com")
        self.client.force_login(self.profile.user)
        self.backend = JobPost.objects.create(
            profile=self.profile, title="Backend Engineer", company_name="Acme",
            location="Paris", status=JobPost.STATUS_COMPLETED,
        )
        self.analyst = JobPost.objects.create(
            profile=self.profile, title="Data Analyst", company_name="Globex",
            location="Berlin", status=JobPost.STATUS_FAILED,
        )
        self.frontend = JobPost.objects.create(
            profile=self.profile, title="Frontend Dev", company_name="Initech",
            location="Remote", status=JobPost.STATUS_PENDING,
        )

    def listed(self, **params):
        response = self.client.get(reverse("jobs:list"), params)
        self.assertEqual(response.status_code, 200)
        return [job.title for job in response.context["job_posts"]]

    def test_newest_first(self):
        self.assertEqual(self.listed(), ["Frontend Dev", "Data Analyst", "Backend Engineer"])

    def test_search_matches_title_company_or_location_ignoring_case(self):
        self.assertEqual(self.listed(q="acme"), ["Backend Engineer"])
        self.assertEqual(self.listed(q="BERLIN"), ["Data Analyst"])
        self.assertEqual(self.listed(q="dev"), ["Frontend Dev"])
        self.assertEqual(self.listed(q="  initech  "), ["Frontend Dev"])
        self.assertEqual(self.listed(q="nothing like this"), [])

    def test_status_filter_and_an_unknown_status_is_ignored(self):
        self.assertEqual(self.listed(status="failed"), ["Data Analyst"])
        self.assertEqual(self.listed(status="completed"), ["Backend Engineer"])
        self.assertEqual(len(self.listed(status="nonsense")), 3)

    def test_filters_combine(self):
        self.assertEqual(self.listed(q="a", status="failed"), ["Data Analyst"])

    def test_the_context_echoes_the_filters_and_counts_everything(self):
        response = self.client.get(reverse("jobs:list"), {"q": "acme", "status": "completed"})
        self.assertEqual(response.context["q"], "acme")
        self.assertEqual(response.context["status"], "completed")
        self.assertEqual(response.context["total_count"], 3)
        self.assertEqual(response.context["status_choices"], JobPost.STATUS_CHOICES)

    def test_twenty_to_a_page(self):
        for index in range(22):
            JobPost.objects.create(profile=self.profile, title=f"Extra {index}")
        first = self.client.get(reverse("jobs:list")).context
        second = self.client.get(reverse("jobs:list"), {"page": 2}).context
        self.assertEqual(len(first["job_posts"]), 20)
        self.assertEqual(len(second["job_posts"]), 5)
        self.assertEqual(first["total_count"], 25)

    def test_another_profiles_jobs_never_appear(self):
        other = make_profile("list-other@example.com")
        JobPost.objects.create(profile=other, title="Someone else's")
        self.assertNotIn("Someone else's", self.listed())
        self.assertEqual(self.client.get(reverse("jobs:list")).context["total_count"], 3)


class JobSubmissionTests(TestCase):
    """UC-05.1: paste a posting, get it queued, spend one analysis."""

    def setUp(self):
        runtime_settings.invalidate()
        self.addCleanup(runtime_settings.invalidate)
        self.plan = Plan.objects.create(
            slug="free", name="Free", price_cents=0, is_default=True, monthly_job_analyses=1
        )
        self.profile = make_profile("submit@example.com")
        self.client.force_login(self.profile.user)

    def analyses_used(self):
        record = UsageRecord.objects.filter(
            user=self.profile.user, metric=UsageMetric.JOB_ANALYSIS
        ).first()
        return record.count if record else 0

    def submit(self, text=JOB_TEXT):
        return self.client.post(reverse("jobs:add"), {"description_text": text})

    def test_a_submitted_posting_is_analysed_under_the_active_profile(self):
        with fake_deepseek(answering()) as calls:
            response = self.submit()
        job = JobPost.objects.get()
        self.assertRedirects(response, job.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(job.profile, self.profile)
        self.assertEqual(job.description_text, JOB_TEXT)
        self.assertEqual(job.status, JobPost.STATUS_COMPLETED)
        self.assertEqual(len(calls), 1, "no skills recorded, so nothing else reaches the model")
        self.assertEqual(
            flash(response),
            ["Analyzing this job post — the sections will fill in as they finish."],
        )
        self.assertEqual(self.analyses_used(), 1)

    def test_the_analysis_is_metered_even_though_quotas_are_not_enforced(self):
        with fake_deepseek(answering()):
            self.submit()
        self.assertEqual(self.analyses_used(), 1)

    def test_an_exhausted_allowance_keeps_the_pasted_text_and_creates_nothing(self):
        runtime_settings.set_value("enforce_quotas", True)
        with fake_deepseek(answering()):
            self.submit()
        response = self.submit(JOB_TEXT + " Second posting.")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Second posting.")
        self.assertEqual(
            flash(response)[-1],
            "You've used all 1 of this month's job analyses. Your allowance resets at the "
            "start of your next billing period.",
        )
        self.assertEqual(JobPost.objects.count(), 1)
        self.assertEqual(self.analyses_used(), 1)

    def test_a_plan_without_the_feature_says_so(self):
        Plan.objects.filter(pk=self.plan.pk).update(monthly_job_analyses=0)
        runtime_settings.set_value("enforce_quotas", True)
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(flash(response), ["Your plan doesn't include this feature. Upgrade to use it."])
        self.assertFalse(JobPost.objects.exists())

    def test_the_ai_kill_switch_blocks_even_when_quotas_are_off(self):
        runtime_settings.set_value("ai_features_enabled", False)
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            flash(response),
            ["AI features are temporarily unavailable while we carry out maintenance. "
             "Please try again shortly."],
        )
        self.assertFalse(JobPost.objects.exists())
        self.assertEqual(self.analyses_used(), 0)

    def test_a_too_short_posting_is_a_form_error_and_costs_nothing(self):
        response = self.submit("Backend dev")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(JobPost.objects.exists())
        self.assertEqual(self.analyses_used(), 0)


class JobDetailContextTests(TestCase):
    def setUp(self):
        self.profile = make_profile("detail@example.com")
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)

    def test_the_rail_lists_every_section_in_canonical_order_with_what_was_found(self):
        context = self.client.get(self.job.get_absolute_url()).context
        self.assertEqual([entry["spec"].key for entry in context["rail"]], list(SECTION_KEYS))
        found = {entry["spec"].key for entry in context["rail"] if entry["section"] is not None}
        self.assertEqual(
            found,
            {"overview", "location_arrangement", "compensation_benefits", "responsibilities",
             "required_technical_skills", "desirable_soft_skills", "languages",
             "education_certifications", "company"},
        )

    def test_the_context_carries_the_summary_the_resume_and_both_tasks(self):
        context = self.client.get(self.job.get_absolute_url()).context
        self.assertEqual(context["match_summary"], self.job.element_match_summary())
        self.assertIsNone(context["tailored_resume"])
        self.assertIsNone(context["ai_task"])
        self.assertIsNone(context["match_task"])

        tailored = TailoredResume.objects.create(profile=self.profile, job=self.job, markdown="# CV")
        analysis = AITask.start_for(self.profile, AITask.JOB_ANALYSIS, self.job)
        matching = AITask.start_for(self.profile, AITask.JOB_MATCH, self.job)
        context = self.client.get(self.job.get_absolute_url()).context
        self.assertEqual(context["tailored_resume"], tailored)
        self.assertEqual(context["ai_task"], analysis)
        self.assertEqual(context["match_task"], matching)

    def test_deleting_says_what_was_deleted_even_for_an_untitled_job(self):
        untitled = JobPost.objects.create(profile=self.profile)
        response = self.client.post(reverse("jobs:delete", args=[untitled.pk]))
        self.assertEqual(flash(response), ["Deleted “Untitled role”."])
        named = JobPost.objects.create(profile=self.profile, title="Named")
        response = self.client.post(reverse("jobs:delete", args=[named.pk]))
        self.assertEqual(flash(response)[-1], "Deleted “Named”.")


class ReanalyzeTests(TestCase):
    """UC-05.7 (metered path): a fresh extraction costs an analysis, like the first."""

    def setUp(self):
        runtime_settings.invalidate()
        self.addCleanup(runtime_settings.invalidate)
        Plan.objects.create(
            slug="free", name="Free", price_cents=0, is_default=True, monthly_job_analyses=1
        )
        self.profile = make_profile("re@example.com")
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)
        self.url = reverse("jobs:reanalyze", args=[self.job.pk])

    def used(self):
        record = UsageRecord.objects.filter(
            user=self.profile.user, metric=UsageMetric.JOB_ANALYSIS
        ).first()
        return record.count if record else 0

    def test_it_re_extracts_from_the_stored_text_and_spends_an_analysis(self):
        replacement = {"title": "Renamed role", "sections": [
            {"key": "required_technical_skills", "body": "", "elements": ["Go"]},
        ]}
        with fake_deepseek(answering(extraction=replacement)):
            response = self.client.post(self.url)
        self.assertRedirects(response, self.job.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Re-analyzing this job post."])
        self.job.refresh_from_db()
        self.assertEqual(self.job.title, "Renamed role")
        self.assertEqual(
            list(element_of(self.job, "required_technical_skills").section.elements.values_list("text", flat=True)),
            ["Go"],
        )
        self.assertEqual(self.used(), 1)
        self.assertEqual(
            AITask.latest_for(self.job, AITask.JOB_ANALYSIS).state, AITask.DONE
        )

    def test_an_exhausted_allowance_explains_and_starts_nothing(self):
        runtime_settings.set_value("enforce_quotas", True)
        UsageRecord.objects.all().delete()
        from staffportal.services import quotas

        quotas.consume(self.profile.user, UsageMetric.JOB_ANALYSIS)
        sections_before = set(self.job.sections.values_list("pk", flat=True))
        with fake_deepseek(answering()) as calls:
            response = self.client.post(self.url)
        self.assertRedirects(response, self.job.get_absolute_url(), fetch_redirect_response=False)
        self.assertIn("You've used all 1 of this month's job analyses.", flash(response)[0])
        self.assertEqual(calls, [])
        self.assertIsNone(AITask.latest_for(self.job, AITask.JOB_ANALYSIS))
        self.assertEqual(set(self.job.sections.values_list("pk", flat=True)), sections_before)
        self.assertEqual(self.used(), 1)

    def test_only_post_and_only_your_own_jobs(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        other = make_profile("re-other@example.com")
        foreign = analyzed_job(other)
        self.assertEqual(
            self.client.post(reverse("jobs:reanalyze", args=[foreign.pk])).status_code, 404
        )


class MatchAgainstProfileTests(TestCase):
    """UC-05.7 (free path): re-compare an extracted job with the profile as it is now."""

    def setUp(self):
        runtime_settings.invalidate()
        self.addCleanup(runtime_settings.invalidate)
        Plan.objects.create(
            slug="free", name="Free", price_cents=0, is_default=True, monthly_job_analyses=5
        )
        self.profile = make_profile("match@example.com")
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)
        self.url = reverse("jobs:match_profile", args=[self.job.pk])

    def test_a_job_that_was_never_analysed_cannot_be_matched(self):
        empty = make_job(self.profile)
        response = self.client.post(reverse("jobs:match_profile", args=[empty.pk]))
        self.assertRedirects(response, empty.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(
            flash(response), ["Analyze this job post first, then match it to your profile."]
        )
        self.assertIsNone(AITask.latest_for(empty, AITask.JOB_MATCH))

    def test_the_kill_switch_holds_here_too(self):
        runtime_settings.set_value("ai_features_enabled", False)
        response = self.client.post(self.url)
        self.assertRedirects(response, self.job.get_absolute_url(), fetch_redirect_response=False)
        self.assertIn("temporarily unavailable", flash(response)[0])
        self.assertIsNone(AITask.latest_for(self.job, AITask.JOB_MATCH))

    def test_it_matches_every_section_and_costs_no_allowance(self):
        add_python(self.profile)
        with fake_deepseek(answering("partial")) as calls:
            response = self.client.post(self.url)
        self.assertRedirects(response, self.job.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(flash(response), ["Matching this job against your profile."])
        skills = element_of(self.job, "required_technical_skills")
        skills.refresh_from_db()
        self.assertEqual(skills.match_status, "partial")
        self.assertEqual(skills.match_evidence, "Covered by the profile.")
        self.assertEqual(
            sorted(match_payload(call)["section"] for call in calls),
            ["Required Technical Skills", "Responsibilities"],
        )
        task = AITask.latest_for(self.job, AITask.JOB_MATCH)
        self.assertEqual(task.state, AITask.DONE)
        self.assertFalse(UsageRecord.objects.exists(), "matching is part of the analysis already paid for")
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.profile_matched_at)

    def test_a_profile_that_grew_changes_the_verdict(self):
        with fake_deepseek(answering()) as calls:
            self.client.post(self.url)
        self.assertEqual(calls, [], "nothing recorded yet, so nothing was sent")
        python = element_of(self.job, "required_technical_skills", "Python")
        self.assertEqual(python.match_status, JobElement.NONE)

        add_python(self.profile)
        with fake_deepseek(answering("strong")):
            self.client.post(self.url)
        python.refresh_from_db()
        self.assertEqual(python.match_status, JobElement.STRONG)

    def test_only_your_own_jobs(self):
        foreign = analyzed_job(make_profile("match-other@example.com"))
        self.assertEqual(
            self.client.post(reverse("jobs:match_profile", args=[foreign.pk])).status_code, 404
        )


class SectionRematchTests(TestCase):
    """UC-05.5: the per-tab Retry button."""

    def setUp(self):
        self.profile = make_profile("section@example.com")
        add_python(self.profile)
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)
        self.section = self.job.sections.get(key="required_technical_skills")
        self.section.match_state = JobSection.FAILED
        self.section.match_error = "The AI analysis took too long and timed out."
        self.section.save()
        self.url = reverse("jobs:section_rematch", args=[self.job.pk, self.section.pk])

    def test_retrying_from_the_page_returns_to_that_tab(self):
        with fake_deepseek(answering()):
            response = self.client.post(self.url)
        self.assertRedirects(
            response,
            f"{self.job.get_absolute_url()}#required_technical_skills",
            fetch_redirect_response=False,
        )
        self.assertEqual(flash(response), ["Re-matching Required Technical Skills."])
        self.section.refresh_from_db()
        self.assertEqual((self.section.match_state, self.section.match_error), (JobSection.DONE, ""))
        self.assertEqual(
            {e.match_status for e in self.section.elements.all()}, {JobElement.STRONG}
        )

    def test_retrying_over_ajax_returns_the_refreshed_panel(self):
        with fake_deepseek(answering()):
            response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        payload = response.json()
        self.assertEqual((payload["ok"], payload["state"]), (True, "done"))
        self.assertIn("Python", payload["section_html"])
        self.assertEqual(flash(response), [], "an ajax retry says nothing in a flash message")

    def test_a_retry_is_a_single_step_task_and_costs_no_allowance(self):
        with fake_deepseek(answering()):
            self.client.post(self.url)
        task = AITask.latest_for(self.job, AITask.JOB_MATCH)
        self.assertEqual((task.steps_total, task.state), (1, AITask.DONE))
        self.assertFalse(UsageRecord.objects.exists())

    def test_a_retry_that_fails_again_records_the_reason_on_the_tab(self):
        with fake_deepseek(lambda request: 401):
            self.client.post(self.url)
        self.section.refresh_from_db()
        self.assertEqual(self.section.match_state, JobSection.FAILED)
        self.assertIn("rejected our API key", self.section.match_error)

    def test_a_section_reached_through_the_wrong_job_or_profile_is_a_404(self):
        other_job = analyzed_job(self.profile)
        wrong_job = reverse("jobs:section_rematch", args=[other_job.pk, self.section.pk])
        self.assertEqual(self.client.post(wrong_job).status_code, 404)
        foreign = analyzed_job(make_profile("section-other@example.com"))
        theirs = foreign.sections.first()
        url = reverse("jobs:section_rematch", args=[foreign.pk, theirs.pk])
        self.assertEqual(self.client.post(url).status_code, 404)


class AnalysisStateTests(TestCase):
    """UC-05.6: one call that says where every section stands."""

    SECTION_KEYS_IN_PAYLOAD = {
        "key", "id", "state", "error", "total", "strong", "partial", "none", "analyzed",
    }

    def setUp(self):
        self.profile = make_profile("state@example.com")
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)

    def state(self, job=None):
        job = job or self.job
        response = self.client.get(reverse("jobs:analysis_state", args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_payload_describes_every_section_and_the_summary(self):
        payload = self.state()
        self.assertEqual(
            set(payload), {"job_status", "sections", "summary", "is_running", "task_id"}
        )
        self.assertEqual(payload["job_status"], "completed")
        self.assertEqual(len(payload["sections"]), self.job.sections.count())
        for entry in payload["sections"]:
            self.assertEqual(set(entry), self.SECTION_KEYS_IN_PAYLOAD)
        skills = next(e for e in payload["sections"] if e["key"] == "required_technical_skills")
        self.assertEqual((skills["total"], skills["analyzed"], skills["state"]), (2, 0, "idle"))
        self.assertEqual(payload["summary"], self.job.element_match_summary())
        self.assertEqual((payload["is_running"], payload["task_id"]), (False, None))

    def test_a_live_task_means_running_and_names_the_task(self):
        task = AITask.start_for(self.profile, AITask.JOB_MATCH, self.job)
        payload = self.state()
        self.assertEqual((payload["is_running"], payload["task_id"]), (True, task.pk))
        task.mark_done()
        self.assertFalse(self.state()["is_running"])

    def test_a_job_still_pending_or_processing_is_running_without_a_task(self):
        for status in (JobPost.STATUS_PENDING, JobPost.STATUS_PROCESSING):
            with self.subTest(status=status):
                JobPost.objects.filter(pk=self.job.pk).update(status=status)
                self.assertTrue(self.state()["is_running"])

    def test_a_failed_section_reports_why(self):
        JobSection.objects.filter(pk=self.job.sections.get(key="languages").pk).update(
            match_state=JobSection.FAILED, match_error="boom"
        )
        entry = next(e for e in self.state()["sections"] if e["key"] == "languages")
        self.assertEqual((entry["state"], entry["error"]), ("failed", "boom"))

    def test_only_your_own_jobs(self):
        foreign = analyzed_job(make_profile("state-other@example.com"))
        response = self.client.get(reverse("jobs:analysis_state", args=[foreign.pk]))
        self.assertEqual(response.status_code, 404)


class AddToProfileTests(TestCase):
    """UC-06.1 to UC-06.3: close a gap from the job page, then re-check just that row."""

    def setUp(self):
        pin_language(self)  # the seeded benefit names follow the active language
        self.profile = make_profile("add@example.com")
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)
        self.technical = SkillCategory.objects.filter(kind=SkillCategory.TECHNICAL).first()
        self.soft = SkillCategory.objects.filter(kind=SkillCategory.SOFT).first()

    def url(self, element):
        return reverse("jobs:element_add", args=[self.job.pk, element.pk])

    def modal(self, key, text=None):
        element = element_of(self.job, key, text)
        response = self.client.get(self.url(element))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        return payload["modal_html"]

    def add(self, key, data, text=None):
        """POST the modal and return (element, response); the AI says "strong"."""
        element = element_of(self.job, key, text)
        with fake_deepseek(answering("strong")) as calls:
            response = self.client.post(self.url(element), data)
        element.refresh_from_db()
        return element, response, calls

    def assertAdded(self, element, response, calls):
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["element_id"], element.pk)
        self.assertIn(element.text, payload["row_html"])
        task = AITask.objects.get(pk=payload["task_id"])
        self.assertEqual((task.kind, task.state), (AITask.JOB_MATCH, AITask.DONE))
        self.assertIsNotNone(element.added_to_profile_at)
        self.assertEqual(element.match_status, JobElement.STRONG)
        self.assertFalse(element.is_evaluating)
        # Only this row was re-checked — its section-mates were left alone.
        others = JobElement.objects.filter(section=element.section).exclude(pk=element.pk)
        self.assertTrue(all(other.evaluated_at is None for other in others))
        for call in calls:
            self.assertEqual([row["id"] for row in match_payload(call)["elements"]], [element.pk])

    # --- the modal -------------------------------------------------------
    def test_the_modal_is_prefilled_from_the_row(self):
        html = self.modal("required_technical_skills", "Python")
        self.assertIn('value="Python"', html)
        self.assertIn("Add to my technical skills", html)

    def test_a_language_row_is_reduced_to_the_language_name(self):
        self.assertIn('value="French"', self.modal("languages"))

    def test_each_supported_section_offers_its_own_form(self):
        expectations = {
            "desirable_soft_skills": "Add to my soft skills",
            "languages": "Add to my languages",
            "responsibilities": "Add to my experience",
            "education_certifications": "Add to my education",
            "compensation_benefits": "Add to my job preferences",
            "location_arrangement": "Add to my job preferences",
        }
        for key, title in expectations.items():
            with self.subTest(section=key):
                self.assertIn(title, self.modal(key))

    def test_highlights_need_a_role_to_attach_to(self):
        html = self.modal("responsibilities")
        self.assertIn("Add a work experience to your profile first, then come back.", html)

    def test_a_section_with_nowhere_to_go_is_refused_on_get_and_post(self):
        company = self.job.sections.get(key="company")
        element = JobElement.objects.create(section=company, text="Series B")
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(self.url(element))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    {"ok": False, "error": "This section can't be added to your profile."},
                )

    # --- creating the right thing ----------------------------------------
    def test_a_technical_skill(self):
        element, response, calls = self.add(
            "required_technical_skills",
            {"name": "Python", "category": self.technical.pk, "level": UserSkill.ADVANCED},
            "Python",
        )
        skill = UserSkill.objects.get(profile=self.profile, name="Python")
        self.assertEqual((skill.category, skill.level), (self.technical, UserSkill.ADVANCED))
        self.assertAdded(element, response, calls)
        self.assertEqual(len(calls), 1)

    def test_a_soft_skill(self):
        element, response, calls = self.add(
            "desirable_soft_skills",
            {"name": "Mentoring", "category": self.soft.pk, "level": UserSkill.EXPERT},
        )
        skill = UserSkill.objects.get(profile=self.profile, name="Mentoring")
        self.assertEqual(skill.category.kind, SkillCategory.SOFT)
        self.assertAdded(element, response, calls)

    def test_a_language(self):
        element, response, calls = self.add(
            "languages", {"name": "French", "proficiency": UserLanguage.FLUENT}
        )
        entry = UserLanguage.objects.get(profile=self.profile)
        self.assertEqual((entry.language.name, entry.proficiency), ("French", "fluent"))
        self.assertAdded(element, response, calls)

    def test_a_highlight_on_a_role_the_user_picks(self):
        role = WorkExperience.objects.create(
            profile=self.profile, job_title="Dev", company="Acme", start_date=date(2020, 1, 1)
        )
        ExperienceHighlight.objects.create(experience=role, text="First", order=0)
        element, response, calls = self.add(
            "responsibilities", {"experience": role.pk, "text": "Designed and ran APIs."}
        )
        highlight = role.highlights.get(text="Designed and ran APIs.")
        self.assertEqual(highlight.order, 1)
        self.assertAdded(element, response, calls)

    def test_a_degree_or_a_certificate(self):
        element, response, calls = self.add(
            "education_certifications",
            {"record_type": "degree", "title": "BSc in Computer Science",
             "organization": "McGill", "field_of_study": "CS"},
        )
        degree = Degree.objects.get(profile=self.profile)
        self.assertEqual((degree.degree, degree.school, degree.field_of_study),
                         ("BSc in Computer Science", "McGill", "CS"))
        self.assertAdded(element, response, calls)

        JobElement.objects.filter(pk=element.pk).update(added_to_profile_at=None)
        element, response, calls = self.add(
            "education_certifications",
            {"record_type": "certificate", "title": "AWS SAA", "organization": "Amazon"},
        )
        certificate = Certificate.objects.get(profile=self.profile)
        self.assertEqual((certificate.name, certificate.issuing_organization), ("AWS SAA", "Amazon"))

    def test_a_degree_without_a_school_is_recorded_with_a_dash(self):
        self.add("education_certifications", {"record_type": "degree", "title": "BSc"})
        self.assertEqual(Degree.objects.get(profile=self.profile).school, "—")

    def test_a_benefit(self):
        section = self.job.sections.get(key="compensation_benefits")
        JobElement.objects.create(section=section, text="Company car", order=5)
        element, response, calls = self.add(
            "compensation_benefits",
            {"name": "Company car", "importance": "must_have", "notes": "electric"},
            "Company car",
        )
        benefit = BenefitPreference.objects.get(preference__profile=self.profile, name="Company car")
        self.assertEqual((benefit.importance, benefit.notes), ("must_have", "electric"))
        self.assertAdded(element, response, calls)

    def test_location_facts_update_the_scalar_preferences(self):
        cases = [
            ({"apply_to": "location", "value": "Remote (Canada)"},
             lambda p: p.preferred_locations_list == ["Remote (Canada)"]),
            ({"apply_to": "arrangement", "value": "Hybrid", "arrangement": "hybrid"},
             lambda p: p.hybrid_ok and not p.remote_ok),
            ({"apply_to": "timezone", "value": "EST ±2h"},
             lambda p: p.timezone_preference == "EST ±2h"),
            ({"apply_to": "travel", "value": "Up to 20% travel", "travel_percentage": "20"},
             lambda p: p.max_travel_percentage == 20),
        ]
        element = element_of(self.job, "location_arrangement")
        for data, holds in cases:
            with self.subTest(apply_to=data["apply_to"]):
                JobElement.objects.filter(pk=element.pk).update(added_to_profile_at=None)
                with fake_deepseek(answering("strong")):
                    response = self.client.post(self.url(element), data)
                self.assertEqual(response.status_code, 200, response.content)
                preference = get_or_create_preference(self.profile)
                preference.refresh_from_db()
                self.assertTrue(holds(preference), data)

    def test_adding_the_same_location_twice_does_not_duplicate_it(self):
        element = element_of(self.job, "location_arrangement")
        for _ in range(2):
            with fake_deepseek(answering("strong")):
                self.client.post(self.url(element), {"apply_to": "location", "value": "Paris"})
        self.assertEqual(get_or_create_preference(self.profile).preferred_locations_list, ["Paris"])

    # --- refusing politely -----------------------------------------------
    def test_a_duplicate_skill_comes_back_in_the_modal_not_as_a_500(self):
        UserSkill.objects.create(profile=self.profile, category=self.technical, name="Python")
        element = element_of(self.job, "required_technical_skills", "Python")
        with fake_deepseek(answering()) as calls:
            response = self.client.post(
                self.url(element),
                {"name": "python", "category": self.technical.pk, "level": UserSkill.ADVANCED},
            )
        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("is already in that category on your profile.", payload["modal_html"])
        self.assertEqual(UserSkill.objects.filter(profile=self.profile).count(), 1)
        self.assertEqual(calls, [])
        element.refresh_from_db()
        self.assertIsNone(element.added_to_profile_at)
        self.assertIsNone(AITask.latest_for(self.job, AITask.JOB_MATCH))

    def test_a_language_already_on_the_profile_is_refused(self):
        UserLanguage.objects.create(
            profile=self.profile, language=Language.objects.create(name="French"),
            proficiency=UserLanguage.NATIVE,
        )
        _element, response, _calls = self.add(
            "languages", {"name": "french", "proficiency": UserLanguage.FLUENT}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("is already on your profile.", response.json()["modal_html"])
        self.assertEqual(UserLanguage.objects.filter(profile=self.profile).count(), 1)

    def test_a_benefit_already_listed_is_refused(self):
        get_or_create_preference(self.profile)
        _element, response, _calls = self.add(
            "compensation_benefits", {"name": "dental care", "importance": "must_have"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("is already in your preferences.", response.json()["modal_html"])

    def test_a_highlight_needs_a_role_and_a_certificate_needs_an_issuer(self):
        _element, response, _calls = self.add("responsibilities", {"text": "Did things."})
        self.assertEqual(response.status_code, 422)
        _element, response, _calls = self.add(
            "education_certifications", {"record_type": "certificate", "title": "AWS SAA"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Certificates need an issuing organization.", response.json()["modal_html"])
        self.assertFalse(Certificate.objects.exists())

    def test_another_profiles_row_is_a_404_on_get_and_post(self):
        foreign = analyzed_job(make_profile("add-other@example.com"))
        element = element_of(foreign, "required_technical_skills", "Python")
        url = reverse("jobs:element_add", args=[foreign.pk, element.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"name": "Python"}).status_code, 404)


class ElementReevaluationTests(TestCase):
    """UC-06.3: re-check one row on demand, and fetch it once the check is done."""

    def setUp(self):
        self.profile = make_profile("row@example.com")
        add_python(self.profile)
        self.client.force_login(self.profile.user)
        self.job = analyzed_job(self.profile)
        self.python = element_of(self.job, "required_technical_skills", "Python")
        self.postgres = element_of(self.job, "required_technical_skills", "PostgreSQL")

    def urls(self, element, name):
        return reverse(f"jobs:{name}", args=[self.job.pk, element.pk])

    def test_rematching_one_row_touches_no_other_row(self):
        with fake_deepseek(answering("partial", "Some Python.")) as calls:
            response = self.client.post(self.urls(self.python, "element_rematch"))
        payload = response.json()
        self.assertEqual((payload["ok"], payload["element_id"]), (True, self.python.pk))
        self.assertIn("Python", payload["row_html"])
        self.python.refresh_from_db()
        self.postgres.refresh_from_db()
        self.assertEqual((self.python.match_status, self.python.match_evidence), ("partial", "Some Python."))
        self.assertFalse(self.python.is_evaluating)
        self.assertEqual(self.postgres.match_status, "")
        self.assertEqual(len(calls), 1)
        self.assertEqual([r["id"] for r in match_payload(calls[0])["elements"]], [self.python.pk])
        task = AITask.objects.get(pk=payload["task_id"])
        self.assertEqual((task.kind, task.steps_total, task.state), (AITask.JOB_MATCH, 1, AITask.DONE))

    def test_a_failed_recheck_leaves_the_row_ready_to_try_again(self):
        with fake_deepseek(lambda request: 401):
            response = self.client.post(self.urls(self.python, "element_rematch"))
        self.assertEqual(response.status_code, 200)
        self.python.refresh_from_db()
        self.assertFalse(self.python.is_evaluating)
        task = AITask.objects.get(pk=response.json()["task_id"])
        self.assertEqual(task.state, AITask.FAILED)
        self.assertIn("rejected our API key", task.error_message)

    def test_a_row_with_nothing_to_compare_is_answered_without_the_model(self):
        empty = analyzed_job(make_profile("row-empty@example.com"))
        client = self.client_class()
        client.force_login(empty.sections.first().job.profile.user)
        element = element_of(empty, "languages")
        with fake_deepseek(answering()) as calls:
            response = client.post(reverse("jobs:element_rematch", args=[empty.pk, element.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [])
        element.refresh_from_db()
        self.assertEqual(element.match_status, JobElement.NONE)
        self.assertIn("No languages recorded", element.match_evidence)

    def test_the_finished_row_comes_with_fresh_summaries(self):
        with fake_deepseek(answering("strong")):
            self.client.post(self.urls(self.python, "element_rematch"))
        response = self.client.get(self.urls(self.python, "element_row"))
        payload = response.json()
        self.assertEqual(set(payload), {"ok", "element_id", "row_html", "section_summary", "summary"})
        self.assertIn("Python", payload["row_html"])
        section = self.python.section
        self.assertEqual(payload["section_summary"], section.match_summary())
        self.assertEqual(payload["section_summary"]["strong"], 1)
        self.assertEqual(payload["summary"], self.job.element_match_summary())

    def test_only_your_own_rows_and_the_right_job(self):
        foreign = analyzed_job(make_profile("row-other@example.com"))
        theirs = element_of(foreign, "required_technical_skills", "Python")
        for name, method in (
            ("element_rematch", self.client.post),
            ("element_row", self.client.get),
        ):
            with self.subTest(name=name):
                url = reverse(f"jobs:{name}", args=[foreign.pk, theirs.pk])
                self.assertEqual(method(url).status_code, 404)
                mixed = reverse(f"jobs:{name}", args=[self.job.pk, theirs.pk])
                self.assertEqual(method(mixed).status_code, 404)
