"""Degrees and certificates (UC-03.5)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile

from .models import Certificate, Degree

User = get_user_model()


def flash(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


class EducationManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ed@example.com", password="pw12345678")
        self.profile = Profile.objects.get(user=self.user)
        self.client.force_login(self.user)

    def test_adding_a_degree(self):
        response = self.client.post(
            reverse("education:degree_add"),
            {"school": "McGill", "degree": "BSc", "field_of_study": "CS",
             "start_date": "2014-09-01", "end_date": "2018-05-01"},
        )
        self.assertRedirects(response, reverse("education:list"), fetch_redirect_response=False)
        degree = Degree.objects.get()
        self.assertEqual((degree.profile, degree.school, degree.degree), (self.profile, "McGill", "BSc"))
        self.assertEqual(flash(response), ["Added your degree from McGill."])

    def test_a_current_degree_has_no_end_date(self):
        self.client.post(
            reverse("education:degree_add"),
            {"school": "MIT", "degree": "MSc", "start_date": "2022-09-01",
             "end_date": "2024-01-01", "is_current": "on"},
        )
        degree = Degree.objects.get()
        self.assertTrue(degree.is_current)
        self.assertIsNone(degree.end_date)

    def test_a_degree_ending_before_it_starts_is_refused(self):
        response = self.client.post(
            reverse("education:degree_add"),
            {"school": "MIT", "degree": "MSc", "start_date": "2022-09-01", "end_date": "2020-01-01"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Degree.objects.exists())

    def test_editing_and_deleting_a_degree(self):
        degree = Degree.objects.create(profile=self.profile, school="McGill", degree="BSc")
        response = self.client.post(
            reverse("education:degree_edit", args=[degree.pk]),
            {"school": "McGill", "degree": "MSc"},
        )
        degree.refresh_from_db()
        self.assertEqual(degree.degree, "MSc")
        self.assertEqual(flash(response), ["Degree updated."])
        response = self.client.post(reverse("education:degree_delete", args=[degree.pk]))
        self.assertFalse(Degree.objects.exists())
        self.assertEqual(flash(response)[-1:], ["Removed MSc — McGill."])

    def test_adding_a_certificate(self):
        response = self.client.post(
            reverse("education:certificate_add"),
            {"name": "AWS SAA", "issuing_organization": "Amazon", "issue_date": "2023-01-15",
             "credential_id": "ABC", "credential_url": "https://aws.example/abc"},
        )
        certificate = Certificate.objects.get()
        self.assertEqual((certificate.profile, certificate.name), (self.profile, "AWS SAA"))
        self.assertEqual(flash(response), ["Added the “AWS SAA” certificate."])

    def test_a_certificate_that_does_not_expire_has_no_expiry_date(self):
        self.client.post(
            reverse("education:certificate_add"),
            {"name": "CKA", "issuing_organization": "CNCF", "expiry_date": "2030-01-01",
             "does_not_expire": "on"},
        )
        certificate = Certificate.objects.get()
        self.assertTrue(certificate.does_not_expire)
        self.assertIsNone(certificate.expiry_date)
        self.assertFalse(certificate.is_expired)

    def test_a_certificate_knows_when_it_has_expired(self):
        past = Certificate.objects.create(
            profile=self.profile, name="Old", issuing_organization="X",
            expiry_date=timezone.localdate() - timedelta(days=1),
        )
        future = Certificate.objects.create(
            profile=self.profile, name="New", issuing_organization="X",
            expiry_date=timezone.localdate() + timedelta(days=30),
        )
        self.assertTrue(past.is_expired)
        self.assertFalse(future.is_expired)

    def test_editing_and_deleting_a_certificate(self):
        certificate = Certificate.objects.create(
            profile=self.profile, name="AWS SAA", issuing_organization="Amazon"
        )
        response = self.client.post(
            reverse("education:certificate_edit", args=[certificate.pk]),
            {"name": "AWS SAP", "issuing_organization": "Amazon"},
        )
        certificate.refresh_from_db()
        self.assertEqual(certificate.name, "AWS SAP")
        self.assertEqual(flash(response), ["Certificate updated."])
        response = self.client.post(reverse("education:certificate_delete", args=[certificate.pk]))
        self.assertFalse(Certificate.objects.exists())
        self.assertEqual(flash(response)[-1:], ["Removed the “AWS SAP” certificate."])

    def test_the_overview_lists_only_this_profiles_records(self):
        other = User.objects.create_user(email="ed2@example.com", password="pw12345678")
        other_profile = Profile.objects.get(user=other)
        Degree.objects.create(profile=other_profile, school="Theirs", degree="PhD")
        Certificate.objects.create(profile=other_profile, name="Theirs", issuing_organization="X")
        Degree.objects.create(profile=self.profile, school="Mine", degree="BSc")
        Certificate.objects.create(profile=self.profile, name="Mine", issuing_organization="X")
        context = self.client.get(reverse("education:list")).context
        self.assertEqual([d.school for d in context["degrees"]], ["Mine"])
        self.assertEqual([c.name for c in context["certificates"]], ["Mine"])

    def test_another_profiles_records_are_404s(self):
        other = User.objects.create_user(email="ed3@example.com", password="pw12345678")
        theirs = Degree.objects.create(
            profile=Profile.objects.get(user=other), school="Theirs", degree="PhD"
        )
        self.assertEqual(self.client.get(reverse("education:degree_edit", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("education:degree_delete", args=[theirs.pk])).status_code, 404)
