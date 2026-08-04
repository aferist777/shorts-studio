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


def call_json(provider: str, model: str, effort: str, system: str, user: str,
              schema: dict, max_tokens: int = 8000) -> dict:
    """One structured-output call, routed to whichever backend the provider needs."""
    if provider == "anthropic":
        return anthropic_backend.complete_json(model, effort, system, user, schema, max_tokens)
    return openai_backend.complete_json(provider, model, system, user, schema, max_tokens)


def generate_hooks(settings: dict, topic: str, language: str, tone: str,
                   narrator: str = "neutral", source_text: str = "") -> list:
    """Five opening lines that differ in kind. -> [{'kind', 'text'}]"""
    data = call_json(
        settings["llm_provider"], settings["llm_model"],
        settings.get("llm_effort", "medium"),
        prompts.HOOKS_SYSTEM,
        prompts.hooks_user_prompt(topic, language, tone, narrator, source_text),
        prompts.HOOKS_SCHEMA,
    )
    hooks = [{"kind": h.get("kind", ""), "text": (h.get("text") or "").strip()}
             for h in data.get("hooks", []) if (h.get("text") or "").strip()]
    if not hooks:
        raise RuntimeError("No hooks came back.")
    return hooks


def generate_script(settings: dict, topic: str, language: str, paragraphs: int,
                    tone: str, hook: str = "", narrator: str = "neutral",
                    source_text: str = "") -> dict:
    """-> {"title": str, "paragraphs": [str, ...]}

    With a transcript to work from the writing task is a different one — selecting
    from ten times the material rather than inventing it — so it gets its own prompt.
    """
    if source_text:
        system = prompts.SOURCE_SCRIPT_SYSTEM
        user = prompts.source_script_user_prompt(
            hook, topic, language, paragraphs, tone, narrator, source_text)
    else:
        system = prompts.SCRIPT_SYSTEM
        user = prompts.script_user_prompt(
            topic, language, paragraphs, tone, narrator, hook)

    data = call_json(
        settings["llm_provider"], settings["llm_model"],
        settings.get("llm_effort", "medium"),
        system, user, prompts.SCRIPT_SCHEMA, max_tokens=8000,
    )
    out = [p.strip() for p in data.get("paragraphs", []) if p and p.strip()]
    if not out:
        raise RuntimeError("The model returned an empty script.")
    return {"title": (data.get("title") or topic)[:80], "paragraphs": out}


def humanize(settings: dict, paragraphs: list, narrator: str = "neutral") -> list:
    """Second pass over freshly written narration, stripping machine tics.

    A model is poor at spotting its own tells right after writing; a separate
    pass with an explicit checklist catches what prevention alone misses.

    The first paragraph is the hook the user approved, so it is never sent to be
    cleaned — asking politely was not enough, the model reworded it anyway.
    """
    if len(paragraphs) < 2:
        return list(paragraphs)

    hook, rest = paragraphs[0], list(paragraphs[1:])
    data = call_json(
        settings["llm_provider"], settings["llm_model"],
        settings.get("llm_effort", "medium"),
        prompts.HUMANIZER_SYSTEM,
        prompts.humanizer_user_prompt(rest, narrator, hook),
        prompts.HUMANIZER_SCHEMA, max_tokens=8000,
    )
    cleaned = [p.strip() for p in data.get("paragraphs", []) if p and p.strip()]
    # a pass that loses or invents paragraphs is worse than no pass
    return [hook] + (cleaned if len(cleaned) == len(rest) else rest)


def generate_terms(settings: dict, paragraphs: list, topic: str) -> list:
    """-> [[str, ...], ...] aligned with `paragraphs` (padded if the model is short)."""
    numbered = "\n\n".join(f"[{i + 1}] {p}" for i, p in enumerate(paragraphs))
    user = f"Overall topic: {topic}\n\nParagraphs:\n{numbered}"
    data = call_json(
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
    data = call_json(
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
