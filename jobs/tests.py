"""Tests for the fixed-section refactor.

The AI is always stubbed: these assert our contract with it (the closed enum,
the scoped slices, the empty-slice short circuit), never the model's output.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import translation
from django.urls import reverse

from accounts.models import Profile
from core.models import AITask
from core.utils import build_profile_slice, profile_slice_is_empty
from jobs.models import JobElement, JobPost, JobSection
from jobs.sections import MATCHED_SECTION_KEYS, SECTION_KEYS
from jobs.services.importer import apply_analysis, normalize_sections
from preferences.models import get_or_create_preference
from skills.models import SkillCategory, UserSkill

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
        self.job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")

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
        self.job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
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


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ViewsNeverCallAITests(TestCase):
    def setUp(self):
        self.profile = make_profile("d@example.com")
        self.client.force_login(self.profile.user)

    def test_submitting_a_job_enqueues_and_redirects(self):
        with patch("jobs.tasks.fetch_job_text.apply_async") as _fetch, \
             patch("celery.canvas._chain.apply_async") as chain_apply:
            chain_apply.return_value = type("R", (), {"id": "fake-id"})()
            response = self.client.post(
                reverse("jobs:add"),
                {"source_url": "https://x.test/job", "manual_text": "Some job text"},
            )
        self.assertEqual(response.status_code, 302)
        job = JobPost.objects.get()
        task = AITask.latest_for(job, AITask.JOB_ANALYSIS)
        self.assertIsNotNone(task, "submitting a job must create an AITask")
        self.assertEqual(task.state, AITask.QUEUED)

    def test_task_status_endpoint_is_owner_scoped(self):
        job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
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
        self.job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")

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

        job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
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
                {"source_url": "https://x.test/job", "manual_text": "Some job text"},
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
        self.job = JobPost.objects.create(profile=self.profile, source_url="https://x.test/j")
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
        english_job = JobPost.objects.create(profile=english, source_url="https://x.test/j2")
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
