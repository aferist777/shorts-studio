"""System prompts for the script step.

Opus 5 dropped `temperature`, so variety has to come from the prompt itself —
hence the explicit "vary structure between runs" line in the writer prompt.

Everything here lives in the app. Nothing is read from an outside vault at run
time; the anti-pattern rules below were transcribed once, by hand, at design time.
"""

# The subset of machine-writing tells that survive being read aloud. Formatting
# tics — em dashes, bold, curly quotes, heading case, emoji — are omitted on
# purpose: none of them exist in speech.
NO_MACHINE_VOICE = """Never write like a language model. Specifically:

- No inflated significance. Nothing "marks a turning point", "plays a key role", \
"leaves an indelible mark" or "reflects a broader trend".
- No lists of three. Two examples, or four, or one — never the reflexive triad.
- No negative parallelism. Not "it isn't just X, it's Y", not "не просто X, а Y".
- No participle tails bolted onto a finished sentence: "подчёркивая", "отражая", \
"тем самым показывая", "highlighting", "ensuring", "showcasing".
- No anonymous authorities. "Историки считают", "эксперты говорят", "исследования \
показывают" — unless the source names who.
- No stacked hedging. Say it, or leave it out.
- No upbeat wrap-up. The last line is the last beat of the story, not a moral.
- No synonym cycling. If it is a king, call him a king every time — not "монарх", \
then "правитель", then "властитель".
- Vary sentence length deliberately. Even, similar-length sentences read as machine \
output even when every word is right.

Russian phrases that are banned outright: важно отметить, стоит отметить, следует \
отметить, в современном мире, неотъемлемая часть, сыграл ключевую роль, не что иное \
как, поражает воображение, трудно переоценить, красной нитью, во главу угла, \
не оставит равнодушным."""

SCRIPT_SYSTEM = """You write narration for vertical short-form video (Reels, Shorts, TikTok).

Rules for the narration you produce:
- It is spoken aloud, so write for the ear: short sentences, concrete nouns, no bullet points, \
no headings, no emoji, no stage directions, no speaker labels.
- The first paragraph IS the hook you are given, in the words you are given. Do not rewrite \
it and do not preface it.
- Every paragraph after it delivers on that hook. If a paragraph would still make sense under \
a different opening, it is the wrong paragraph.
- Each paragraph is one beat of the story and reads in 5-9 seconds aloud.
- The last paragraph lands the point the hook promised. No "subscribe", no "let me know in \
the comments".
- Vary sentence rhythm and structure between runs; do not fall into a fixed template.

Write in the language you are asked for, and in that language only. Follow the narrator \
you are given."""

TERMS_SYSTEM = """You pick stock-footage search keywords for a video narration.

For each paragraph, give 2-4 short English search phrases that a stock library like Pexels \
would actually match. Prefer filmable scenes over abstractions: "man walking rainy street" \
matches, "the burden of expectation" does not. Keywords are always English even when the \
narration is not."""


