"""The footage a project has gathered, before any of it is used.

Pieces cut out of the fragment and frames saved from it land here, and later so
will anything pulled from the open archives. A scene draws from this pool
rather than going off to search on its own — gather first, distribute after.
"""

import json
from pathlib import Path

from app.paths import project_dir

CLIP_KINDS = {".mp4", ".mov", ".webm", ".mkv"}
STILL_KINDS = {".jpg", ".jpeg", ".png", ".webp"}


def folder(project_id: str) -> Path:
    d = project_dir(project_id) / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def items(project_id: str) -> list:
    """Everything gathered for this project. -> [{'path','kind','thumb','name'}]"""
    home = folder(project_id)
    thumbs = home / "thumbs"
    out = []
    for path in sorted(home.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in CLIP_KINDS:
            kind = "clip"
        elif suffix in STILL_KINDS:
            kind = "still"
        else:
            continue
        # a still is its own thumbnail; a clip had one made when it was kept
        poster = str(path) if kind == "still" else ""
        made = thumbs / f"{path.stem}.jpg"
        if made.exists():
            poster = str(made)
        out.append({"path": str(path), "kind": kind, "thumb": poster,
                    "name": path.name})
    return out


# ---- who has to be named ---------------------------------------------------
# Written when the archive search still existed and pictures arrived under a
# licence that asked for a name. Nothing records a credit any more — drawn
# pictures owe nobody — but a project made back then still has its file, and a
# render of it should still carry the names it promised.

CREDITS = "credits.json"


def _credit_file(project_id: str) -> Path:
    return folder(project_id) / CREDITS


def load_credits(project_id: str) -> dict:
    path = _credit_file(project_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_credits(project, dest: str) -> str:
    """List the authors of everything this video actually shows.

    Only what ended up in a scene: pictures gathered and then not used owe
    nobody anything.
    """
    owed = load_credits(project.id)
    if not owed:
        return ""
    used = [owed[Path(v.path).name] for scene in project.scenes for v in scene.visuals
            if Path(v.path).name in owed]
    if not used:
        return ""

    lines = ["Images used in this video", ""]
    lines += [f"- {line}" for line in dict.fromkeys(used)]
    Path(dest).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def used_paths(project) -> set:
    """What is already standing in some scene, so the picker can say so."""
    return {v.path for scene in project.scenes for v in scene.visuals}
