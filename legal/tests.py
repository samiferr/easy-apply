"""The public legal pages (UC-09.1) and the operator details they interpolate (UC-09.2)."""

from django.test import TestCase, override_settings
from django.urls import reverse

from .services import legal_entity, legal_page_context

ENTITY = {
    "name": "Acme Careers SAS",
    "address": "12 rue de la Paix, 75002 Paris",
    "email": "hello@acme.example",
    "jurisdiction": "Tribunal de Commerce de Paris",
    "registration": "RCS Paris 123 456 789",
    "director": "Jane Doe",
    "host_name": "Scaleway SAS",
    "host_address": "8 rue de la Ville l'Evêque, Paris",
    "dpo_email": "dpo@acme.example",
}

PAGES = {
    "legal:privacy": "Privacy Policy",
    "legal:terms": "Terms of Service",
    "legal:cookies": "Cookie Policy",
    "legal:notice": "Legal notice",
    "legal:contact": "Contact",
}


class LegalPagesTests(TestCase):
    def test_every_page_is_public_and_titled(self):
        for name, title in PAGES.items():
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(str(response.context["page_title"]), title)

    def test_the_pages_render_in_french_too(self):
        self.client.cookies["django_language"] = "fr"
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_the_title_helper_only_carries_the_title(self):
        self.assertEqual(legal_page_context("Anything"), {"page_title": "Anything"})


@override_settings(LEGAL_ENTITY=ENTITY)
class OperatorDetailsTests(TestCase):
    """UC-09.2: the policies say who the operator is without hard-coded text."""

    def body(self, name):
        return self.client.get(reverse(name)).content.decode()

    def test_the_operator_is_read_from_settings(self):
        self.assertEqual(legal_entity(), ENTITY)

    def test_the_legal_notice_lists_the_publisher_and_the_host(self):
        body = self.body("legal:notice")
        for key in ("name", "address", "registration", "director", "email", "host_name"):
            with self.subTest(key=key):
                self.assertIn(ENTITY[key], body)
        self.assertIn("Scaleway SAS", body)

    def test_the_contact_page_lists_support_and_privacy_addresses(self):
        body = self.body("legal:contact")
        for key in ("email", "dpo_email", "name", "address"):
            with self.subTest(key=key):
                self.assertIn(ENTITY[key], body)

    def test_the_privacy_policy_names_the_operator_the_dpo_and_the_courts(self):
        body = self.body("legal:privacy")
        for key in ("name", "address", "dpo_email", "jurisdiction"):
            with self.subTest(key=key):
                self.assertIn(ENTITY[key], body)

    def test_the_terms_name_the_operator_and_the_governing_courts(self):
        body = self.body("legal:terms")
        for key in ("name", "jurisdiction", "email"):
            with self.subTest(key=key):
                self.assertIn(ENTITY[key], body)

    def test_every_template_sees_the_operator_not_just_the_legal_pages(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["LEGAL_ENTITY"], ENTITY)

    def test_unconfigured_deployments_show_loud_placeholders(self):
        with override_settings(LEGAL_ENTITY={**ENTITY, "name": "TODO: Registered company name"}):
            self.assertIn("TODO: Registered company name", self.body("legal:notice"))
