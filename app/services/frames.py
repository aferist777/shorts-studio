"""Working out what each scene should show, before anything is drawn.

Three passes, deliberately separate:

  1. shots   — what is in each picture, plainly. One request per scene, on the
               cheap model. Style-free on purpose, so it survives a change of
               style: this is the expensive thinking and it is done once.
  2. details — a bank of small recurring things drawn from the whole script,
               sprinkled into prompts later so the pictures share a world.
  3. style   — turning the above into prompts in a chosen manner. That lives
               elsewhere, because it is the part that gets rewritten often.

The fan-out is per scene rather than one request for the lot. Asking for sixty
descriptions in one answer is how the topic and hook steps in this project first
hit the token ceiling; a beat at a time keeps each context small, lets the model
guarantee variety inside a scene, and means one failure costs one scene instead
of the batch.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.models_data import visual_count
from app.paths import DATA_DIR, project_dir
from app.services import prompts
from app.services.llm import call_json

PROMPTS_SCHEMA = {
    "type": "object",
    "properties": {"prompts": {"type": "array", "items": {"type": "string"}}},
    "required": ["prompts"],
    "additionalProperties": False,
}

SHOTS_MODEL = "google/gemini-3.1-flash-lite"
DETAILS_MODEL = "google/gemini-3.6-flash"
LANES = 6           # how many scenes are analysed at once


def home(project_id: str) -> Path:
    d = project_dir(project_id) / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def base_path(project_id: str) -> Path:
    return home(project_id) / "base.json"


EMPTY_BASE = {"scenes": {}, "details": [], "world": ""}


def load_base(project_id: str) -> dict:
    path = base_path(project_id)
    if not path.exists():
        return dict(EMPTY_BASE)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(EMPTY_BASE)
    return {"scenes": stored.get("scenes", {}),
            "details": stored.get("details", []),
            "world": stored.get("world", "")}


def save_base(project_id: str, base: dict):
    base_path(project_id).write_text(
        json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")


def shots_wanted(scene) -> int:
    """How many pictures a scene gets — the same rule the timeline already uses."""
    return visual_count(scene.duration)


# ---- pass zero: where and when any of this happens ---------------------------
# The project knows it is about the USSR — it says so in the topic and twice in
# the script — but none of that ever reached the pass that writes the image
# prompt, which saw "an elderly man in a suit at a wooden podium" and drew an
# American one. Read once, kept as plain text so it can be corrected by hand,
# and carried into every pass after it.

WORLD_MODEL = "google/gemini-3.6-flash"


def read_world(project) -> str:
    """Where and when this video happens, as a block a person can edit."""
    script = "\n\n".join(s.text for s in project.scenes if s.text)
    if not (script.strip() or project.topic.strip()):
        raise RuntimeError("There is nothing to read the world from.")

    data = call_json("openrouter", WORLD_MODEL, "low",
                     prompts.WORLD_SYSTEM,
                     prompts.world_user_prompt(project.topic, script,
                                               project.source_text),
                     prompts.WORLD_SCHEMA)
    lines = []
    for field in prompts.WORLD_FIELDS:
        value = (data.get(field) or "").strip()
        if value:
            lines.append(f"{field}: {value}")
    if not lines:
        raise RuntimeError("The world pass came back empty.")
    return "\n".join(lines)


def world_block(world: str) -> str:
    """How the world is handed to a pass that has to draw inside it."""
    world = (world or "").strip()
    if not world:
        return ""
    return ("THE WORLD THIS HAPPENS IN — the setting unless a picture plainly "
            "says otherwise:\n" + world)


# ---- pass one: what is in the pictures --------------------------------------

def analyse_scene(beat: str, count: int, topic: str = "", world: str = "") -> list:
    """-> [{'subject','action','place','framing'}] for one beat."""
    user = prompts.shots_user_prompt(beat, count, topic)
    block = world_block(world)
    if block:
        user = f"{block}\n\n{user}"
    data = call_json("openrouter", SHOTS_MODEL, "low",
                     prompts.SHOTS_SYSTEM, user,
                     prompts.SHOTS_SCHEMA)
    shots = []
    for shot in data.get("shots", []):
        subject = (shot.get("subject") or "").strip()
        if not subject or subject.lower() in ("none", "n/a", "nobody"):
            # the instruction says a frame may lack a hero but never a subject;
            # a model that answers "none" anyway would put that word in a prompt
            subject = "the place itself, busy with signs and clutter"
        shots.append({"subject": subject,
                      "action": (shot.get("action") or "").strip(),
                      "place": (shot.get("place") or "").strip(),
                      "framing": (shot.get("framing") or "wide").strip()})
    if not shots:
        raise RuntimeError("The model returned no pictures for this beat.")
    return shots[:count]


def analyse_project(project, world: str = "", progress=None) -> dict:
    """Every scene at once, six lanes wide. -> {'scenes': {...}, 'failed': [...]}

    A scene that fails is named rather than swallowed: it can be redone on its
    own without touching the ones that worked.
    """
    scenes = list(enumerate(project.scenes))
    done, failed = {}, []
    finished = 0

    def one(pair):
        index, scene = pair
        if not (scene.text or "").strip():
            return index, None, "no text"
        try:
            return index, analyse_scene(scene.text, shots_wanted(scene),
                                        project.topic, world), ""
        except Exception as e:
            return index, None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=LANES) as lanes:
        for index, shots, error in lanes.map(one, scenes):
            finished += 1
            if progress:
                progress(f"Reading scene {finished}/{len(scenes)}")
            if shots:
                done[str(index)] = shots
            else:
                failed.append({"scene": index, "why": error})

    return {"scenes": done, "failed": failed}


# ---- pass two: the bank of small things -------------------------------------

PER_PICTURE = 10        # how many are offered to any one prompt to choose from
# The bank has to outnumber the pictures, or the same joke comes round every
# other frame: forty of them across fifty-one pictures was a tic, not a thread.
DETAILS_PER_PICTURE = 2.5
DETAIL_MIN, DETAIL_MAX = 40, 160
DETAILS_BATCH = 40      # how many to ask for in one request


def details_wanted(project) -> int:
    """How big this project's bank should be, from how many pictures it will draw."""
    pictures = sum(visual_count(s.duration) for s in project.scenes)
    return max(DETAIL_MIN, min(DETAIL_MAX,
                               round((pictures or len(project.scenes)) * DETAILS_PER_PICTURE)))


