"""Voice step — pick a voice, hear it, synthesize every scene.

Synthesis also produces per-word timings; those are what the render step turns
into karaoke subtitles, so they are stored on the scene, not thrown away.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.paths import CACHE_DIR, project_dir
from app.services import tts
from app.services.worker import run_async


def _synthesize_all(texts: list, engine: str, voice: str, rate: str,
                    out_dir: str, ffmpeg_path: str, progress=None) -> list:
    """Sequential on purpose — Edge throttles parallel connections."""
    results = []
    for i, text in enumerate(texts):
        if progress:
            progress(f"Scene {i + 1} of {len(texts)}")
        out = str(Path(out_dir) / f"scene_{i + 1:02d}.mp3")
        results.append(tts.synthesize(engine, text, voice, rate, out, ffmpeg_path))
    return results


class SceneAudioRow(QFrame):
    playRequested = Signal(int)
    resynthRequested = Signal(int)

    def __init__(self, index: int, scene):
        super().__init__()
        self.setObjectName("SceneCard")
        self.index = index
        self.scene = scene

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(10)

        num = QLabel(f"SCENE {index + 1}")
        num.setObjectName("SceneNum")
        num.setFixedWidth(64)

        self.snippet = QLabel()
        self.snippet.setObjectName("ProjMeta")
        self.snippet.setTextInteractionFlags(Qt.NoTextInteraction)

        self.duration = QLabel()
        self.duration.setObjectName("Chip")
        self.duration.setFixedWidth(56)
        self.duration.setAlignment(Qt.AlignCenter)

        self.play = QPushButton("▶")
        self.play.setObjectName("GBtn")
        self.play.setToolTip("Play this scene")
        self.play.setCursor(Qt.PointingHandCursor)
        self.play.clicked.connect(lambda: self.playRequested.emit(self.index))

        self.resynth = QPushButton("↻")
        self.resynth.setObjectName("GBtn")
        self.resynth.setToolTip("Re-voice just this scene")
        self.resynth.setCursor(Qt.PointingHandCursor)
        self.resynth.clicked.connect(lambda: self.resynthRequested.emit(self.index))

        lay.addWidget(num)
        lay.addWidget(self.snippet, 1)
        lay.addWidget(self.duration)
        lay.addWidget(self.play)
        lay.addWidget(self.resynth)

        self.refresh()

    def refresh(self):
        text = self.scene.text.strip().replace("\n", " ")
        self.snippet.setText(text[:70] + "…" if len(text) > 70 else text)
        has_audio = bool(self.scene.audio_path) and Path(self.scene.audio_path).exists()
        self.duration.setText(f"{self.scene.duration:.1f}s" if has_audio else "—")
        self.play.setEnabled(has_audio)

    def set_locked(self, locked: bool):
        self.resynth.setEnabled(not locked)
        self.play.setEnabled(not locked and bool(self.scene.audio_path)
                             and Path(self.scene.audio_path).exists())


class VoiceStep(QWidget):
    projectChanged = Signal()
    log = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.project = None
        self._rows = []
        self._voices = []
        self._elapsed = 0
        self._message = ""
        self._resynth_index = -1
        self._loading_voices = False
        self._voice_language = ""

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(0.9)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.engine = QComboBox()
        for eid, label in tts.ENGINES.items():
            self.engine.addItem(label, eid)
        self.voice = QComboBox()
        self.rate = QComboBox()
        self.rate.addItems(tts.RATES)

        for label, widget, stretch in [
            ("ENGINE", self.engine, 1),
            ("VOICE", self.voice, 3),
            ("RATE", self.rate, 0),
        ]:
            col = QVBoxLayout()
            col.setSpacing(3)
            cap = QLabel(label)
            cap.setObjectName("FieldLabel")
            col.addWidget(cap)
            col.addWidget(widget)
            controls.addLayout(col, stretch)

        buttons = QVBoxLayout()
        buttons.setSpacing(3)
        buttons.addWidget(QLabel(""))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.preview_btn = QPushButton("▶ Preview")
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(self.preview_voice)
        self.synth_btn = QPushButton("Voice all scenes")
        self.synth_btn.setObjectName("Primary")
        self.synth_btn.setCursor(Qt.PointingHandCursor)
        self.synth_btn.clicked.connect(self.synthesize_all)
        row.addWidget(self.preview_btn)
        row.addWidget(self.synth_btn)
        buttons.addLayout(row)
        controls.addLayout(buttons, 0)
        root.addLayout(controls)

        self.engine.currentIndexChanged.connect(self._on_engine_changed)
        self.voice.currentIndexChanged.connect(self._persist)
        self.rate.currentIndexChanged.connect(self._persist)

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

        self.placeholder = QLabel("Write a script first — the Voice step reads its scenes.")
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

        idx = self.engine.findData(settings.get("tts_engine", "edge"))
        self.engine.setCurrentIndex(max(0, idx))
        self.rate.setCurrentText(settings.get("tts_rate", "+0%"))

    # ---- voices ------------------------------------------------------------

    def _on_engine_changed(self):
        self.rate.setEnabled(self.engine.currentData() == "edge")  # Edge-only knob
        self._persist()
        self.reload_voices()

    def reload_voices(self):
        if not self.project or self._loading_voices:
            return
        self._loading_voices = True
        engine = self.engine.currentData()
        self._set_busy(True, "Loading voices")
        run_async(self, tts.list_voices, self._on_voices, self._fail,
                  engine, self.project.language)

    def _on_voices(self, voices: list):
        self._loading_voices = False
        self._voices = voices
        self._voice_language = self.project.language if self.project else ""
        self.voice.blockSignals(True)
        self.voice.clear()
        for v in voices:
            self.voice.addItem(v["label"], v["id"])
        wanted = self.settings.get("tts_voice", "")
        idx = self.voice.findData(wanted)
        if idx >= 0:
            self.voice.setCurrentIndex(idx)
        self.voice.blockSignals(False)
        self._set_busy(False)
        if not voices:
            self.log.emit("No voices returned for this language.")

    def _persist(self):
        if self.voice.currentData():
            self.settings["tts_voice"] = self.voice.currentData()
        self.settings["tts_engine"] = self.engine.currentData()
        self.settings["tts_rate"] = self.rate.currentText()
        from app.config import save_settings
        save_settings(self.settings)

    # ---- project binding ---------------------------------------------------

    def set_project(self, project):
        self.project = project
        self._rebuild_rows()
        # the list is language-specific, so a project in another language needs a refetch
        if project and project.language != self._voice_language:
            self.reload_voices()

    def shutdown(self):
        """Tear the media player down before Qt does — otherwise the Windows
        multimedia backend takes the process out with a non-zero exit."""
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setAudioOutput(None)

    def _rebuild_rows(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        scenes = self.project.scenes if self.project else []
        self.placeholder.setVisible(not scenes)
        for i, scene in enumerate(scenes):
            row = SceneAudioRow(i, scene)
            row.playRequested.connect(self.play_scene)
            row.resynthRequested.connect(self.resynth_scene)
            self.row_layout.insertWidget(i + 1, row)
            self._rows.append(row)
        self._update_total()

    def _update_total(self):
        scenes = self.project.scenes if self.project else []
        voiced = [s for s in scenes if s.audio_path and Path(s.audio_path).exists()]
        if not voiced:
            self.total.setText("")
            return
        total = sum(s.duration for s in voiced)
        self.total.setText(f"{len(voiced)}/{len(scenes)} voiced · {total:.1f}s total")

    # ---- lock / progress ---------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        for w in (self.engine, self.voice, self.preview_btn, self.synth_btn):
            w.setEnabled(not busy)
        self.rate.setEnabled(not busy and self.engine.currentData() == "edge")
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
        self._loading_voices = False
        self._set_busy(False)
        self.status.setText("Failed — see log")
        self.log.emit(f"ERROR  {message}")

    # ---- playback ----------------------------------------------------------

    def _play_file(self, path: str):
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self._player.play()

    def play_scene(self, index: int):
        scene = self.project.scenes[index]
        if scene.audio_path and Path(scene.audio_path).exists():
            self._play_file(scene.audio_path)

    def preview_voice(self):
        voice_id = self.voice.currentData()
        if not voice_id or not self.project:
            return
        out = str(CACHE_DIR / "voice_preview.mp3")
        self._set_busy(True, "Rendering preview")
        run_async(
            self, tts.synthesize, self._on_preview, self._fail,
            self.engine.currentData(), tts.sample_text(self.project.language),
            voice_id, self.rate.currentText(), out,
            self.settings.get("ffmpeg_path", ""),
        )

    def _on_preview(self, result: dict):
        self._set_busy(False)
        self._play_file(result["path"])

    # ---- synthesis ---------------------------------------------------------

    def synthesize_all(self):
        if not self.project or not self.project.scenes:
            return
        voice_id = self.voice.currentData()
        if not voice_id:
            self.log.emit("Pick a voice first.")
            return

        self._persist()
        self._set_busy(True, "Voicing scenes")
        self.log.emit(f"Voice · {self.engine.currentData()} · {self.voice.currentText()}")
        run_async(
            self, _synthesize_all, self._on_all_done, self._fail,
            [s.text for s in self.project.scenes],
            self.engine.currentData(), voice_id, self.rate.currentText(),
            str(project_dir(self.project.id)), self.settings.get("ffmpeg_path", ""),
            on_progress=self._on_progress,
        )

    def _on_all_done(self, results: list):
        voice_id = self.voice.currentData()
        for scene, result in zip(self.project.scenes, results):
            scene.audio_path = result["path"]
            scene.duration = result["duration"]
            scene.words = result["words"]
            scene.voice = voice_id
        for row in self._rows:
            row.refresh()
        self._set_busy(False)
        self._update_total()
        self.projectChanged.emit()
        total = sum(s.duration for s in self.project.scenes)
        words = sum(len(s.words) for s in self.project.scenes)
        self.log.emit(f"Voiced {len(results)} scenes · {total:.1f}s · {words} word timings")

    def resynth_scene(self, index: int):
        voice_id = self.voice.currentData()
        if not voice_id or not self.project:
            return
        self._resynth_index = index
        scene = self.project.scenes[index]
        out = str(project_dir(self.project.id) / f"scene_{index + 1:02d}.mp3")
        self._set_busy(True, f"Voicing scene {index + 1}")
        run_async(
            self, tts.synthesize, self._on_one_done, self._fail,
            self.engine.currentData(), scene.text, voice_id,
            self.rate.currentText(), out, self.settings.get("ffmpeg_path", ""),
        )

    def _on_one_done(self, result: dict):
        i = self._resynth_index
        scene = self.project.scenes[i]
        scene.audio_path = result["path"]
        scene.duration = result["duration"]
        scene.words = result["words"]
        scene.voice = self.voice.currentData()
        self._rows[i].refresh()
        self._set_busy(False)
        self._update_total()
        self.projectChanged.emit()
        self.log.emit(f"Scene {i + 1} voiced · {result['duration']:.1f}s")
