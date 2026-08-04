"""Render step — subtitle look, background music, and the ffmpeg run."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from app.paths import project_dir
from app.services import render
from app.services.worker import run_async

FONTS = ["Arial", "Arial Black", "Impact", "Verdana", "Tahoma", "Trebuchet MS", "Georgia"]
HIGHLIGHTS = [
    ("Violet", "#8B7CF6"), ("Gold", "#FFD700"), ("Mint", "#7ADFA0"),
    ("Cyan", "#5FD7F0"), ("Pink", "#FF6FB5"), ("White", "#FFFFFF"),
]
SAMPLE_WORDS = ["ЭТО", "ПОДСВЕТКА", "СЛОВА"]


class RenderStep(QWidget):
    projectChanged = Signal()
    log = Signal(str)
    rendered = Signal(str)   # path of the finished mp4

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.project = None
        self._elapsed = 0
        self._message = ""
        self._result = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ---- subtitle style ----------------------------------------------
        style_row = QHBoxLayout()
        style_row.setSpacing(8)

        self.font = QComboBox()
        self.font.addItems(FONTS)
        self.size = QSpinBox()
        self.size.setRange(40, 130)
        self.size.setSingleStep(2)
        self.highlight = QComboBox()
        for name, value in HIGHLIGHTS:
            self.highlight.addItem(name, value)
        self.words_per_line = QSpinBox()
        self.words_per_line.setRange(2, 7)
        self.margin = QSpinBox()
        self.margin.setRange(120, 700)
        self.margin.setSingleStep(20)

        for label, widget, stretch in [
            ("FONT", self.font, 2),
            ("SIZE", self.size, 0),
            ("HIGHLIGHT", self.highlight, 1),
            ("WORDS/LINE", self.words_per_line, 0),
            ("HEIGHT", self.margin, 0),
        ]:
            col = QVBoxLayout()
            col.setSpacing(3)
            cap = QLabel(label)
            cap.setObjectName("FieldLabel")
            col.addWidget(cap)
            col.addWidget(widget)
            style_row.addLayout(col, stretch)

        upper_col = QVBoxLayout()
        upper_col.setSpacing(3)
        upper_col.addWidget(QLabel(""))
        self.uppercase = QCheckBox("UPPERCASE")
        upper_col.addWidget(self.uppercase)
        style_row.addLayout(upper_col, 0)
        root.addLayout(style_row)

        self.style_preview = QLabel()
        self.style_preview.setObjectName("SubPreview")
        self.style_preview.setAlignment(Qt.AlignCenter)
        self.style_preview.setMinimumHeight(74)
        root.addWidget(self.style_preview)

        # ---- music --------------------------------------------------------
        music_row = QHBoxLayout()
        music_row.setSpacing(8)
        cap = QLabel("MUSIC")
        cap.setObjectName("FieldLabel")
        music_row.addWidget(cap)
        self.music_label = QLabel()
        self.music_label.setObjectName("Hint")
        music_row.addWidget(self.music_label, 1)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 40)
        self.volume.setFixedWidth(130)
        self.volume_label = QLabel()
        self.volume_label.setObjectName("Hint")
        self.volume_label.setFixedWidth(38)
        self.music_btn = QPushButton("Choose…")
        self.music_btn.setCursor(Qt.PointingHandCursor)
        self.music_btn.clicked.connect(self._choose_music)
        self.music_clear = QPushButton("×")
        self.music_clear.setObjectName("GBtn")
        self.music_clear.setToolTip("No background music")
        self.music_clear.clicked.connect(self._clear_music)
        music_row.addWidget(self.volume)
        music_row.addWidget(self.volume_label)
        music_row.addWidget(self.music_btn)
        music_row.addWidget(self.music_clear)
        root.addLayout(music_row)

        sep = QFrame()
        sep.setObjectName("Sep")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ---- action -------------------------------------------------------
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.readiness = QLabel()
        self.readiness.setObjectName("Hint")
        self.readiness.setWordWrap(True)
        self.render_btn = QPushButton("Render video")
        self.render_btn.setObjectName("Primary")
        self.render_btn.setCursor(Qt.PointingHandCursor)
        self.render_btn.clicked.connect(self.start_render)
        action_row.addWidget(self.readiness, 1)
        action_row.addWidget(self.render_btn)
        root.addLayout(action_row)

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

        self.result_box = QFrame()
        self.result_box.setObjectName("SceneCard")
        result_lay = QHBoxLayout(self.result_box)
        result_lay.setContentsMargins(12, 10, 12, 10)
        result_lay.setSpacing(10)
        self.result_label = QLabel()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(lambda: self.rendered.emit(self._result["path"]))
        self.folder_btn = QPushButton("Open folder")
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.clicked.connect(self._open_folder)
        result_lay.addWidget(self.result_label, 1)
        result_lay.addWidget(self.play_btn)
        result_lay.addWidget(self.folder_btn)
        self.result_box.setVisible(False)
        root.addWidget(self.result_box)

        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._load_settings()
        for widget in (self.font, self.highlight):
            widget.currentIndexChanged.connect(self._on_style_changed)
        for widget in (self.size, self.words_per_line, self.margin):
            widget.valueChanged.connect(self._on_style_changed)
        self.uppercase.stateChanged.connect(self._on_style_changed)
        self.volume.valueChanged.connect(self._on_style_changed)
        self._on_style_changed()

    # ---- settings ----------------------------------------------------------

    def _load_settings(self):
        s = self.settings
        self.font.setCurrentText(s.get("sub_font", "Arial"))
        self.size.setValue(int(s.get("sub_size", 78)))
        idx = self.highlight.findData(s.get("sub_highlight", "#8B7CF6"))
        self.highlight.setCurrentIndex(max(0, idx))
        self.words_per_line.setValue(int(s.get("sub_words_per_line", 4)))
        self.margin.setValue(int(s.get("sub_margin_v", 320)))
        self.uppercase.setChecked(bool(s.get("sub_uppercase", True)))
        self.volume.setValue(int(s.get("bgm_volume", 12)))
        self._refresh_music_label()

    def _on_style_changed(self):
        """Settings apply straight to the preview — no Apply button."""
        self.settings.update({
            "sub_font": self.font.currentText(),
            "sub_size": self.size.value(),
            "sub_highlight": self.highlight.currentData(),
            "sub_words_per_line": self.words_per_line.value(),
            "sub_margin_v": self.margin.value(),
            "sub_uppercase": self.uppercase.isChecked(),
            "bgm_volume": self.volume.value(),
        })
        from app.config import save_settings
        save_settings(self.settings)

        self.volume_label.setText(f"{self.volume.value()}%")
        words = [w if self.uppercase.isChecked() else w.capitalize() for w in SAMPLE_WORDS]
        # the strip is ~1/3 of frame width, so scale the point size to match
        preview_size = max(11, round(self.size.value() / 3.4))
        spans = []
        for i, word in enumerate(words):
            colour = self.highlight.currentData() if i == 1 else "#FFFFFF"
            spans.append(f"<span style='color:{colour}'>{word}</span>")
        self.style_preview.setText(
            f"<div style=\"font-family:'{self.font.currentText()}'; font-size:{preview_size}pt; "
            f"font-weight:800;\">{' '.join(spans)}</div>"
        )

    def _choose_music(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Background music", self.settings.get("bgm_path", ""),
            "Audio (*.mp3 *.m4a *.wav *.ogg *.flac)")
        if path:
            self.settings["bgm_path"] = path
            from app.config import save_settings
            save_settings(self.settings)
            self._refresh_music_label()

    def _clear_music(self):
        self.settings["bgm_path"] = ""
        from app.config import save_settings
        save_settings(self.settings)
        self._refresh_music_label()

    def _refresh_music_label(self):
        path = self.settings.get("bgm_path", "")
        self.music_label.setText(Path(path).name if path else "none — narration only")
        self.volume.setEnabled(bool(path))
        self.music_clear.setEnabled(bool(path))

    # ---- project binding ---------------------------------------------------

    def set_project(self, project):
        self.project = project
        self._result = None
        self.result_box.setVisible(False)
        self._refresh_readiness()
        if not project:
            return
        # a render from an earlier session is still on disk — surface it
        existing = project_dir(project.id) / "render.mp4"
        if existing.exists():
            total = sum(s.duration for s in project.scenes)
            self._result = {"path": str(existing), "duration": total}
            self.result_label.setText(
                f"{total:.1f}s · {existing.stat().st_size / 1e6:.1f} MB · rendered earlier")
            self.result_box.setVisible(True)

    def _refresh_readiness(self):
        scenes = self.project.scenes if self.project else []
        if not scenes:
            self.readiness.setText("Nothing to render yet.")
            self.render_btn.setEnabled(False)
            return
        no_voice = [i + 1 for i, s in enumerate(scenes) if not s.audio_path]
        no_clip = [i + 1 for i, s in enumerate(scenes) if not s.clip_path]
        problems = []
        if no_voice:
            problems.append(f"no voice on {', '.join(map(str, no_voice))}")
        if no_clip:
            problems.append(f"no footage on {', '.join(map(str, no_clip))}")
        if problems:
            self.readiness.setText("Scene " + "; ".join(problems))
            self.render_btn.setEnabled(False)
        else:
            total = sum(s.duration for s in scenes)
            self.readiness.setText(
                f"{len(scenes)} scenes · {total:.1f}s · 1080×1920 · subtitles burned in")
            self.render_btn.setEnabled(True)

    # ---- lock / progress ---------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        if busy:
            self.progress.setValue(0)
        for widget in (self.render_btn, self.font, self.size, self.highlight,
                       self.words_per_line, self.margin, self.uppercase,
                       self.music_btn, self.volume, self.music_clear):
            widget.setEnabled(not busy)
        if not busy:
            self._refresh_readiness()
            self._refresh_music_label()
            self._timer.stop()
            self.status.setText("")
        else:
            self._elapsed = 0
            self._message = message
            self.status.setText(f"{message} · 0s")
            self._timer.start()

    def _tick(self):
        self._elapsed += 1
        self.status.setText(f"{self._message} · {self._elapsed}s")

    def _on_progress(self, label: str):
        self._message = label
        self.status.setText(f"{label} · {self._elapsed}s")

    def _on_pct(self, value: int):
        self.progress.setValue(value)

    def _fail(self, message: str):
        self._set_busy(False)
        self.status.setText("Failed — see log")
        self.log.emit(f"ERROR  {message}")

    # ---- render ------------------------------------------------------------

    def start_render(self):
        if not self.project or not self.project.scenes:
            return
        work = project_dir(self.project.id)
        out = str(work / "render.mp4")
        style = {
            "font": self.font.currentText(),
            "size": self.size.value(),
            "highlight": self.highlight.currentData(),
            "words_per_line": self.words_per_line.value(),
            "margin_v": self.margin.value(),
            "uppercase": self.uppercase.isChecked(),
        }
        scenes = [{"clip_path": s.clip_path, "audio_path": s.audio_path,
                   "duration": s.duration, "words": s.words} for s in self.project.scenes]

        self._set_busy(True, "Rendering")
        self.log.emit(f"Render · {len(scenes)} scenes · {self.font.currentText()} {self.size.value()}px")
        run_async(
            self, render.render, self._on_done, self._fail,
            scenes, out, str(work), style,
            self.settings.get("bgm_path", ""), self.volume.value() / 100.0,
            self.settings.get("ffmpeg_path", ""),
            on_progress=self._on_progress, on_progress_pct=self._on_pct,
        )

    def _on_done(self, result: dict):
        self._result = result
        self._set_busy(False)
        size_mb = Path(result["path"]).stat().st_size / 1e6
        self.result_label.setText(
            f"{result['duration']:.1f}s · {size_mb:.1f} MB · {result['words']} words highlighted")
        self.result_box.setVisible(True)
        self.log.emit(f"Rendered {result['duration']:.1f}s to {Path(result['path']).name}")
        self.rendered.emit(result["path"])

    def _open_folder(self):
        if not self._result:
            return
        folder = str(Path(self._result["path"]).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