def build_details(project, count: int = 0, world: str = "", progress=None) -> list:
    """Background jokes for this video's world. -> [{'kind','detail'}]

    One request over the whole narration rather than one per scene: recurring
    motifs only show up if the model sees the story end to end. And because
    they carry no style, the bank survives a change of it — the same rat in a
    uniform can be drawn as a caricature or as an engraving.
    """
    script = "\n\n".join(s.text for s in project.scenes if s.text)
    if not script.strip():
        raise RuntimeError("There is no narration to draw jokes from.")
    count = count or details_wanted(project)

    # Asked for in batches: a hundred and twenty of them in one answer runs past
    # the token budget and comes back as unclosed JSON. Separate calls also
    # wander further apart than one list would, which is what a bank wants.
    batches = [min(DETAILS_BATCH, count - i)
               for i in range(0, count, DETAILS_BATCH)]
    if progress:
        progress(f"Inventing {count} background jokes")

    block = world_block(world)

    def one(size):
        user = prompts.details_user_prompt(script, project.topic, size)
        return call_json("openrouter", DETAILS_MODEL, "low",
                         prompts.DETAILS_SYSTEM,
                         f"{block}\n\n{user}" if block else user,
                         prompts.DETAILS_SCHEMA)

    seen, out = set(), []
    with ThreadPoolExecutor(max_workers=min(LANES, len(batches))) as lanes:
        for data in lanes.map(one, batches):
            for item in data.get("details", []):
                phrase = (item.get("detail") or "").strip()
                if not phrase or phrase.lower() in seen:
                    continue
                seen.add(phrase.lower())
                scale = (item.get("scale") or "small").strip().lower()
                out.append({"kind": (item.get("kind") or "object").strip().lower(),
                            "detail": phrase,
                            "scale": "big" if scale.startswith("b") else "small"})
    if not out:
        raise RuntimeError("No usable background jokes came back.")
    return out


BIG_PER_PICTURE = 3     # of PER_PICTURE; the rest are edge business


