"""Turning a transcript into topics that could each carry their own short.

The model never handles timecodes. Cues are grouped into numbered blocks, the
model answers in block indices, and real seconds are substituted back from the
source data — long numbers are exactly the thing LLMs copy wrong.
"""

from app.services.llm import call_json

# 30s blocks let up to half a minute of sponsor chatter bleed into a topic's head;
# 15s roughly doubles the index count for a negligible token cost
BLOCK_SECONDS = 15
MAX_TRANSCRIPT_CHARS = 120_000   # ~2.5h of speech; beyond that we warn instead


def build_blocks(cues: list, block_seconds: int = BLOCK_SECONDS) -> list:
    """-> [{'index', 'start', 'end', 'text'}]"""
    blocks, current = [], None
    for cue in cues:
        if current is None or cue["start"] - current["start"] >= block_seconds:
            current = {"index": len(blocks), "start": cue["start"],
                       "end": cue["end"], "parts": []}
            blocks.append(current)
        current["parts"].append(cue["text"])
        current["end"] = cue["end"]
    return [{"index": b["index"], "start": b["start"], "end": b["end"],
             "text": " ".join(b["parts"])} for b in blocks]


def trim_edges(text: str) -> str:
    """Drop a dangling half-sentence at either end of a slice.

    Blocks are cut on seconds, so a topic often opens mid-phrase. A lowercase
    first character is the reliable tell that we landed inside a sentence —
    trimming on the first full stop alone would eat legitimate short openers.
    """
    body = text.strip()
    if not body:
        return text
    if body[0].islower():
        for i, char in enumerate(body[:400]):
            if char in ".!?":
                body = body[i + 1:].lstrip()
                break
    if body and body[-1] not in ".!?":
        last = max(body.rfind(c) for c in ".!?")
        if last > 0:
            body = body[:last + 1]
    return body or text


def _timestamp(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def render_transcript(blocks: list) -> str:
    return "\n".join(f"[{b['index']}] {_timestamp(b['start'])} {b['text']}" for b in blocks)


TOPICS_SYSTEM = """You read the transcript of a long video and find the topics inside it that \
could each carry a standalone short video.

What counts as a topic:
- One self-contained idea, story or claim. Someone who never saw the source should be able to \
follow it from your excerpt alone.
- A complete arc, not a fragment. Whatever length the material actually needs — usually a couple \
of minutes, sometimes ten.
- Topics do not overlap and stay in the order they appear.
- Start the span on the first sentence that belongs to the topic itself, not on the sentence \
before it.

Skip entirely: intros and outros, greetings, sponsor reads, merch and subscribe prompts, channel \
housekeeping, and anything that is only there to link two other parts together.

For each topic give a title that states what is actually interesting about it, a summary of two \
sentences at most saying what the source really claims, and a short project name of two to six \
words. Write all three in the same language as the transcript.

The transcript may be machine-generated, so it can contain mis-heard words and no speaker labels. \
Read through the errors rather than quoting them.

Return the span as block indices from the numbered transcript. Never invent timecodes."""


TOPICS_SCHEMA = {
    "type": "object",
    "properties": {
        "video_summary": {"type": "string", "description": "One sentence on the video as a whole"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "project_name": {"type": "string"},
                    "start_block": {"type": "integer"},
                    "end_block": {"type": "integer"},
                },
                "required": ["title", "summary", "project_name", "start_block", "end_block"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["video_summary", "topics"],
    "additionalProperties": False,
}


def extract(info: dict, cues: list, settings: dict, progress=None) -> dict:
    """-> {'video_summary': str, 'topics': [...]} with real seconds and text filled in."""
    blocks = build_blocks(cues)
    if not blocks:
        raise RuntimeError("The transcript came back empty.")

    transcript = render_transcript(blocks)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise RuntimeError(
            f"This transcript is {len(transcript) // 1000}k characters — too long for one pass. "
            "Try a shorter video for now."
        )

    if progress:
        progress(f"Finding topics in {len(blocks)} blocks")

    user = (
        f"Video title: {info.get('title', '')}\n"
        f"Channel: {info.get('channel', '')}\n"
        f"Length: {int(info.get('duration', 0)) // 60} minutes\n\n"
        f"Description:\n{(info.get('description') or '')[:1500]}\n\n"
        f"Transcript, one numbered block per {BLOCK_SECONDS} seconds:\n{transcript}"
    )

    data = call_json(
        settings["llm_provider"], settings["llm_model"],
        settings.get("llm_effort", "medium"),
        TOPICS_SYSTEM, user, TOPICS_SCHEMA,
        max_tokens=16000,   # ten topics of Russian prose overflow the default ceiling
    )

    last = len(blocks) - 1
    topics = []
    for raw in data.get("topics", []):
        start_index = max(0, min(last, int(raw.get("start_block", 0))))
        end_index = max(start_index, min(last, int(raw.get("end_block", start_index))))
        span = blocks[start_index:end_index + 1]
        topics.append({
            "title": raw.get("title", "").strip(),
            "summary": raw.get("summary", "").strip(),
            "project_name": (raw.get("project_name") or raw.get("title") or "").strip()[:60],
            "start": span[0]["start"],
            "end": span[-1]["end"],
            "text": trim_edges(" ".join(b["text"] for b in span)),
            "used_by": "",
        })

    if not topics:
        raise RuntimeError("No topics came back for this video.")
    return {"video_summary": data.get("video_summary", "").strip(), "topics": topics}
