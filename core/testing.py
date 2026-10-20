"""Helpers shared by the apps' test suites. Nothing in production imports this.

`fake_deepseek` stubs the one place the app talks to the AI provider — the HTTP
call inside `core.ai.call_deepseek_json` — rather than any module that happens
to import that function. Tests written against it keep working when code is
moved around, and they see exactly what the provider would: the system prompt
and the user message.
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import patch

from django.test import override_settings
from django.utils import translation


@dataclass
class AIRequest:
    """One chat-completions request the app made."""

    system: str
    user: str
    temperature: float | None


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._body


@contextmanager
def fake_deepseek(reply, *, model: str = "deepseek-test"):
    """Answer every AI call with `reply(request) -> dict | int`, and yield the
    list of `AIRequest`s received so far.

    * a dict is what the model "says" (sent back as its JSON-mode message);
    * a str is sent back verbatim, for malformed output that is not JSON;
    * an int is an HTTP status the provider fails with (401, 429, 500, ...);
    * `reply` may also raise, e.g. `requests.exceptions.Timeout`.
    """
    calls: list[AIRequest] = []

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):  # noqa: A002
        messages = {m["role"]: m["content"] for m in json["messages"]}
        request = AIRequest(
            system=messages["system"],
            user=messages["user"],
            temperature=json.get("temperature"),
        )
        calls.append(request)
        outcome = reply(request)
        if isinstance(outcome, int):
            return _FakeResponse(outcome)
        content = outcome if isinstance(outcome, str) else _dumps(outcome)
        return _FakeResponse(200, {"model": model, "choices": [{"message": {"content": content}}]})

    with override_settings(DEEPSEEK_API_KEY="test-key"), patch(
        "core.ai.requests.post", side_effect=fake_post
    ):
        yield calls


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def pin_language(testcase, language: str = "en") -> None:
    """Run `testcase` under `language`, and put back whatever was active after.

    Views re-activate a language on every request, but a test that calls code
    directly (a task, a seed, `str(lazy_label)`) gets whichever language an
    earlier test left active on the thread — a profile switch leaves French.
    Anything that asserts on English text from such a call pins it first.
    """
    override = translation.override(language)
    override.__enter__()
    testcase.addCleanup(override.__exit__, None, None, None)
