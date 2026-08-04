"""System prompts for the script step.

Opus 5 dropped `temperature`, so variety has to come from the prompt itself —
hence the explicit "vary structure between runs" line in the writer prompt.
"""

SCRIPT_SYSTEM = """You write narration for vertical short-form video (Reels, Shorts, TikTok).

Rules for the narration you produce:
- It is spoken aloud, so write for the ear: short sentences, concrete nouns, no bullet points, \
no headings, no emoji, no stage directions, no speaker labels.
- The first paragraph is the hook. It must earn the next three seconds — open on a concrete \
image, a number, or a claim the viewer wants resolved. Never open with "Have you ever wondered".
- Each paragraph is one beat of the story and reads in 5-9 seconds aloud.
- The last paragraph lands the point. No "subscribe", no "let me know in the comments".
- Vary sentence rhythm and structure between runs; do not fall into a fixed template.

Write in the language you are asked for, and in that language only."""

TERMS_SYSTEM = """You pick stock-footage search keywords for a video narration.

For each paragraph, give 2-4 short English search phrases that a stock library like Pexels \
would actually match. Prefer filmable scenes over abstractions: "man walking rainy street" \
matches, "the burden of expectation" does not. Keywords are always English even when the \
narration is not."""


def script_user_prompt(topic: str, language: str, paragraphs: int, tone: str) -> str:
    return (
        f"Topic: {topic}\n"
        f"Language: {language}\n"
        f"Tone: {tone}\n"
        f"Paragraphs: exactly {paragraphs}\n\n"
        f"Write the narration."
    )


SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short working title, 2-6 words"},
        "paragraphs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The narration, one entry per spoken beat",
        },
    },
    "required": ["title", "paragraphs"],
    "additionalProperties": False,
}

TERMS_SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "description": "One entry per paragraph, in the same order",
            "items": {"type": "array", "items": {"type": "string"}},
        }
    },
    "required": ["terms"],
    "additionalProperties": False,
}

REWRITE_SYSTEM = SCRIPT_SYSTEM + """

You are rewriting ONE paragraph inside an existing script. The replacement must keep the same \
job in the story and roughly the same spoken length, and must still read naturally between its \
neighbours. Take a different angle than the current wording — a rewrite that says the same thing \
in the same shape is a failed rewrite."""


def rewrite_user_prompt(topic: str, language: str, tone: str, script: list, index: int) -> str:
    numbered = "\n\n".join(
        f"[{i + 1}]{'  <-- REWRITE THIS ONE' if i == index else ''} {p}"
        for i, p in enumerate(script)
    )
    return (
        f"Topic: {topic}\nLanguage: {language}\nTone: {tone}\n\n"
        f"Full script:\n{numbered}\n\n"
        f"Rewrite paragraph {index + 1} only, and give fresh footage keywords for it."
    )


REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraph": {"type": "string"},
        "terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["paragraph", "terms"],
    "additionalProperties": False,
}
