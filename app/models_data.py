"""Plain data objects, JSON-round-trippable."""

import math
import uuid
from dataclasses import dataclass, field, asdict


def new_id() -> str:
    return uuid.uuid4().hex[:12]


MAX_VISUALS = 8
SECONDS_PER_VISUAL = 5.0


def visual_count(duration: float) -> int:
    """How many pictures a scene of this length wants.

    Five seconds is the ceiling a picture may stay on screen, not an average —
    so the count rounds UP, and a scene takes the fewest pictures that keeps
    every one of them under it. Eight seconds is two at four, six is two at
    three, thirteen is three at four and a third.

    Up rather than nearest, because the pictures are dense enough to be worth
    looking at: the cost of one being a second short is a cut nobody minds, and
    the cost of one running long is a frame going stale on screen.
    """
    if duration <= 0:
        return 1
    return max(1, min(MAX_VISUALS, math.ceil(duration / SECONDS_PER_VISUAL)))


def share_duration(total: float, count: int) -> list:
    """Split a scene's length evenly, with the rounding crumbs on the last one.

    Ten seconds across two pieces is five each, across three is 3.3 — and the
    parts always add back up to the whole, which matters because the renderer
    lays them end to end under one continuous voice track.
    """
    if count <= 0:
        return []
    each = round(total / count, 3)
    lengths = [each] * count
    lengths[-1] = round(total - each * (count - 1), 3)
    return lengths


@dataclass
class Visual:
    """One shot inside a scene — a cut piece, a saved frame, or stock."""

    path: str = ""
    kind: str = "clip"       # "clip" | "still"
    source: str = ""         # "fragment" | "pexels" | "pixabay" | "local"
    thumb: str = ""
    credit: str = ""
    duration: float = 0.0    # its share of the scene, recomputed when the list changes
    # Taken out of the scene without being thrown away: it keeps its place in
    # the list, so putting it back needs no memory of where it was.
    off: bool = False

    @staticmethod
    def from_dict(d: dict) -> "Visual":
        return Visual(**{k: v for k, v in d.items() if k in Visual.__annotations__})


@dataclass
class Scene:
    """One paragraph of narration and everything derived from it."""

    text: str = ""
    clip_path: str = ""                          # local video used for this scene
    clip_source: str = ""                        # "pexels" | "pixabay" | "local"
    clip_thumb: str = ""                         # cached poster frame for the UI
    clip_credit: str = ""                        # author, for attribution
    audio_path: str = ""
    duration: float = 0.0
    words: list = field(default_factory=list)   # [{"w", "start", "end"}] for karaoke subs
    voice: str = ""                              # voice id the audio was made with
    visuals: list = field(default_factory=list)  # list[Visual], in playing order

    @staticmethod
    def from_dict(d: dict) -> "Scene":
        known = {k: v for k, v in d.items() if k in Scene.__annotations__}
        known["visuals"] = [Visual.from_dict(v) for v in d.get("visuals", [])]
        scene = Scene(**known)
        # projects written when a scene held exactly one clip still open: that
        # clip becomes the first and only shot
        if not scene.visuals and scene.clip_path:
            scene.visuals = [Visual(path=scene.clip_path, kind="clip",
                                    source=scene.clip_source, thumb=scene.clip_thumb,
                                    credit=scene.clip_credit, duration=scene.duration)]
        return scene

    @property
    def shots(self) -> list:
        """The visuals that actually play — the ones not switched off."""
        return [v for v in self.visuals if not v.off]

    def rebalance(self):
        """Re-split the scene's length across whatever shots it now plays."""
        playing = self.shots
        for visual, length in zip(playing, share_duration(self.duration, len(playing))):
            visual.duration = length
        for visual in self.visuals:
            if visual.off:
                visual.duration = 0.0
        # the renderer and the library still read clip_path; keeping it aimed at
        # the first shot means nothing breaks while the rest catches up
        first = playing[0] if playing else None
        self.clip_path = first.path if first else ""
        self.clip_source = first.source if first else ""
        self.clip_thumb = first.thumb if first else ""
        self.clip_credit = first.credit if first else ""


@dataclass
class Project:
    id: str = field(default_factory=new_id)
    title: str = "Untitled"
    topic: str = ""
    hook: str = ""                               # the opening line the script is built on
    narrator: str = "neutral"
    language: str = "Russian"
    tone: str = "Conversational"
    scenes: list = field(default_factory=list)   # list[Scene]
    created_at: str = ""
    updated_at: str = ""
    # set when the project was spawned from a video in the ideas base
    source_url: str = ""
    source_video_id: str = ""
    source_title: str = ""
    source_start: float = 0.0
    source_end: float = 0.0
    source_text: str = ""
    # the slice of that video cut out for this project, inside its own folder;
    # the full download is a working file and does not outlive the cutting
    fragment_path: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenes"] = [asdict(s) if isinstance(s, Scene) else s for s in self.scenes]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Project":
        known = {k: v for k, v in d.items() if k in Project.__annotations__}
        known["scenes"] = [Scene.from_dict(s) for s in d.get("scenes", [])]
        return Project(**known)

    @property
    def script_text(self) -> str:
        return "\n\n".join(s.text for s in self.scenes if s.text)
