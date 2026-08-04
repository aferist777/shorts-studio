"""Claude via the official Anthropic SDK.

Notes that bite if forgotten:
- Opus 5 rejects `temperature` / `top_p` / `top_k` with a 400. Steer with the prompt.
- Thinking is on by default on Opus 5; `effort` is the depth/cost dial.
- A safety decline comes back as HTTP 200 with stop_reason == "refusal" and
  empty content, so stop_reason is checked before content is read.
"""

import json

from app.config import get_key

MAX_TOKENS = 16000


def _client():
    key = get_key("anthropic")
    if not key:
        raise RuntimeError("No Anthropic API key. Add one in Settings.")
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("The `anthropic` package is missing — run: pip install anthropic") from e
    return anthropic.Anthropic(api_key=key)


def complete_json(model: str, effort: str, system: str, user: str, schema: dict) -> dict:
    client = _client()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": schema},
        },
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        reason = getattr(detail, "explanation", None) or "no explanation given"
        raise RuntimeError(f"Claude declined this request ({reason}).")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Response hit the token limit — try fewer paragraphs.")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("Claude returned no text.")
    return json.loads(text)
