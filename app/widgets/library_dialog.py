"""Videos — every project in one list: what is done, what is queued, what is a draft."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.paths import project_dir
from app.services import library
from app.services.worker import run_async

THUMB_W, THUMB_H = 45, 80


class LibraryRow(QFrame):
    toggled = Signal()
    playRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRenderRequested = Signal(str)

    def __init__(self, info: dict):
        super().__init__()
        self.setObjectName("SceneCard")
        self.info = info

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)

        self.check = QCheckBox()
        self.check.setEnabled(info["state"] != library.DRAFT)
        self.check.setToolTip("Include in the render queue"
                              if info["state"] != library.DRAFT
                              else "Needs a voice-over and footage first")
        self.check.stateChanged.connect(self.toggled.emit)

        self.thumb = QLabel()
        self.thumb.setObjectName("ClipThumb")
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(info["poster"]) if info["poster"] else QPixmap()
        if not pixmap.isNull():
            self.thumb.setPixmap(pixmap.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatioByExpanding,
                                               Qt.SmoothTransformation))
        else:
            self.thumb.setText("—")

        middle = QVBoxLayout()
        middle.setSpacing(3)
        title = QLabel(info["title"])
        title.setObjectName("ProjName")
        detail = QLabel(f"{info['scenes']} scenes · {info['duration']:.1f}s")
        detail.setObjectName("ProjMeta")
        middle.addWidget(title)
        middle.addWidget(detail)

        state = QLabel(library.STATE_LABELS[info["state"]].upper())
        state.setObjectName(f"Chip{info['state'].capitalize()}")
        state.setAlignment(Qt.AlignCenter)
        state.setFixedWidth(84)

        made = QLabel(f"{info['size_mb']:.1f} MB · {info['made_at']}" if info["video"] else "")
        made.setObjectName("ProjMeta")
        made.setFixedWidth(150)
        made.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.play = QPushButton("►")
        self.play.setObjectName("GBtn")
        self.play.setToolTip("Play in the preview panel")
        self.play.setEnabled(bool(info["video"]))
        self.play.clicked.connect(lambda: self.playRequested.emit(self.info["video"]))

        self.folder = QPushButton("⌸")
        self.folder.setObjectName("GBtn")
        self.folder.setToolTip("Open the project folder")
        self.folder.clicked.connect(self._open_folder)

        self.copy = QPushButton("⧉")
        self.copy.setObjectName("GBtn")
        self.copy.setToolTip("Duplicate the script for another take")
        self.copy.clicked.connect(lambda: self.duplicateRequested.emit(self.info["id"]))

        self.drop = QPushButton("×")
        self.drop.setObjectName("GBtn")
        self.drop.setToolTip("Delete the rendered file (the project stays)")
        self.drop.setEnabled(bool(info["video"]))
        self.drop.clicked.connect(lambda: self.deleteRenderRequested.emit(self.info["id"]))

        lay.addWidget(self.check, 0, Qt.AlignVCenter)
        lay.addWidget(self.thumb)
        lay.addLayout(middle, 1)
        lay.addWidget(state, 0, Qt.AlignVCenter)
        lay.addWidget(made, 0, Qt.AlignVCenter)
        for button in (self.play, self.folder, self.copy, self.drop):
            lay.addWidget(button, 0, Qt.AlignVCenter)

    def _open_folder(self):
        folder = str(project_dir(self.info["id"]))
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def set_locked(self, locked: bool):
        if locked:
            for widget in (self.check, self.play, self.folder, self.copy, self.drop):
                widget.setEnabled(False)
            return
        has_video = bool(self.info["video"])
        self.check.setEnabled(self.info["state"] != library.DRAFT)
        self.play.setEnabled(has_video)
        self.drop.setEnabled(has_video)
        self.folder.setEnabled(True)
        self.copy.setEnabled(True)


class LibraryDialog(QDialog):
    playRequested = Signal(str)
    storeChanged = Signal()

    def __init__(self, store, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Videos")
        self.resize(1000, 640)
        self.store = store
        self.settings = settings
        self._rows = []
        self._elapsed = 0
        self._message = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Videos")
        title.setObjectName("DlgTitle")
        self.summary = QLabel()
        self.summary.setObjectName("Hint")
        head.addWidget(title)
        head.addWidget(self.summary)
        head.addStretch(1)
        self.render_btn = QPushButton("Render selected")
        self.render_btn.setObjectName("Primary")
        self.render_btn.setCursor(Qt.PointingHandCursor)
        self.render_btn.setEnabled(False)
        self.render_btn.clicked.connect(self.render_selected)
        head.addWidget(self.render_btn)
        root.addLayout(head)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
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

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self.reload()

    # ---- rows --------------------------------------------------------------

    def reload(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        counts = {library.DRAFT: 0, library.READY: 0, library.RENDERED: 0}
        for i, project in enumerate(self.store.projects):
            info = library.summarize(project)
            counts[info["state"]] += 1
            row = LibraryRow(info)
            row.toggled.connect(self._refresh_button)
            row.playRequested.connect(self._play)
            row.duplicateRequested.connect(self._duplicate)
            row.deleteRenderRequested.connect(self._delete_render)
            self.row_layout.insertWidget(i, row)
            self._rows.append(row)

        self.summary.setText(
            f"{counts[library.RENDERED]} rendered · {counts[library.READY]} ready · "
            f"{counts[library.DRAFT]} draft"
        )
        self._refresh_button()

    def _refresh_button(self):
        count = len(self._selected())
        self.render_btn.setText(f"Render {count} selected" if count else "Render selected")
        self.render_btn.setEnabled(count > 0)

    def _selected(self) -> list:
        return [r for r in self._rows if r.check.isChecked() and r.check.isEnabled()]

    # ---- row actions -------------------------------------------------------

    def _play(self, path: str):
        self.playRequested.emit(path)
        self.accept()

    def _duplicate(self, project_id: str):
        copy = self.store.duplicate(project_id)
        self.storeChanged.emit()
        self.reload()
        self.status.setText(f"Duplicated as “{copy.title}”")

    def _delete_render(self, project_id: str):
        project = self.store.get(project_id)
        video = library.render_path(project_id)
        confirm = QMessageBox.question(
            self, "Delete render",
            f"Delete the rendered file for “{project.title}”?\n"
            "The project, its voice-over and its footage all stay.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        video.unlink(missing_ok=True)
        self.reload()
        self.storeChanged.emit()

    # ---- batch render ------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        if busy:
            self.progress.setValue(0)
        self.render_btn.setEnabled(not busy and bool(self._selected()))
        for row in self._rows:
            row.set_locked(busy)
        if busy:
            self._elapsed = 0
            self._message = message
            self.status.setText(f"{message} · 0s")
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self):
        self._elapsed += 1
        self.status.setText(f"{self._message} · {self._elapsed}s")

    def _on_progress(self, label: str):
        self._message = label
        self.status.setText(f"{label} · {self._elapsed}s")

    def _on_pct(self, value: int):
        self.progress.setValue(value)

    def render_selected(self):
        s = self.settings
        style = {
            "font": s.get("sub_font", "Arial"), "size": s.get("sub_size", 78),
            "highlight": s.get("sub_highlight", "#8B7CF6"),
            "words_per_line": s.get("sub_words_per_line", 4),
            "margin_v": s.get("sub_margin_v", 320),
            "uppercase": s.get("sub_uppercase", True),
        }
        jobs = []
        for row in self._selected():
            project = self.store.get(row.info["id"])
            work = project_dir(project.id)
            jobs.append({
                "id": project.id,
                "title": project.title,
                "scenes": [{"clip_path": sc.clip_path, "audio_path": sc.audio_path,
                            "duration": sc.duration, "words": sc.words}
                           for sc in project.scenes],
                "out": str(work / "render.mp4"),
                "work": str(work),
                "style": style,
                "bgm_path": s.get("bgm_path", ""),
                "bgm_volume": s.get("bgm_volume", 12) / 100.0,
                "ffmpeg_path": s.get("ffmpeg_path", ""),
            })

        self._set_busy(True, "Rendering queue")
        run_async(self, library.render_batch, self._on_batch_done, self._fail, jobs,
                  on_progress=self._on_progress, on_progress_pct=self._on_pct)

    def _on_batch_done(self, results: list):
        self._set_busy(False)
        self.reload()
        self.storeChanged.emit()
        ok = [r for r in results if r["ok"]]
        failed = [r for r in results if not r["ok"]]
        note = f"{len(ok)} rendered"
        if failed:
            note += f" · {len(failed)} failed: " + "; ".join(
                f"{r['title']} ({r['error'][:60]})" for r in failed)
        self.status.setText(note)

    def _fail(self, message: str):
        self._set_busy(False)
        self.status.setText(f"Failed — {message}")
