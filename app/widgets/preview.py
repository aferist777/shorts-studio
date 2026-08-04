"""Right pane — the 9:16 player, the script as one block, and the run log."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QStackedLayout, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.services import library


class PlayerFrame(QFrame):
    """Keeps a 9:16 box centred in whatever width it gets."""

    def __init__(self):
        super().__init__()
        self.setObjectName("PreviewFrame")
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(6, 6, 6, 6)

        self.placeholder = QLabel("No render yet")
        self.placeholder.setObjectName("PreviewPh")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)

        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.KeepAspectRatio)

        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.video)

    def show_video(self, on: bool):
        self.stack.setCurrentIndex(1 if on else 0)

    def show_poster(self, path: str):
        """QMediaPlayer draws nothing until it plays, so a loaded-but-paused
        render would otherwise look like an empty black box."""
        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            self.placeholder.setText("Rendered · press play")
            return
        self.placeholder.setPixmap(
            pixmap.scaled(self.placeholder.width() or 240, self.placeholder.height() or 420,
                          Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.show_video(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMaximumWidth(max(120, int(self.height() * 9 / 16)))


class PreviewPane(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Pane")
        self.project = None
        self._video_path = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("PaneHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 9, 10, 9)
        title = QLabel("Preview")
        title.setObjectName("PaneTitle")
        self.meta = QLabel("")
        self.meta.setObjectName("PaneCount")
        hl.addWidget(title)
        hl.addWidget(self.meta)
        hl.addStretch(1)
        root.addWidget(head)

        body = QVBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(8)

        frame_row = QHBoxLayout()
        frame_row.addStretch(1)
        self.frame = PlayerFrame()
        frame_row.addWidget(self.frame)
        frame_row.addStretch(1)
        body.addLayout(frame_row, 3)

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.setVideoOutput(self.frame.video)
        self.audio_out.setVolume(0.9)
        self.player.playbackStateChanged.connect(self._on_state)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addStretch(1)
        # geometric glyphs, not the emoji-presentation ones Windows colours in
        self.play_btn = QPushButton("►")
        self.play_btn.setObjectName("GBtn")
        self.play_btn.setToolTip("Play / pause")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.toggle)
        self.restart_btn = QPushButton("⟲")
        self.restart_btn.setObjectName("GBtn")
        self.restart_btn.setToolTip("Back to the start")
        self.restart_btn.setEnabled(False)
        self.restart_btn.clicked.connect(self.restart)
        controls.addWidget(self.restart_btn)
        controls.addWidget(self.play_btn)
        controls.addStretch(1)
        body.addLayout(controls)

        cap = QLabel("FULL SCRIPT")
        cap.setObjectName("FieldLabel")
        body.addWidget(cap)
        self.script = QTextEdit()
        self.script.setReadOnly(True)
        self.script.setPlaceholderText("The generated narration shows up here, end to end.")
        body.addWidget(self.script, 2)

        cap2 = QLabel("LOG")
        cap2.setObjectName("FieldLabel")
        body.addWidget(cap2)
        self.log = QTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        body.addWidget(self.log, 1)

        root.addLayout(body, 1)

    # ---- script ------------------------------------------------------------

    def set_project(self, project):
        self.project = project
        self.stop()
        self.frame.show_video(False)
        self.play_btn.setEnabled(False)
        self.restart_btn.setEnabled(False)
        self._video_path = ""
        self.refresh()
        # a project that was rendered before keeps its file on disk
        if project:
            existing = library.render_path(project.id)
            if existing.exists():
                self.set_video(str(existing), autoplay=False)

    def refresh(self):
        if not self.project:
            self.script.setPlainText("")
            self.meta.setText("")
            return
        self.script.setPlainText(self.project.script_text)
        words = len(self.project.script_text.split())
        if not words:
            self.meta.setText("")
            return
        voiced = sum(s.duration for s in self.project.scenes)
        if voiced:
            self.meta.setText(f"{words} words · {voiced:.1f}s")   # measured, not guessed
        else:
            # ~2.6 words/second is a normal narration pace
            self.meta.setText(f"{words} words · ~{round(words / 2.6)}s")

    def append_log(self, line: str):
        self.log.append(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ---- player ------------------------------------------------------------

    def set_video(self, path: str, autoplay: bool = True):
        if not path or not Path(path).exists():
            return
        self._video_path = path
        self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.play_btn.setEnabled(True)
        self.restart_btn.setEnabled(True)
        if autoplay:
            self.frame.show_video(True)
            self.player.play()
        else:
            self.frame.show_poster(library.poster_for(path))

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.frame.show_video(True)
            self.player.play()

    def restart(self):
        self.frame.show_video(True)
        self.player.setPosition(0)
        self.player.play()

    def stop(self):
        self.player.stop()

    def _on_state(self, state):
        self.play_btn.setText("❚❚" if state == QMediaPlayer.PlayingState else "▶")

    def shutdown(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setVideoOutput(None)
        self.player.setAudioOutput(None)
