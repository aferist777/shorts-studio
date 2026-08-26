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
        f"Rewrite paragraph {index + 1} only."
    )


REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"paragraph": {"type": "string"}},
    "required": ["paragraph"],
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

POSTER_BRIEF = """This one is not a scene. It is the poster for the whole video, and \
it exists to be shown to the image model as the sample every other picture is drawn to \
match. So it must be the manner at full strength and nothing else: no character from the \
story, no moment from the script, nothing the narration says.

Fill it with the background jokes below and the world they live in, packed the way a \
crowded frame is packed — a few large enough to read at a glance, the rest at the edges.

Write the SAME picture twice:
- "titled": in the middle of the frame hangs a plain painted board, a banner or a plaque, \
and the lettering on it reads exactly: {title}
  Written in {language}, in the lettering of that place and period. Nothing else in the \
picture carries words this large.
- "plain": the identical picture with no board, no banner, no plaque and no lettering in \
the middle — whatever is behind it simply continues.

Everything else — the jokes, where they sit, the light, the colour — is word for word \
the same in both. They are one drawing photographed twice, not two drawings.

Each between 130 and 160 words."""

POSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "titled": {"type": "string", "description": "with the lettering in the middle"},
        "plain": {"type": "string", "description": "the same picture, no lettering"},
    },
    "required": ["titled", "plain"],
    "additionalProperties": False,
}


def poster_user_prompt(title: str, language: str, jokes: list, world: str = "") -> str:
    parts = []
    if world.strip():
        parts.append(world)
    parts.append(POSTER_BRIEF.format(title=f"“{title}”", language=language))
    parts.append("The jokes to fill it with:\n"
                 + "\n".join(f"- {j}" for j in jokes))
    return "\n\n".join(parts)


WORLD_SYSTEM = """You read a piece of narration and say where and when it happens, \
in terms an illustrator can draw.

Everything after you works from what you write. A picture of a Soviet tax office and a \
picture of an American one differ in the badge, the lettering, the furniture and the \
paper — and nobody downstream will know which to draw unless you say so here.

Answer only from the texts. If they do not settle a thing, choose the most likely \
reading and keep it plain; never invent a specific year the material does not support.

The period is what will be DRAWN, so it must be one decade, not a span. A story can run \
across fifty years — a law passed in one decade and repealed in another — but a picture \
cannot be set in fifty years, and asked for a span the illustrator will drift to whichever \
end it likes. Name the decade where most of the story happens, and if the whole span \
matters, put it in the same field afterwards as background: "1940s (the law itself runs \
to 1991)".

Name no real person, living or dead, in any field. A portrait on an office wall is "a \
framed official portrait", never whose. Everything after you is forbidden to draw a real \
person, and it cannot obey that if you have already asked for one.

For each field give concrete, drawable nouns — no adjectives standing alone, no history \
lesson, two lines each at most.

- place: the country and the kind of settlement
- period: the decade or the span of years
- architecture: buildings and interiors as they would be drawn
- dress: what ordinary people and officials wear
- objects: documents, money, machines, tools that belong to this world
- signage: the language written on signs, and how the lettering looks
- props: three or four things that could recur across many pictures

Write in English, except the signage language, which you name plainly \
("Russian, in Cyrillic")."""

WORLD_SCHEMA = {
    "type": "object",
    "properties": {
        "place": {"type": "string"},
        "period": {"type": "string"},
        "architecture": {"type": "string"},
        "dress": {"type": "string"},
        "objects": {"type": "string"},
        "signage": {"type": "string"},
        "props": {"type": "string"},
    },
    "required": ["place", "period", "architecture", "dress", "objects",
                 "signage", "props"],
    "additionalProperties": False,
}

WORLD_FIELDS = ["place", "period", "architecture", "dress", "objects",
                "signage", "props"]


def world_user_prompt(topic: str, script: str, source_text: str = "") -> str:
    parts = [f"The video is about: {topic}"]
    if source_text.strip():
        # the original keeps names and dates the retelling drops
        parts.append(f"WHAT THE ORIGINAL SOURCE SAID\n{source_text[:6000]}")
    parts.append(f"THE NARRATION AS IT WILL BE SPOKEN\n{script[:6000]}")
    parts.append("Say where and when this happens.")
    return "\n\n".join(parts)


