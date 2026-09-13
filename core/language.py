"""The one place that turns a profile's language into instructions for the AI.

Every AI call in the app — job extraction, requirement matching, resume
parsing, resume writing — goes through `language_clause`, so a profile created
in French can never come back with an English summary because one prompt forgot
to ask.
"""

from contextlib import contextmanager

from django.conf import settings
from django.utils import translation

#: English names for the languages we offer, because the instruction itself is
#: written in English (the model follows an English instruction more reliably
#: than one written in the target language).
LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
}


def normalize(language: str | None) -> str:
    """Coerce anything (None, "fr-ca", "") into a language we actually support."""
    available = {code for code, _label in settings.LANGUAGES}
    code = (language or "").strip().lower()
    if code in available:
        return code
    if code[:2] in available:
        return code[:2]
    return settings.LANGUAGE_CODE


def language_name(language: str | None) -> str:
    return LANGUAGE_NAMES.get(normalize(language), LANGUAGE_NAMES[settings.LANGUAGE_CODE])


def language_clause(language: str | None) -> str:
    """The sentence prepended to every prompt's user message."""
    name = language_name(language)
    return (
        f"Write EVERYTHING you produce in {name}: summaries, section bodies, "
        f"explanations, bullet points, headings and labels. This is not "
        f"negotiable — even when the source text is in another language, your "
        f"output must be in {name}. Keep proper nouns (people, company, product "
        f"and technology names) in their original form, and keep any value that "
        f"is an enum defined in these instructions exactly as spelled here."
    )


@contextmanager
def use_language(language: str | None):
    """Render translatable strings in a profile's language.

    Used around document assembly (the Markdown recap, the tailored resume) so
    the parts *we* write — headings, "Present", month names — come out in the
    same language as the parts the AI writes.
    """
    with translation.override(normalize(language)):
        yield
