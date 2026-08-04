"""Model registry + the two script-step calls the app actually makes.

Two backends, kept in separate modules on purpose: Anthropic goes through the
official SDK, everything OpenAI-shaped goes through plain HTTP. They are never
mixed.
"""

from app.services import prompts
from app.services.llm import anthropic_backend, openai_backend

# provider -> (label, [model ids]). First model is the default.
REGISTRY = {
    "anthropic": (
        "Anthropic",
        ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
    ),
    "openrouter": (
        "OpenRouter",
        [
            "google/gemini-3.5-flash",
            "anthropic/claude-opus-5",
            "openai/gpt-5.5",
            "deepseek/deepseek-v4-pro",
            "nousresearch/hermes-4-405b",
        ],
    ),
    "openai": ("OpenAI", ["gpt-5.5", "gpt-5.4-mini"]),
}

EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def models_for(provider: str) -> list:
    return REGISTRY.get(provider, ("", []))[1]


def _call_json(provider: str, model: str, effort: str, system: str, user: str, schema: dict) -> dict:
    if provider == "anthropic":
        return anthropic_backend.complete_json(model, effort, system, user, schema)
    return openai_backend.complete_json(provider, model, system, user, schema)


def generate_script(settings: dict, topic: str, language: str, paragraphs: int, tone: str) -> dict:
    """-> {"title": str, "paragraphs": [str, ...]}"""
    data = _call_json(
        settings["llm_provider"],
        settings["llm_model"],
        settings.get("llm_effort", "medium"),
        prompts.SCRIPT_SYSTEM,
        prompts.script_user_prompt(topic, language, paragraphs, tone),
        prompts.SCRIPT_SCHEMA,
    )
    out = [p.strip() for p in data.get("paragraphs", []) if p and p.strip()]
    if not out:
        raise RuntimeError("The model returned an empty script.")
    return {"title": (data.get("title") or topic)[:80], "paragraphs": out}


def generate_terms(settings: dict, paragraphs: list, topic: str) -> list:
    """-> [[str, ...], ...] aligned with `paragraphs` (padded if the model is short)."""
    numbered = "\n\n".join(f"[{i + 1}] {p}" for i, p in enumerate(paragraphs))
    user = f"Overall topic: {topic}\n\nParagraphs:\n{numbered}"
    data = _call_json(
        settings["llm_provider"],
        settings["llm_model"],
        "low",  # keyword extraction is not reasoning-heavy
        prompts.TERMS_SYSTEM,
        user,
        prompts.TERMS_SCHEMA,
    )
    terms = data.get("terms", [])
    while len(terms) < len(paragraphs):
        terms.append([])
    return [[str(t) for t in group][:4] for group in terms[: len(paragraphs)]]


def rewrite_paragraph(settings: dict, topic: str, language: str, tone: str,
                      script: list, index: int) -> dict:
    """-> {"paragraph": str, "terms": [str, ...]} for one scene, in context."""
    data = _call_json(
        settings["llm_provider"],
        settings["llm_model"],
        settings.get("llm_effort", "medium"),
        prompts.REWRITE_SYSTEM,
        prompts.rewrite_user_prompt(topic, language, tone, script, index),
        prompts.REWRITE_SCHEMA,
    )
    text = (data.get("paragraph") or "").strip()
    if not text:
        raise RuntimeError("The model returned an empty paragraph.")
    return {"paragraph": text, "terms": [str(t) for t in data.get("terms", [])][:4]}
