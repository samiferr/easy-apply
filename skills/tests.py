"""Soft and technical skills are two screens, one per sidebar entry."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile

from .models import SkillCategory, UserSkill

User = get_user_model()


class SkillKindPagesTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="s@example.com", password="pw12345678")
        self.profile = Profile.objects.get(user=user)
        # The starter categories are seeded by a data migration.
        self.technical, _ = SkillCategory.objects.get_or_create(
            name="Programming Languages", kind=SkillCategory.TECHNICAL
        )
        self.soft, _ = SkillCategory.objects.get_or_create(
            name="Communication", kind=SkillCategory.SOFT
        )
        UserSkill.objects.create(profile=self.profile, category=self.technical, name="Python")
        UserSkill.objects.create(profile=self.profile, category=self.soft, name="Mentoring")
        self.client.force_login(user)

    def test_each_page_shows_only_its_own_kind(self):
        technical = self.client.get(reverse("skills:list", args=["technical"])).content.decode()
        self.assertIn("Python", technical)
        self.assertNotIn("Mentoring", technical)

        soft = self.client.get(reverse("skills:list", args=["soft"])).content.decode()
        self.assertIn("Mentoring", soft)
        self.assertNotIn("Python", soft)

    def test_neither_page_carries_a_tab_switcher(self):
        """The sidebar links to both kinds; a second switcher was duplication."""
        for kind in ("soft", "technical"):
            with self.subTest(kind=kind):
                body = self.client.get(reverse("skills:list", args=[kind])).content.decode()
                self.assertNotIn("tab = '", body)

    def test_the_sidebar_highlights_the_page_you_are_on(self):
        for kind, expected in (("technical", "Technical skills"), ("soft", "Soft skills")):
            with self.subTest(kind=kind):
                body = self.client.get(reverse("skills:list", args=[kind])).content.decode()
                active = body.split("nav-side-active")[1:]
                self.assertEqual(len(active), 1, "exactly one sidebar row should be active")
                self.assertIn(expected, active[0].split("</a>")[0])

    def test_an_unknown_kind_is_a_404(self):
        self.assertEqual(self.client.get("/skills/nonsense/").status_code, 404)

    def test_bare_skills_url_lands_on_a_real_page(self):
        response = self.client.get("/skills/")
        self.assertRedirects(response, reverse("skills:list", args=["technical"]))

    def test_adding_returns_to_that_kinds_page(self):
        response = self.client.post(
            reverse("skills:add", args=["soft"]),
            {"category": self.soft.pk, "name": "Listening", "level": UserSkill.ADVANCED},
        )
        self.assertRedirects(response, reverse("skills:list", args=["soft"]))

    def test_deleting_returns_to_that_kinds_page(self):
        skill = UserSkill.objects.get(name="Python")
        response = self.client.post(reverse("skills:delete", args=[skill.pk]))
        self.assertRedirects(response, reverse("skills:list", args=["technical"]))