DETAILS_SYSTEM = """You invent small background jokes for an illustrated video.

These are the things that live at the edges of a busy drawing — a sign with the wrong \
word on it, a dog stealing something in the corner, a bored official asleep behind the \
main action, a poster peeling off a wall. They do not advance what is being said. They \
reward the viewer who looks twice, and they are what makes a crowded frame worth \
crowding.

Rules that make them usable:
- Each one must be DRAWABLE in a corner of a frame, in one short phrase. "A rat in a \
tiny uniform saluting" works. "A sense of bureaucratic despair" does not.
- Each must belong to the world of THIS video. If it is about a tax on eggs, the jokes \
are about chickens, forms, queues and inspectors — not about generic funny animals.
- They must not repeat each other. Forty variations on a queue is one joke, not forty.
- Nothing that depends on words a viewer must read closely. A sign can be absurd by its \
picture; a paragraph of small print cannot.
- No named real people, no logos, no characters from existing publications.

Spread them across kinds so a handful picked at random never comes out all the same: \
signs and notices, animals behaving oddly, minor people caught mid-blunder, objects out \
of place, small disasters in progress.

Each also has a SCALE, and the two are used differently:
- big: it goes in the middle ground, drawn large enough to be caught on a first watch. \
This is what tells a viewer the picture is worth a second look. Give it something with \
a shape at a distance — a whole animal, a person mid-fall, a machine coming apart.
- small: it hides at an edge or in a corner and rewards the one who looks again. It can \
be finer — a hand doing something odd, a creature under a table, an object out of place.

Give roughly one big for every two small.

Write in English, one phrase each."""

DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "details": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "description": "sign, animal, person, object or mishap"},
                    "detail": {"type": "string",
                               "description": "one drawable phrase"},
                    "scale": {"type": "string",
                              "description": "big for the middle ground, "
                                             "small for the edges"},
                },
                "required": ["kind", "detail", "scale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["details"],
    "additionalProperties": False,
}


def details_user_prompt(script: str, topic: str, count: int) -> str:
    return (f"The video is about: {topic}\n\n"
            f"THE WHOLE NARRATION\n{script[:9000]}\n\n"
            f"Invent {count} background jokes for this world.")


SHOTS_SYSTEM = """You break one beat of narration into separate pictures.

Describe what is in each picture and nothing else: who is there, what they are doing, \
where it happens, and how close the camera is. No drawing style, no mood words, no \
colours — that is decided later and by somebody else.

The pictures of one beat must show DIFFERENT things. Vary two axes at once:
- how close: a wide view of the place, a face filling the frame, an object filling the \
frame, a small detail of the surroundings
- what is looked at: the person acting, the person reacting, the thing being talked \
about, the place itself

Four restagings of the same moment from four angles is a failure. Each picture earns \
its place by showing something the others do not.

NEVER leave the subject empty. If no particular character belongs in a picture, put \
something else living or telling in it — a crowd going about its business, a queue, a \
street full of signs and clutter, a room busy with objects. An empty frame is not an \
option; a frame without a main character is.

Write in English, plainly, one short sentence per field."""

SHOTS_SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string",
                                "description": "Who or what fills the frame — never empty"},
                    "action": {"type": "string", "description": "What is happening"},
                    "place": {"type": "string", "description": "Where it happens"},
                    "framing": {"type": "string",
                                "description": "wide, medium, close-up or detail"},
                },
                "required": ["subject", "action", "place", "framing"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["shots"],
    "additionalProperties": False,
}


def shots_user_prompt(beat: str, count: int, topic: str = "") -> str:
    parts = []
    if topic:
        parts.append(f"The video is about: {topic}")
    parts.append(f"The beat being spoken:\n{beat}")
    parts.append(f"Give exactly {count} pictures, each showing something different.")
    return "\n\n".join(parts)


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
