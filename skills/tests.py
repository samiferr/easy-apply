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

    def test_neither_page_carries_a_soft_technical_switcher(self):
        """The sidebar links to both kinds; a second switcher was duplication.

        The category tabs *within* a page are a different thing — they split
        one kind's skills, and never offer the other kind.
        """
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

    def test_each_category_gets_its_own_tab_and_panel(self):
        """One tab per category the profile has skills in, wired to a panel."""
        databases = SkillCategory.objects.get_or_create(
            name="Databases", kind=SkillCategory.TECHNICAL
        )[0]
        UserSkill.objects.create(profile=self.profile, category=databases, name="Postgres")

        body = self.client.get(reverse("skills:list", args=["technical"])).content.decode()
        for category in (self.technical, databases):
            with self.subTest(category=category.name):
                self.assertIn(f'id="tab-category-{category.pk}"', body)
                self.assertIn(f'aria-controls="panel-category-{category.pk}"', body)
                self.assertIn(f'id="panel-category-{category.pk}"', body)
                self.assertIn(category.name, body)
        self.assertIn('role="tablist"', body)

    def test_a_category_with_no_skills_gets_no_tab(self):
        """The tabs show what you have, the same set the card grid showed."""
        empty = SkillCategory.objects.get_or_create(
            name="Cloud & DevOps", kind=SkillCategory.TECHNICAL
        )[0]
        body = self.client.get(reverse("skills:list", args=["technical"])).content.decode()
        self.assertNotIn(f'id="tab-category-{empty.pk}"', body)

    def test_a_kind_with_no_skills_shows_the_empty_state_not_an_empty_strip(self):
        UserSkill.objects.filter(profile=self.profile, category__kind="soft").delete()
        body = self.client.get(reverse("skills:list", args=["soft"])).content.decode()
        self.assertNotIn('role="tablist"', body)
        self.assertIn("No soft skills yet", body)

    def test_an_unknown_kind_is_a_404(self):
        self.assertEqual(self.client.get("/skills/nonsense/").status_code, 404)

    def test_bare_skills_url_lands_on_a_real_page(self):
        response = self.client.get("/skills/")
        self.assertRedirects(response, reverse("skills:list", args=["technical"]))

    def test_adding_returns_to_that_skills_category_tab(self):
        response = self.client.post(
            reverse("skills:add", args=["soft"]),
            {"category": self.soft.pk, "name": "Listening", "level": UserSkill.ADVANCED},
        )
        self.assertRedirects(
            response,
            f"{reverse('skills:list', args=['soft'])}#category-{self.soft.pk}",
        )

    def test_deleting_returns_to_that_skills_category_tab(self):
        skill = UserSkill.objects.get(name="Python")
        response = self.client.post(reverse("skills:delete", args=[skill.pk]))
        self.assertRedirects(
            response,
            f"{reverse('skills:list', args=['technical'])}#category-{self.technical.pk}",
        )