def script_user_prompt(topic: str, language: str, paragraphs: int, tone: str,
                       narrator_block: str = "", hook: str = "") -> str:
    return (
        f"Topic: {topic}\n"
        f"Language: {language}\n"
        f"Tone: {tone}\n"
        f"Paragraphs: exactly {paragraphs}, the first being the hook\n\n"
        f"{narrator_block}\n\n"
        f"The hook, already chosen:\n{hook}\n\n"
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


# ---- narrators -------------------------------------------------------------
# The neutral narrator carries the anti-machine rules. A narrator built from real
# writing replaces them with its own profile instead of stacking on top: a profile
# already says what its author never does, and one voice per prompt beats two sets
# of rules arguing about precedence.
NEUTRAL_BLOCK = ("Write plainly and let the material carry the interest.\n\n"
                 + NO_MACHINE_VOICE)

NARRATOR_ANALYSIS_SYSTEM = """You read several texts by one author and describe how that \
author writes, so another writer can produce new work in the same voice.

Describe HOW they write, never WHAT they wrote about. If a subject from the samples \
appears in your description, you have gone wrong — the profile has to fit a topic the \
author never touched.

Quote from the samples. Every observation needs a short quotation showing it; where you \
cannot quote, you invented the observation and should drop it.

Be specific and behavioural. "Ironic and lively" is useless. "Undersells catastrophes — \
calls a massacre an unpleasantness, an empire an outfit" can be followed.

The negative space matters as much as the rest: what this author consistently does not do \
is part of the voice.

Write the profile in the same language as the samples."""

NARRATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two sentences: who this voice is"},
        "sentences": {"type": "string", "description": "Sentence architecture and length"},
        "rhythm": {"type": "string", "description": "Pacing — where it slows and speeds up"},
        "address": {"type": "string", "description": "Person used, how it treats the audience"},
        "register": {"type": "string", "description": "Vocabulary and level of formality"},
        "imagery": {"type": "string", "description": "What areas its metaphors come from"},
        "humour": {"type": "string", "description": "Kind of humour, or its absence"},
        "openings": {"type": "string", "description": "How it starts a piece"},
        "endings": {"type": "string", "description": "How it lands a piece"},
        "stance": {"type": "string", "description": "Its attitude towards the subject"},
        "signature_moves": {"type": "array", "items": {"type": "string"},
                            "description": "Recurring devices, with a quotation each"},
        "never_does": {"type": "array", "items": {"type": "string"},
                       "description": "What this author consistently avoids"},
    },
    "required": ["summary", "sentences", "rhythm", "address", "register", "imagery",
                 "humour", "openings", "endings", "stance", "signature_moves",
                 "never_does"],
    "additionalProperties": False,
}

_PROFILE_ROWS = [
    ("sentences", "Sentences"), ("rhythm", "Rhythm"), ("address", "Address"),
    ("register", "Register"), ("imagery", "Imagery"), ("humour", "Humour"),
    ("openings", "Openings"), ("endings", "Endings"), ("stance", "Stance"),
]


