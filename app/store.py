"""Project persistence — one JSON index, media under data/projects/<id>/."""

import json
from datetime import datetime, timezone

from app.models_data import Project, Scene
from app.paths import DATA_DIR

INDEX_PATH = DATA_DIR / "projects.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self):
        self.projects: list = []
        self.load()

    def load(self):
        if not INDEX_PATH.exists():
            self.projects = []
            return
        try:
            raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            self.projects = [Project.from_dict(p) for p in raw.get("projects", [])]
        except Exception:
            self.projects = []

    def save(self):
        payload = {"projects": [p.to_dict() for p in self.projects]}
        INDEX_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def create(self, title: str = "Untitled", topic: str = "") -> Project:
        p = Project(title=title, topic=topic, created_at=_now(), updated_at=_now())
        self.projects.insert(0, p)
        self.save()
        return p

    def touch(self, project: Project):
        project.updated_at = _now()
        self.save()

    def create_from_topic(self, video: dict, topic: dict, language: str = "Russian",
                          tone: str = "Conversational") -> Project:
        """A project born out of one topic in an analysed video.

        `topic` is the title, so the existing topic-driven script generation works
        straight away; the transcript slice sits alongside for later phases.
        """
        project = Project(
            title=topic.get("project_name") or topic.get("title", "Untitled"),
            topic=topic.get("title", ""),
            language=language,
            tone=tone,
            created_at=_now(),
            updated_at=_now(),
            source_url=video.get("url", ""),
            source_video_id=video.get("video_id", ""),
            source_title=video.get("title", ""),
            source_start=float(topic.get("start", 0)),
            source_end=float(topic.get("end", 0)),
            source_text=topic.get("text", ""),
        )
        self.projects.insert(0, project)
        self.save()
        return project

    def duplicate(self, project_id: str) -> Project:
        """Copy the script, drop the media.

        The point of a duplicate is to redo the same script with a different
        voice, footage or subtitle style — carrying the old audio and clips over
        would defeat that.
        """
        source = self.get(project_id)
        if source is None:
            raise ValueError(f"No such project: {project_id}")
        copy = Project(
            title=f"{source.title} (copy)",
            topic=source.topic,
            language=source.language,
            tone=source.tone,
            scenes=[Scene(text=s.text, terms=list(s.terms)) for s in source.scenes],
            created_at=_now(),
            updated_at=_now(),
        )
        self.projects.insert(0, copy)
        self.save()
        return copy

    def delete(self, project_id: str):
        self.projects = [p for p in self.projects if p.id != project_id]
        self.save()

    def get(self, project_id: str):
        return next((p for p in self.projects if p.id == project_id), None)