def _spread(pool: list, how_many: int) -> list:
    """Take `how_many`, never several of one kind in a row."""
    import random

    by_kind = {}
    for item in pool:
        by_kind.setdefault(item["kind"], []).append(item)
    for group in by_kind.values():
        random.shuffle(group)

    chosen, kinds = [], list(by_kind)
    random.shuffle(kinds)
    while len(chosen) < how_many and any(by_kind.values()):
        for kind in kinds:
            if by_kind[kind] and len(chosen) < how_many:
                chosen.append(by_kind[kind].pop())
    return chosen


def sprinkle(details: list, taken: set, how_many: int = PER_PICTURE) -> list:
    """A handful for one picture, spread across kinds and unused in this scene.

    Picking blind would hand the same joke to two neighbouring frames, which
    turns a running thread into a tic; `taken` is what the scene has used
    already.

    Big and small are drawn separately so every picture is offered both: a
    frame with nothing but corner business has nothing to catch the eye on a
    first watch, and one with nothing but middle-ground events has no reward
    for a second.
    """
    fresh = [d for d in details if d["detail"] not in taken] or list(details)
    big = [d for d in fresh if d.get("scale") == "big"]
    small = [d for d in fresh if d.get("scale") != "big"]

    want_big = min(BIG_PER_PICTURE, how_many)
    chosen = _spread(big, want_big)
    chosen += _spread(small, how_many - len(chosen))
    # a bank with no big ones at all (anything written before scale existed)
    if len(chosen) < how_many:
        chosen += _spread([d for d in fresh if d not in chosen],
                          how_many - len(chosen))
    return chosen


# ---- the styles themselves --------------------------------------------------
# Kept as plain files rather than in code: this is the text the user rewrites
# most, and every rewrite going through a developer would make the whole idea
# somebody else's.

STYLES_DIR = DATA_DIR / "styles"


def style_names() -> list:
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in STYLES_DIR.glob("*.txt"))


def load_style(name: str) -> str:
    path = STYLES_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_style(name: str, text: str):
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    (STYLES_DIR / f"{name}.txt").write_text(text, encoding="utf-8")


# ---- pass three: the same pictures, in a manner ------------------------------

def style_dir(project_id: str, style: str) -> Path:
    d = home(project_id) / style
    d.mkdir(parents=True, exist_ok=True)
    return d


def stylize_scene(shots: list, details: list, style_text: str,
                  taken: set = None, world: str = "") -> list:
    """One scene's pictures turned into prompts. -> [str]"""
    taken = taken if taken is not None else set()
    block = world_block(world)
    lines = [block] if block else []
    for i, shot in enumerate(shots, 1):
        picked = sprinkle(details, taken, PER_PICTURE) if details else []
        for item in picked:
            taken.add(item["detail"])
        block = [f"PICTURE {i}",
                 f"framing: {shot['framing']}",
                 f"subject: {shot['subject']}",
                 f"action: {shot['action']}",
                 f"place: {shot['place']}"]
        # handed over already sorted by how large each should be drawn, so the
        # layering is a fact of the brief rather than a hope in the manner
        big = [d["detail"] for d in picked if d.get("scale") == "big"]
        small = [d["detail"] for d in picked if d.get("scale") != "big"]
        if big:
            block.append("middle-ground events, drawn big enough to catch at a "
                         "glance: " + "; ".join(big))
        if small:
            block.append("small business for the edges and corners: "
                         + "; ".join(small))
        lines.append("\n".join(block))

    # eight pictures of a hundred and sixty words each, plus whatever the model
    # spends thinking — three thousand was written for prompts half this length
    data = call_json("openrouter", DETAILS_MODEL, "low", style_text,
                     "\n\n".join(lines)
                     + f"\n\nWrite {len(shots)} prompts, one per picture, in order.",
                     PROMPTS_SCHEMA)

    out = [(p or "").strip() for p in data.get("prompts", []) if (p or "").strip()]
    if not out:
        raise RuntimeError("The style pass returned no prompts.")
    return out[:len(shots)]


