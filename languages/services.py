"""Use cases of a profile's spoken languages.

Language names live in one shared table and are matched case-insensitively, so
"french" and "French" are the same language for everyone. A profile then holds
one `UserLanguage` per language, with a proficiency.

Use cases: docs/use-cases/UC03_PROFILE_DATA_MANAGEMENT.md (UC-03.3).
"""

from .models import UserLanguage


# UC-03.3 — Multilingual Language Proficiencies Management: the workspace boundary
def profile_languages(profile):
    return UserLanguage.objects.filter(profile=profile)


# UC-03.3 — step 2: the recorded languages, alphabetical
def list_languages(profile):
    return profile_languages(profile).select_related("language")


# UC-03.3 — steps 4-6: the form looks the name up case-insensitively (creating
# the shared `Language` when it is new), refuses a language the profile already
# has, and stores the entry against the profile.
def add_language(form) -> UserLanguage:
    return form.save()


# UC-03.3 — editing an entry (proficiency, or a different language)
def update_language(form) -> UserLanguage:
    return form.save()


# UC-03.3 — removing an entry (the shared `Language` stays for others)
def remove_language(user_language: UserLanguage) -> None:
    user_language.delete()