def render_profile(profile: dict) -> str:
    """A stored analysis, turned back into prompt text."""
    lines = [f"Write as this narrator.\n\n{profile.get('summary', '').strip()}"]
    for key, label in _PROFILE_ROWS:
        value = (profile.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    moves = [m.strip() for m in profile.get("signature_moves", []) if m.strip()]
    if moves:
        lines.append("Signature moves:\n" + "\n".join(f"- {m}" for m in moves))
    never = [n.strip() for n in profile.get("never_does", []) if n.strip()]
    if never:
        lines.append("Never does:\n" + "\n".join(f"- {n}" for n in never))
    lines.append("This governs how things are said. It never governs what is true — "
                 "facts come from the material, not from the voice.")
    return "\n\n".join(lines)


def narrator_analysis_user_prompt(samples: list) -> str:
    blocks = "\n\n---\n\n".join(f"[Sample {i + 1}]\n{s}" for i, s in enumerate(samples))
    return f"{len(samples)} texts by the same author:\n\n{blocks}\n\nDescribe the voice."


# ---- hooks -----------------------------------------------------------------

HOOKS_SYSTEM = f"""You write opening lines for vertical short-form video.

The hook is the first thing said out loud. It has about three seconds to make \
someone not scroll away, and everything after it exists to pay off what it promised.

Give five hooks that differ in KIND, not in wording. Between them use:
- a number that does not fit in the head
- a contradiction the viewer wants resolved
- a question that cannot be left unanswered
- a scene dropped mid-action, no setup
- a claim aimed straight at the viewer

Each is one or two spoken sentences. No preamble, no "in this video", no greeting. \
Never promise something the material cannot deliver.

Write in the language you are asked for, and follow the narrator you are given."""

HOOKS_SCHEMA = {
    "type": "object",
    "properties": {
        "hooks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": ("Which approach this is, in two or three words: "
                                        "number, contradiction, question, scene, challenge"),
                    },
                    "text": {"type": "string"},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hooks"],
    "additionalProperties": False,
}


def hooks_user_prompt(topic: str, language: str, tone: str, narrator_block: str,
                      source_text: str = "") -> str:
    parts = [f"Topic: {topic}", f"Language: {language}", f"Tone: {tone}",
             f"\n{narrator_block}\n"]
    if source_text:
        parts.append(
            "\nThe video is built on this source material. Every hook must be "
            "supported by something actually in it:\n" + source_text[:12000])
    parts.append("\nWrite the five hooks.")
    return "\n".join(parts)


# ---- script from a transcript ----------------------------------------------

SOURCE_SCRIPT_SYSTEM = f"""You write narration for vertical short-form video, working \
from a transcript of a longer video.

The transcript is raw material, not a draft. It may be ten times longer than what you \
are about to write, and it may contain speech-recognition errors — read through them.

How to use it:
- Select, do not summarise. Choose one line of argument and follow it. Everything that \
does not serve that line gets dropped, however interesting it is.
- Never walk the transcript in order, paraphrasing as you go. That produces a recap, \
and a recap is the failure mode here.
- Take facts, names and numbers only from the transcript. Do not add any the source \
does not contain, and do not soften or sharpen what it says to fit the hook.
- Reuse no phrase from the source longer than a few words. Say it your own way.

Structure:
- The first paragraph IS the hook you are given, in the words you are given, or as close \
as the language allows. Do not rewrite it and do not preface it.
- Every paragraph after it delivers on that hook. If a paragraph would still make sense \
under a different opening, it is the wrong paragraph.
- The last paragraph lands the point the hook promised. No "subscribe", no moral.

It is spoken aloud: no bullet points, no headings, no emoji, no stage directions, no \
speaker labels. Each paragraph reads in five to nine seconds.

Write in the language you are asked for, and in that language only. Follow the narrator \
you are given."""


def source_script_user_prompt(hook: str, topic: str, language: str, paragraphs: int,
                              tone: str, narrator_block: str, source_text: str) -> str:
    return (
        f"Topic: {topic}\n"
        f"Language: {language}\n"
        f"Tone: {tone}\n"
        f"Paragraphs: exactly {paragraphs}, the first being the hook\n\n"
        f"{narrator_block}\n\n"
        f"The hook, already chosen:\n{hook}\n\n"
        f"Source transcript:\n{source_text}\n\n"
        f"Write the narration."
    )


# ---- the cleaning pass -----------------------------------------------------

HUMANIZER_SYSTEM = """You are an editor. You are given narration a language model just \
wrote, and you bring it into line with the narrator it was supposed to be written as — \
taking out anything that sounds like a machine rather than that voice.

Two things matter as much as the narrator's own rules:

Keep the meaning and the facts exactly. You are changing how it sounds, not what it says. \
Do not add a fact, drop a fact, or shift a claim.

Do not flatten it. Sterile, voiceless writing gives itself away just as fast as slop does. \
Where a line is dull, make it specific rather than neutral: not "это тревожно" but the \
concrete thing that is troubling. Let sentence lengths differ. Let the author have an \
opinion where they clearly had one.

You are given the video's opening line for context. It is fixed and is not yours to \
edit — the paragraphs you clean have to keep delivering on it.

Return exactly as many paragraphs as you were given, in the same order, in the same \
language."""

HUMANIZER_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["paragraphs"],
    "additionalProperties": False,
}


def humanizer_user_prompt(paragraphs: list, narrator_block: str, hook: str = "") -> str:
    numbered = "\n\n".join(f"[{i + 1}] {p}" for i, p in enumerate(paragraphs))
    head = f"{narrator_block}\n"
    if hook:
        head += f"\nThe opening line, fixed and not to be returned:\n{hook}\n"
    return f"{head}\nClean these {len(paragraphs)} paragraphs:\n\n{numbered}"