def stylize_project(project, style: str, progress=None) -> dict:
    """Every scene through the style, six lanes wide."""
    base = load_base(project.id)
    style_text = load_style(style)
    if not style_text:
        raise RuntimeError(f"No style called “{style}” — add it in the styles folder.")
    if not base["scenes"]:
        raise RuntimeError("Read the scenes first.")

    numbers = sorted(base["scenes"], key=int)
    done, failed, finished = {}, [], 0

    def one(key):
        # each scene keeps its own used-details set, so a joke can come back
        # later in the video but never twice in the same breath
        try:
            return key, stylize_scene(base["scenes"][key], base["details"],
                                      style_text, set(), base["world"]), ""
        except Exception as e:
            return key, None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=LANES) as lanes:
        for key, prompts_out, error in lanes.map(one, numbers):
            finished += 1
            if progress:
                progress(f"Styling scene {finished}/{len(numbers)}")
            if prompts_out:
                done[key] = prompts_out
            else:
                failed.append({"scene": int(key), "why": error})

    payload = {"style": style, "prompts": done, "failed": failed}
    (style_dir(project.id, style) / "prompts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


# ---- the poster --------------------------------------------------------------
# What the rest of the pictures are drawn to match. It used to be the first frame
# of the first scene, which handed every other frame that scene's subject as well
# as its manner — fifty pictures quietly inherited an orator at a podium. A poster
# carries no scene at all: only the jokes, the world and the manner.
#
# Two of them come out of one brief. The one with the title is for looking at; the
# one without is what goes to the model, because a sample with large lettering
# across the middle teaches every frame to put lettering across the middle.

POSTER_JOKES = 12


def poster_prompts(project, style: str, world: str = "", details: list = None) -> dict:
    """One call, two prompts for the same picture. -> {'titled','plain'}"""
    style_text = load_style(style)
    if not style_text:
        raise RuntimeError(f"No style called “{style}”.")

    bank = details if details is not None else load_base(project.id)["details"]
    big = [d["detail"] for d in bank if d.get("scale") == "big"] or \
          [d["detail"] for d in bank]
    if not big:
        raise RuntimeError("There are no background jokes to build a poster from.")

    import random
    picked = random.sample(big, min(POSTER_JOKES, len(big)))

    data = call_json("openrouter", DETAILS_MODEL, "low", style_text,
                     prompts.poster_user_prompt(project.title, project.language,
                                                picked, world_block(world)),
                     prompts.POSTER_SCHEMA)
    titled = (data.get("titled") or "").strip()
    plain = (data.get("plain") or "").strip()
    if not (titled and plain):
        raise RuntimeError("The poster pass came back with only one version.")
    return {"titled": titled, "plain": plain}


def poster_path(project_id: str, style: str, kind: str) -> Path:
    return style_dir(project_id, style) / f"poster_{kind}.png"


def poster_meta_path(project_id: str, style: str) -> Path:
    return style_dir(project_id, style) / "poster.json"


def load_poster_meta(project_id: str, style: str) -> dict:
    path = poster_meta_path(project_id, style)
    if not path.exists():
        return {"prompts": {}, "urls": {}, "hosted": ""}
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"prompts": {}, "urls": {}, "hosted": ""}
    # the first version of this file held the two prompts and nothing else
    written = stored.get("prompts")
    if written is None:
        written = {k: stored[k] for k in ("titled", "plain") if k in stored}
    return {"prompts": written or {},
            "urls": stored.get("urls", {}),
            "hosted": stored.get("hosted", "")}


def save_poster_meta(project_id: str, style: str, meta: dict):
    poster_meta_path(project_id, style).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# One thread does the checking and, if it comes to it, the uploading. Four
# lanes all deciding at once that the link is dead would send the same eleven
# megabytes four times and race each other writing the cache.
_LINK_LOCK = threading.Lock()


def reference_link(project_id: str, style: str, progress=None) -> str:
    """A URL the model can fetch the sample from.

    kie keeps what it draws for about a day, which outlives most projects and
    costs nothing — so its own link is tried first. When that has expired the
    poster goes to imgbb, which keeps it for a month, and that link is written
    down and used from then on.
    """
    from app.services import kie_images

    with _LINK_LOCK:
        meta = load_poster_meta(project_id, style)
        for key in ("hosted", "plain", "titled"):
            link = meta["hosted"] if key == "hosted" else meta["urls"].get(key, "")
            if link and kie_images.alive(link):
                return link

        plain = poster_path(project_id, style, "plain")
        sample = plain if plain.exists() else poster_path(project_id, style, "titled")
        if not sample.exists():
            return ""
        if progress:
            progress("The sample's link has expired — hosting it")
        meta["hosted"] = kie_images.host(str(sample))
        save_poster_meta(project_id, style, meta)
        return meta["hosted"]


