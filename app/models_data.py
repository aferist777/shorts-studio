"""Plain data objects, JSON-round-trippable."""

import uuid
from dataclasses import dataclass, field, asdict


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Scene:
    """One paragraph of narration and everything derived from it."""

    text: str = ""
    terms: list = field(default_factory=list)   # search keywords for stock footage
    clip_path: str = ""                          # local video used for this scene
    clip_source: str = ""                        # "pexels" | "pixabay" | "local"
    clip_thumb: str = ""                         # cached poster frame for the UI
    clip_credit: str = ""                        # author, for attribution
    audio_path: str = ""
    duration: float = 0.0
    words: list = field(default_factory=list)   # [{"w", "start", "end"}] for karaoke subs
    voice: str = ""                              # voice id the audio was made with

    @staticmethod
    def from_dict(d: dict) -> "Scene":
        return Scene(**{k: v for k, v in d.items() if k in Scene.__annotations__})


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
