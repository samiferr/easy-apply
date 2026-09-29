"""Use cases of a profile's degrees and certificates.

Use cases: docs/use-cases/UC03_PROFILE_DATA_MANAGEMENT.md (UC-03.5).
"""

from .models import Certificate, Degree


# UC-03.5 — Education Degrees & Professional Certifications: the workspace boundary
def profile_degrees(profile):
    return Degree.objects.filter(profile=profile)


def profile_certificates(profile):
    return Certificate.objects.filter(profile=profile)


# UC-03.5 — step 1 of both scenarios: the education overview
def education_overview(profile) -> dict:
    return {
        "degrees": profile_degrees(profile),
        "certificates": profile_certificates(profile),
    }


# UC-03.5 — Main Success Scenario (Degree), step 3
def add_degree(profile, form) -> Degree:
    form.instance.profile = profile
    return form.save()


def update_degree(form) -> Degree:
    return form.save()


def remove_degree(degree: Degree) -> None:
    degree.delete()


# UC-03.5 — Main Success Scenario (Certification), step 2
def add_certificate(profile, form) -> Certificate:
    form.instance.profile = profile
    return form.save()


def update_certificate(form) -> Certificate:
    return form.save()


def remove_certificate(certificate: Certificate) -> None:
    certificate.delete()