def posters_so_far(project_id: str, style: str) -> dict:
    """Which of the two exist. -> {'titled': path|'', 'plain': path|''}"""
    out = {}
    for kind in ("titled", "plain"):
        path = poster_path(project_id, style, kind)
        out[kind] = str(path) if path.exists() else ""
    return out


def draw_poster(project, style: str, world: str = "", model: str = "",
                aspect: str = "9:16", resolution: str = "1K",
                progress=None) -> dict:
    """Write the pair, then draw them side by side. -> {'titled','plain','prompts'}"""
    from app.services import kie_images

    if progress:
        progress("Writing the poster")
    pair = poster_prompts(project, style, world)
    # written down before anything is drawn: if the drawing falls over, the
    # words it cost three cents to write are still here
    save_poster_meta(project.id, style, {"prompts": pair, "urls": {}, "hosted": ""})

    def one(kind):
        try:
            made = kie_images.generate_to(
                str(poster_path(project.id, style, kind)),
                model or kie_images.DEFAULT_MODEL, pair[kind], aspect,
                resolution, label=f"poster · {kind}")
            return kind, made["path"], made["url"], ""
        except Exception as e:
            return kind, "", "", str(e)[:140]

    if progress:
        progress("Drawing both posters")
    made, urls, failed = {}, {}, []
    # two at once: they are the same picture and there is nothing to wait for
    with ThreadPoolExecutor(max_workers=2) as lanes:
        for kind, path, url, error in lanes.map(one, ("titled", "plain")):
            if path:
                made[kind] = path
                # kept because kie serves what it drew for about a day: while
                # that lasts the sample needs no uploading anywhere
                urls[kind] = url
            else:
                failed.append(f"{kind}: {error}")
    if not made:
        raise RuntimeError("Neither poster came back — " + "; ".join(failed))
    save_poster_meta(project.id, style,
                     {"prompts": pair, "urls": urls, "hosted": ""})
    return {"titled": made.get("titled", ""), "plain": made.get("plain", ""),
            "prompts": pair, "failed": failed}


# ---- pass four: the pictures themselves --------------------------------------
# The first one is drawn alone and shown for approval. Everything after it is
# drawn with that picture in hand, because forty images generated independently
# in the same described manner still drift apart — a sample holds the palette
# and the weight of line in a way words cannot.

IMAGE_LANES = 4         # kie is fine with this and it keeps a failure cheap


def picture_path(project_id: str, style: str, scene: str, index: int) -> Path:
    return style_dir(project_id, style) / f"scene_{int(scene) + 1:02d}_{index + 1}.png"


def save_prompts(project_id: str, style: str, by_scene: dict):
    """Put back one scene's rewrite without disturbing the others."""
    path = style_dir(project_id, style) / "prompts.json"
    payload = {"style": style, "prompts": by_scene, "failed": []}
    if path.exists():
        try:
            payload["failed"] = json.loads(
                path.read_text(encoding="utf-8")).get("failed", [])
        except Exception:
            pass
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def load_prompts(project_id: str, style: str) -> dict:
    path = style_dir(project_id, style) / "prompts.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("prompts", {})
    except Exception:
        return {}


def draw_one(project_id: str, style: str, scene: str, index: int, model: str,
             aspect: str = "9:16", resolution: str = "1K",
             reference: str = "", reference_url: str = "", progress=None) -> str:
    """One picture from its prompt. -> the path it landed at."""
    from app.services import kie_images

    prompts_by_scene = load_prompts(project_id, style)
    shots = prompts_by_scene.get(str(scene), [])
    if index >= len(shots):
        raise RuntimeError("No prompt for that picture — run Stylize first.")

    dest = str(picture_path(project_id, style, scene, index))
    made = kie_images.generate_to(dest, model, shots[index], aspect, resolution,
                                  reference, reference_url,
                                  f"scene {int(scene) + 1}, picture {index + 1}",
                                  progress)
    return made["path"]


