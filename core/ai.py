"""Shared DeepSeek chat-completions client.

Any feature that needs an LLM to turn raw text into structured JSON
(job post analysis, resume parsing, ...) calls `call_deepseek_json`
with its own system prompt rather than talking to the HTTP API
directly, so the request/error-handling logic lives in one place.
"""

import json

import requests
from django.conf import settings


class AIServiceError(Exception):
    """Raised for any failure calling or parsing the AI service's response."""


class AIConfigError(AIServiceError):
    """Raised when DEEPSEEK_API_KEY isn't configured."""


def call_deepseek_json(system_prompt: str, user_content: str, *, temperature: float = 0.2) -> dict:
    """Send a system/user message pair to DeepSeek and return the parsed
    JSON object it replies with (JSON mode). Raises AIServiceError /
    AIConfigError with a message safe to show to the end user."""

    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        raise AIConfigError(
            "AI analysis isn't configured yet — set DEEPSEEK_API_KEY in your "
            "environment to enable it."
        )

    try:
        response = requests.post(
            f"{settings.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "response_format": {"type": "json_object"},
                "temperature": temperature,
            },
            timeout=settings.DEEPSEEK_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        raise AIServiceError("The AI analysis took too long and timed out. Please try again.")
    except requests.exceptions.RequestException:
        raise AIServiceError("Couldn't reach the AI analysis service. Please try again.")

    if response.status_code == 401:
        raise AIServiceError("The AI analysis service rejected our API key.")
    if response.status_code == 429:
        raise AIServiceError("The AI analysis service is rate-limiting us. Please try again shortly.")
    if not response.ok:
        raise AIServiceError(f"The AI analysis service returned an error (HTTP {response.status_code}).")

    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AIServiceError("The AI analysis service returned an unexpected response.")

    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        raise AIServiceError("The AI analysis service returned invalid JSON.")

    if not isinstance(data, dict):
        raise AIServiceError("The AI analysis service returned an unexpected response.")

    data["_model"] = payload.get("model", settings.DEEPSEEK_MODEL)
    return data
