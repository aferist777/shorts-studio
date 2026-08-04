"""OpenAI-compatible chat completions — OpenRouter, OpenAI, and anything that
speaks the same shape. Kept separate from the Anthropic path on purpose.
"""

import json

import httpx

from app.config import get_key

BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
}

TIMEOUT = 180.0
# without a ceiling a weaker model can loop and return tens of KB of garbage;
# reasoning models spend part of this budget before writing anything, so the
# guard sits well above what the visible answer needs
MAX_TOKENS = 8000


def complete_json(provider: str, model: str, system: str, user: str, schema: dict,
                  max_tokens: int = MAX_TOKENS) -> dict:
    key = get_key(provider)
    if not key:
        raise RuntimeError(f"No {provider} API key. Add one in Settings.")
    base = BASE_URLS.get(provider)
    if not base:
        raise RuntimeError(f"Unknown provider: {provider}")

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "result", "strict": True, "schema": schema},
        },
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["X-Title"] = "Shorts Studio"

    r = httpx.post(f"{base}/chat/completions", json=payload, headers=headers, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"{provider} error {r.status_code}: {r.text[:300]}")

    body = r.json()
    try:
        choice = body["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected {provider} response: {str(body)[:300]}") from e

    if choice.get("finish_reason") == "length":
        raise RuntimeError(
            f"{model} ran past the token limit without closing its JSON — "
            "pick a model that supports structured outputs, or ask for fewer scenes."
        )
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{model} did not return valid JSON: {content[:200]}") from e
