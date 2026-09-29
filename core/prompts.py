"""Loads the prompts the app sends to the AI.

Every prompt is a plain-text file under `settings.PROMPTS_DIR` (the top-level
`prompts/` directory), one prompt per file, so it can be read, reviewed and
edited without touching Python. The file *is* the prompt: what is in it is what
the model receives, byte for byte. The one thing done on the way out is
placeholder substitution — `{{ name }}` is replaced by the value passed to
`load_prompt` — and nothing else is interpreted, so JSON examples, braces, `$`,
backslashes and quotes are written exactly as the model should see them.

`prompts/README.md` lists every prompt and explains the conventions.
"""

import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings

#: `{{ name }}`; the spaces inside the braces are optional.
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class PromptError(Exception):
    """A prompt file is missing, or its placeholders and the variables given disagree."""


@lru_cache(maxsize=None)
def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"Cannot read prompt file {path}: {exc.strerror or exc}") from exc


def load_prompt(name: str, **variables) -> str:
    """The text of prompt `name` with every `{{ placeholder }}` filled in.

    `name` is the file's path under `prompts/`, without the `.txt`:
    `load_prompt("jobs/extract_sections", section_spec=...)`.

    Raises `PromptError` when the file cannot be read, when it has a
    placeholder that no variable was given for, or when a variable was given
    that the file never uses. An unfilled `{{ name }}` reaching the model, or a
    value silently dropped, is worse than an error at start-up.
    """
    text = _read(Path(settings.PROMPTS_DIR) / f"{name}.txt")

    placeholders = set(PLACEHOLDER.findall(text))
    given = set(variables)
    missing, unused = placeholders - given, given - placeholders
    if missing or unused:
        problems = []
        if missing:
            problems.append("no value for " + ", ".join(sorted(missing)))
        if unused:
            problems.append("unused variable(s) " + ", ".join(sorted(unused)))
        raise PromptError(f"Prompt {name!r}: " + "; ".join(problems))

    # A function, not a template string, so a value containing backslashes or
    # `\1` is inserted as written.
    return PLACEHOLDER.sub(lambda match: str(variables[match.group(1)]), text)
