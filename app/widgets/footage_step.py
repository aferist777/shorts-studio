"""Footage step — one clip per scene, chosen from stock or your own folder.

Thumbnails only: the full clip is never played here, it just gets attached to
the scene and shown as a poster frame.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.paths import project_dir
from app.services import footage
from app.services.footage import local
from app.services.worker import run_async
from app.widgets.clip_picker import ClipPicker

THUMB_W, THUMB_H = 45, 80


def _autofill(scenes: list, sources: list, out_dir: str, local_folder: str,
              progress=None) -> list:
    """One clip per scene, top-ranked match, downloaded. Returns per-scene dicts."""
    pool = []
    if local_folder:
        if progress:
            progress("Scanning local folder")
        pool = local.scan(local_folder, progress=progress)

    used, out = set(), []
    for i, scene in enumerate(scenes):
        if progress:
            progress(f"Scene {i + 1} of {len(scenes)}")
        candidates = footage.rank(pool, scene["duration"]) if pool else footage.search(
            scene["terms"], sources, min_duration=scene["duration"]
        )
        # don't repeat a clip inside one video
        fresh = [c for c in candidates if (c["source"], c["id"]) not in used]
        if not fresh:
            out.append(None)
            continue
        chosen = fresh[0]
        used.add((chosen["source"], chosen["id"]))
        dest = str(Path(out_dir) / f"clip_{i + 1:02d}.mp4")
        footage.download(chosen, dest, progress=progress)
        out.append({
            "index": i,
            "path": dest,
            "source": chosen["source"],
            "thumb": footage.thumbnail(chosen),
            "credit": chosen["credit"],
        })
    return out


def _search_for_scene(terms: list, sources: list, min_duration: float,
                      local_folder: str, progress=None) -> list:
    if local_folder:
        return footage.rank(local.scan(local_folder, progress=progress), min_duration)
    return footage.search(terms, sources, min_duration=min_duration, progress=progress)


def _download_one(candidate: dict, dest: str, progress=None) -> dict:
    path = footage.download(candidate, dest, progress=progress)
    return {
        "path": path,
        "source": candidate["source"],
        "thumb": footage.thumbnail(candidate),
        "credit": candidate["credit"],
    }


class SceneClipRow(QFrame):
    pickRequested = Signal(int)

    def __init__(self, index: int, scene):
        super().__init__()
        self.setObjectName("SceneCard")
        self.index = index
        self.scene = scene

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        self.thumb = QLabel()
        self.thumb.setObjectName("ClipThumb")
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)

        middle = QVBoxLayout()
        middle.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        num = QLabel(f"SCENE {index + 1}")
        num.setObjectName("SceneNum")
        self.credit = QLabel()
        self.credit.setObjectName("ProjMeta")
        top.addWidget(num)
        top.addWidget(self.credit)
        top.addStretch(1)
        middle.addLayout(top)

        self.chips = QHBoxLayout()
        self.chips.setSpacing(5)
        self.chips.addStretch(1)
        middle.addLayout(self.chips)

        self.length = QLabel()
        self.length.setObjectName("Chip")
        self.length.setFixedWidth(52)
        self.length.setAlignment(Qt.AlignCenter)

        self.pick = QPushButton("Pick…")
        self.pick.setCursor(Qt.PointingHandCursor)
        self.pick.clicked.connect(lambda: self.pickRequested.emit(self.index))

        lay.addWidget(self.thumb)
        lay.addLayout(middle, 1)
        lay.addWidget(self.length, 0, Qt.AlignVCenter)   # chips must not stretch to row height
        lay.addWidget(self.pick, 0, Qt.AlignVCenter)

        self.refresh()

    def refresh(self):
        has_clip = bool(self.scene.clip_path) and Path(self.scene.clip_path).exists()
        pixmap = QPixmap(self.scene.clip_thumb) if self.scene.clip_thumb else QPixmap()
        if has_clip and not pixmap.isNull():
            self.thumb.setPixmap(pixmap.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatioByExpanding,
                                               Qt.SmoothTransformation))
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("—")
        self.credit.setText(
            f"{self.scene.clip_source} · {self.scene.clip_credit}" if has_clip else "no clip yet"
        )
        self.length.setText(f"{self.scene.duration:.1f}s" if self.scene.duration else "—")

        while self.chips.count() > 1:
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for term in self.scene.terms[:3]:
            chip = QLabel(term)
            chip.setObjectName("Chip")
            self.chips.insertWidget(self.chips.count() - 1, chip)

    def set_locked(self, locked: bool):
        self.pick.setEnabled(not locked)


class FootageStep(QWidget):
    projectChanged = Signal()
    log = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.project = None
        self._rows = []
        self._elapsed = 0
        self._message = ""
        self._pick_index = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        cap = QLabel("SOURCES")
        cap.setObjectName("FieldLabel")
        controls.addWidget(cap)

        self.source_boxes = {}
        for sid, label in footage.SOURCES.items():
            box = QCheckBox(label)
            box.setChecked(sid in settings.get("footage_sources", []))
            box.stateChanged.connect(self._persist)
            controls.addWidget(box)
            self.source_boxes[sid] = box

        self.use_local = QCheckBox("Local folder")
        self.use_local.setChecked(bool(settings.get("local_folder")))
        self.use_local.stateChanged.connect(self._on_local_toggled)
        controls.addWidget(self.use_local)

        self.folder_btn = QPushButton("Browse…")
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.clicked.connect(self._browse_folder)
        controls.addWidget(self.folder_btn)

        controls.addStretch(1)
        self.autofill_btn = QPushButton("Fill all scenes")
        self.autofill_btn.setObjectName("Primary")
        self.autofill_btn.setCursor(Qt.PointingHandCursor)
        self.autofill_btn.clicked.connect(self.autofill)
        controls.addWidget(self.autofill_btn)
        root.addLayout(controls)

        self.folder_label = QLabel()
        self.folder_label.setObjectName("Hint")
        root.addWidget(self.folder_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        status_row.addWidget(self.progress, 1)
        status_row.addWidget(self.status)
        root.addLayout(status_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.row_layout = QVBoxLayout(holder)
        self.row_layout.setContentsMargins(0, 2, 6, 2)
        self.row_layout.setSpacing(6)
        self.row_layout.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

        self.placeholder = QLabel("Write a script first — footage is picked per scene.")
        self.placeholder.setObjectName("Hint")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.row_layout.insertWidget(0, self.placeholder)

        self.total = QLabel("")
        self.total.setObjectName("Hint")
        self.total.setAlignment(Qt.AlignRight)
        root.addWidget(self.total)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._on_local_toggled()

    # ---- settings ----------------------------------------------------------

    def _persist(self):
        self.settings["footage_sources"] = [
            sid for sid, box in self.source_boxes.items() if box.isChecked()
        ]
        if not self.use_local.isChecked():
            self.settings["local_folder"] = ""
        from app.config import save_settings
        save_settings(self.settings)

    def _on_local_toggled(self):
        on = self.use_local.isChecked()
        self.folder_btn.setEnabled(on)
        for box in self.source_boxes.values():
            box.setEnabled(not on)  # a local folder replaces the stock search
        folder = self.settings.get("local_folder", "")
        self.folder_label.setText(f"Using {folder}" if on and folder else "")
        self.folder_label.setVisible(bool(on and folder))
        self._persist()

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with your clips",
                                                  self.settings.get("local_folder", ""))
        if folder:
            self.settings["local_folder"] = folder
            self.use_local.setChecked(True)
            self._on_local_toggled()

    def _local_folder(self) -> str:
        return self.settings.get("local_folder", "") if self.use_local.isChecked() else ""

    def _sources(self) -> list:
        return [sid for sid, box in self.source_boxes.items() if box.isChecked()]

    # ---- project binding ---------------------------------------------------

    def set_project(self, project):
        self.project = project
        self._rebuild_rows()

    def _rebuild_rows(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        scenes = self.project.scenes if self.project else []
        self.placeholder.setVisible(not scenes)
        for i, scene in enumerate(scenes):
            row = SceneClipRow(i, scene)
            row.pickRequested.connect(self.pick_for_scene)
            self.row_layout.insertWidget(i + 1, row)
            self._rows.append(row)
        self._update_total()

    def _update_total(self):
        scenes = self.project.scenes if self.project else []
        filled = [s for s in scenes if s.clip_path and Path(s.clip_path).exists()]
        self.total.setText(f"{len(filled)}/{len(scenes)} scenes have footage" if scenes else "")

    # ---- lock / progress ---------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        self.autofill_btn.setEnabled(not busy)
        self.use_local.setEnabled(not busy)
        self.folder_btn.setEnabled(not busy and self.use_local.isChecked())
        for box in self.source_boxes.values():
            box.setEnabled(not busy and not self.use_local.isChecked())
        for row in self._rows:
            row.set_locked(busy)
        if busy:
            self._elapsed = 0
            self._message = message
            self.status.setText(f"{message} · 0s")
            self._timer.start()
        else:
            self._timer.stop()
            self.status.setText("")

    def _tick(self):
        self._elapsed += 1
        self.status.setText(f"{self._message} · {self._elapsed}s")

    def _on_progress(self, label: str):
        self._message = label
        self.status.setText(f"{label} · {self._elapsed}s")

    def _fail(self, message: str):
        self._set_busy(False)
        self.status.setText("Failed — see log")
        self.log.emit(f"ERROR  {message}")

    # ---- fill all ----------------------------------------------------------

    def autofill(self):
        if not self.project or not self.project.scenes:
            return
        if not self._sources() and not self._local_folder():
            self.log.emit("Pick at least one source.")
            return

        self._set_busy(True, "Finding footage")
        self.log.emit(f"Footage · {', '.join(self._sources()) or 'local folder'}")
        run_async(
            self, _autofill, self._on_autofill, self._fail,
            [{"terms": s.terms, "duration": s.duration} for s in self.project.scenes],
            self._sources(), str(project_dir(self.project.id)), self._local_folder(),
            on_progress=self._on_progress,
        )

    def _on_autofill(self, results: list):
        filled = 0
        for result in results:
            if not result:
                continue
            scene = self.project.scenes[result["index"]]
            scene.clip_path = result["path"]
            scene.clip_source = result["source"]
            scene.clip_thumb = result["thumb"]
            scene.clip_credit = result["credit"]
            filled += 1
        for row in self._rows:
            row.refresh()
        self._set_busy(False)
        self._update_total()
        self.projectChanged.emit()
        missing = len(results) - filled
        note = f" · {missing} scene(s) found nothing" if missing else ""
        self.log.emit(f"Footage attached to {filled} scenes{note}")

    # ---- pick one ----------------------------------------------------------

    def pick_for_scene(self, index: int):
        if not self.project:
            return
        scene = self.project.scenes[index]
        if not scene.terms and not self._local_folder():
            self.log.emit(f"Scene {index + 1} has no keywords to search with.")
            return

        self._pick_index = index
        self._set_busy(True, f"Searching for scene {index + 1}")
        run_async(
            self, _search_for_scene, self._on_candidates, self._fail,
            scene.terms, self._sources(), scene.duration, self._local_folder(),
            on_progress=self._on_progress,
        )

    def _on_candidates(self, candidates: list):
        self._set_busy(False)
        index = self._pick_index
        if not candidates:
            self.log.emit(f"Nothing found for scene {index + 1}.")
            return

        scene = self.project.scenes[index]
        picker = ClipPicker(candidates, f"Scene {index + 1} · {', '.join(scene.terms[:3])}", self)
        if not picker.exec() or not picker.selected:
            return

        dest = str(project_dir(self.project.id) / f"clip_{index + 1:02d}.mp4")
        self._set_busy(True, f"Fetching clip for scene {index + 1}")
        run_async(self, _download_one, self._on_downloaded, self._fail,
                  picker.selected, dest, on_progress=self._on_progress)

    def _on_downloaded(self, result: dict):
        index = self._pick_index
        scene = self.project.scenes[index]
        scene.clip_path = result["path"]
        scene.clip_source = result["source"]
        scene.clip_thumb = result["thumb"]
        scene.clip_credit = result["credit"]
        self._rows[index].refresh()
        self._set_busy(False)
        self._update_total()
        self.projectChanged.emit()
        self.log.emit(f"Scene {index + 1} · {result['source']} clip attached")
