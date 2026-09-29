"""Work experience and its highlight bullets (UC-03.4)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile

from .models import ExperienceHighlight, WorkExperience

User = get_user_model()


def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def formset(*texts, initial=()):
    """POST data for the highlights formset: existing rows first, then new ones."""
    data = {
        "highlights-TOTAL_FORMS": str(len(initial) + len(texts)),
        "highlights-INITIAL_FORMS": str(len(initial)),
        "highlights-MIN_NUM_FORMS": "0",
        "highlights-MAX_NUM_FORMS": "20",
    }
    index = 0
    for highlight, text in initial:
        data[f"highlights-{index}-id"] = str(highlight.pk)
        data[f"highlights-{index}-experience"] = str(highlight.experience_id)
        data[f"highlights-{index}-text"] = text
        index += 1
    for text in texts:
        data[f"highlights-{index}-text"] = text
        index += 1
    return data


def experience_data(**overrides):
    data = {
        "job_title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "employment_type": "full_time", "start_date": "2020-01-01", "end_date": "2022-06-30",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


class ExperienceManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="e@example.com", password="pw12345678")
        self.profile = Profile.objects.get(user=self.user)
        self.client.force_login(self.user)

    def create(self, *highlights, **overrides):
        return self.client.post(
            reverse("experience:add"), {**experience_data(**overrides), **formset(*highlights)}
        )

    def test_creating_a_role_saves_it_with_its_highlights_in_the_active_profile(self):
        response = self.create("Built the payments API.", "Mentored two juniors.")
        self.assertRedirects(response, reverse("experience:list"), fetch_redirect_response=False)
        role = WorkExperience.objects.get()
        self.assertEqual((role.profile, role.job_title, role.company), (self.profile, "Backend Engineer", "Acme"))
        self.assertEqual(
            [h.text for h in role.highlights.all()],
            ["Built the payments API.", "Mentored two juniors."],
        )
        self.assertEqual(flash(response), ["Added your role at Acme."])

    def test_blank_highlight_rows_are_ignored(self):
        self.create("Kept.", "", "   ")
        self.assertEqual(ExperienceHighlight.objects.count(), 1)

    def test_a_current_role_has_no_end_date(self):
        self.create(is_current="on", end_date="2022-06-30")
        role = WorkExperience.objects.get()
        self.assertTrue(role.is_current)
        self.assertIsNone(role.end_date)

    def test_an_end_date_before_the_start_redisplays_the_form_unsaved(self):
        response = self.create(start_date="2022-01-01", end_date="2021-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkExperience.objects.exists())
        self.assertIn("end_date", response.context["form"].errors)

    def test_invalid_highlights_stop_the_role_from_being_saved(self):
        response = self.create("x" * 501)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkExperience.objects.exists())

    def test_editing_updates_the_role_and_its_highlights(self):
        role = WorkExperience.objects.create(
            profile=self.profile, job_title="Dev", company="Acme", start_date=date(2020, 1, 1)
        )
        keep = ExperienceHighlight.objects.create(experience=role, text="Old one")
        drop = ExperienceHighlight.objects.create(experience=role, text="Drop me")
        data = {**experience_data(job_title="Senior Dev"), **formset("Brand new", initial=[(keep, "Reworded"), (drop, "Drop me")])}
        data[f"highlights-1-DELETE"] = "on"
        response = self.client.post(reverse("experience:edit", args=[role.pk]), data)
        self.assertRedirects(response, reverse("experience:list"), fetch_redirect_response=False)
        role.refresh_from_db()
        self.assertEqual(role.job_title, "Senior Dev")
        self.assertEqual(sorted(h.text for h in role.highlights.all()), ["Brand new", "Reworded"])
        self.assertEqual(flash(response), ["Work experience updated."])

    def test_the_edit_form_shows_the_existing_highlights(self):
        role = WorkExperience.objects.create(
            profile=self.profile, job_title="Dev", company="Acme", start_date=date(2020, 1, 1)
        )
        ExperienceHighlight.objects.create(experience=role, text="Shown")
        response = self.client.get(reverse("experience:edit", args=[role.pk]))
        self.assertContains(response, "Shown")

    def test_deleting_says_what_was_removed(self):
        role = WorkExperience.objects.create(
            profile=self.profile, job_title="Dev", company="Acme", start_date=date(2020, 1, 1)
        )
        ExperienceHighlight.objects.create(experience=role, text="Bullet")
        response = self.client.post(reverse("experience:delete", args=[role.pk]))
        self.assertFalse(WorkExperience.objects.exists())
        self.assertFalse(ExperienceHighlight.objects.exists())
        self.assertEqual(flash(response), ["Removed Dev at Acme."])

    def test_the_list_is_current_first_then_newest_and_private(self):
        other = User.objects.create_user(email="e2@example.com", password="pw12345678")
        WorkExperience.objects.create(
            profile=Profile.objects.get(user=other), job_title="Theirs", company="X",
            start_date=date(2019, 1, 1),
        )
        for title, start, current in (("Old", date(2015, 1, 1), False), ("New", date(2021, 1, 1), False), ("Now", date(2018, 1, 1), True)):
            WorkExperience.objects.create(
                profile=self.profile, job_title=title, company="Co", start_date=start,
                is_current=current,
            )
        roles = self.client.get(reverse("experience:list")).context["experiences"]
        self.assertEqual([r.job_title for r in roles], ["Now", "New", "Old"])

    def test_another_profiles_role_is_a_404(self):
        other = User.objects.create_user(email="e3@example.com", password="pw12345678")
        theirs = WorkExperience.objects.create(
            profile=Profile.objects.get(user=other), job_title="Theirs", company="X",
            start_date=date(2019, 1, 1),
        )
        self.assertEqual(self.client.get(reverse("experience:edit", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("experience:delete", args=[theirs.pk])).status_code, 404)