def draw_slot_job(project_id: str, style: str, scene: int, index: int, model: str,
                  aspect: str = "9:16", resolution: str = "1K",
                  reference: str = "", reference_url: str = "",
                  progress=None) -> dict:
    """draw_one, but the answer says which slot it belongs to.

    Which picture came back cannot be closed over in the callback — a callback
    that is not a bound method runs on the worker thread. So it travels in the
    result, and a failure comes back the same way rather than as an exception,
    so one slot breaking is not mistaken for the window breaking.
    """
    out = {"scene": int(scene), "index": int(index), "path": "", "error": ""}
    try:
        link = reference_url or reference_link(project_id, style, progress)
        out["path"] = draw_one(project_id, style, str(scene), index, model,
                               aspect, resolution, reference, link, progress)
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def draw_rest(project, style: str, sample: str, model: str,
              aspect: str = "9:16", resolution: str = "1K",
              progress=None) -> dict:
    """Everything that has no picture yet, following the approved sample.

    `sample` is kept in the signature for a caller that has a file and no link
    of its own; normally the link comes from the poster and nothing is uploaded.
    """
    from app.services import kie_images

    prompts_by_scene = load_prompts(project.id, style)
    wanted = [(scene, i) for scene in sorted(prompts_by_scene, key=int)
              for i in range(len(prompts_by_scene[scene]))
              if not picture_path(project.id, style, scene, i).exists()]
    if not wanted:
        return {"drawn": [], "failed": []}

    if progress:
        progress("Finding the sample")
    link = reference_link(project.id, style, progress)
    if not link and sample:
        link = kie_images.host(sample)

    drawn, failed, finished = [], [], 0

    def one(pair):
        scene, index = pair
        try:
            return pair, draw_one(project.id, style, scene, index, model,
                                  aspect, resolution, "", link), ""
        except Exception as e:
            return pair, "", str(e)[:120]

    with ThreadPoolExecutor(max_workers=IMAGE_LANES) as lanes:
        for pair, path, error in lanes.map(one, wanted):
            finished += 1
            if progress:
                progress(f"Drawing {finished}/{len(wanted)}")
            if path:
                drawn.append({"scene": int(pair[0]), "index": pair[1], "path": path})
            else:
                failed.append({"scene": int(pair[0]), "index": pair[1], "why": error})

    return {"drawn": drawn, "failed": failed}


def drawn_so_far(project_id: str, style: str) -> list:
    """Every picture that exists for this style, in playing order."""
    prompts_by_scene = load_prompts(project_id, style)
    out = []
    for scene in sorted(prompts_by_scene, key=int):
        for i in range(len(prompts_by_scene[scene])):
            path = picture_path(project_id, style, scene, i)
            if path.exists():
                out.append({"scene": int(scene), "index": i, "path": str(path)})
    return out


# ---- pass five: putting them on the timeline ---------------------------------

def place_in_scenes(project, style: str, replace: bool = True) -> dict:
    """Hand every drawn picture to the scene it was drawn for.

    Nothing has to be guessed: a picture was invented from one beat and its
    filename carries that beat's number, which is what separates this from the
    pool that Cut and Find fill — those hold material with no home yet.

    Replacing is the default because a generated set is an alternative to
    hand-picked footage, not an addition to it. Appending is there for the case
    where the two are being mixed on purpose.
    """
    from app.models_data import Visual

    have = drawn_so_far(project.id, style)
    if not have:
        return {"scenes": 0, "pictures": 0}

    by_scene = {}
    for picture in have:
        by_scene.setdefault(picture["scene"], []).append(picture)

    touched = 0
    for index, pictures in sorted(by_scene.items()):
        if index >= len(project.scenes):
            continue
        scene = project.scenes[index]
        made = [Visual(path=p["path"], kind="still", source=f"drawn:{style}",
                       thumb=p["path"])
                for p in sorted(pictures, key=lambda x: x["index"])]
        scene.visuals = made if replace else list(scene.visuals) + made
        scene.rebalance()
        touched += 1

    return {"scenes": touched, "pictures": len(have)}


def redo_scene(project, index: int) -> list:
    """One scene again, for when it failed or came back wrong."""
    scene = project.scenes[index]
    return analyse_scene(scene.text, shots_wanted(scene), project.topic,
                         load_base(project.id)["world"])
