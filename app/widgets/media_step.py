"""Script, voice and footage as one step, in that order.

They used to be separate tabs and the order between them lived only in the
user's head — which mattered, because a scene's length comes from its voice
track and nothing about footage can be decided without it, and neither exists
before the script does. Here each set of tools simply is not on screen until
the one before it is done.

The three are stacked rather than shown side by side: while you are choosing a
voice, the seven dials that write a script are noise — and they are also what
made this pane refuse to narrow, so they leave the screen entirely.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app.widgets.footage_step import FootageStep
from app.widgets.script_step import ScriptStep
from app.widgets.voice_step import VoiceStep

SCRIPT, VOICE, FOOTAGE = 0, 1, 2

# per mode: the word on the bar, what the button forward says, and the way back
FORWARD = {SCRIPT: "Script done →", VOICE: "Voices done →"}
BACK = {VOICE: "← Script", FOOTAGE: "← Voices"}
TITLES = {SCRIPT: "SCRIPT", VOICE: "VOICE", FOOTAGE: "FOOTAGE"}


class MediaStep(QWidget):
    projectChanged = Signal()
    log = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.project = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("ModeBar")
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(14, 8, 14, 8)
        bar_lay.setSpacing(8)

        self.where = QLabel()
        self.where.setObjectName("FieldLabel")
        self.hint = QLabel()
        self.hint.setObjectName("Hint")
        bar_lay.addWidget(self.where)
        bar_lay.addWidget(self.hint)
        bar_lay.addStretch(1)

        # the way back is deliberately quiet: rewriting one line and re-voicing
        # it is a real need, but not the direction of travel
        self.back_btn = QPushButton()
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.step_back)
        self.done_btn = QPushButton()
        self.done_btn.setObjectName("Primary")
        self.done_btn.setCursor(Qt.PointingHandCursor)
        self.done_btn.clicked.connect(self.step_forward)
        bar_lay.addWidget(self.back_btn)
        bar_lay.addWidget(self.done_btn)
        root.addWidget(bar)

        self.stack = QStackedWidget()
        self.script = ScriptStep(settings)
        self.voice = VoiceStep(settings)
        self.footage = FootageStep(settings)
        for step in (self.script, self.voice, self.footage):
            step.projectChanged.connect(self._on_changed)
            step.log.connect(self.log.emit)
            self.stack.addWidget(step)
        root.addWidget(self.stack, 1)

        self.set_mode(SCRIPT)

    # ---- modes --------------------------------------------------------------

    def set_mode(self, mode: int):
        mode = max(SCRIPT, min(FOOTAGE, mode))
        # the scenes are written after every step here has been handed the
        # project, so whichever one is about to be shown catches up first
        if mode == VOICE:
            self.voice.sync()
        elif mode == FOOTAGE:
            self.footage.sync()
        self.stack.setCurrentIndex(mode)
        if mode != VOICE:
            self.voice.stop_playback()
        if mode != FOOTAGE:
            self.footage._stop_audio()
        # the writing dials belong to writing; past that they are only width
        self.script.show_options(mode == SCRIPT)
        # a page that changes size while it is off screen never tells the stack,
        # and the pane goes on reserving room for a row that is no longer there
        self.stack.updateGeometry()
        self._sync_bar()

    def step_forward(self):
        self.set_mode(self.stack.currentIndex() + 1)

    def step_back(self):
        self.set_mode(self.stack.currentIndex() - 1)

    def _sync_bar(self):
        mode = self.stack.currentIndex()
        scenes = self.project.scenes if self.project else []
        voiced = [s for s in scenes if s.audio_path]

        self.where.setText(TITLES[mode])
        self.back_btn.setVisible(mode in BACK)
        self.back_btn.setText(BACK.get(mode, ""))
        self.done_btn.setVisible(mode in FORWARD)
        self.done_btn.setText(FORWARD.get(mode, ""))

        if mode == SCRIPT:
            ready = bool(scenes)
            self.hint.setText(f"{len(scenes)} scenes" if scenes else "")
            self.done_btn.setEnabled(ready)
            self.done_btn.setToolTip(
                "" if ready else "Write the script first — everything after it "
                                 "is built per scene")
        elif mode == VOICE:
            ready = bool(scenes) and len(voiced) == len(scenes)
            self.hint.setText(
                f"{len(voiced)}/{len(scenes)} scenes voiced" if scenes else "")
            self.done_btn.setEnabled(ready)
            self.done_btn.setToolTip(
                "" if ready else "Every scene needs a voice track first — a "
                                 "scene's length comes from its audio")
        else:
            filled = sum(1 for s in scenes if s.shots)
            self.hint.setText(f"{filled}/{len(scenes)} scenes have footage"
                              if scenes else "")

    def _on_changed(self):
        self._sync_bar()
        self.projectChanged.emit()

    # ---- the outside world --------------------------------------------------

    def set_project(self, project):
        self.project = project
        self.script.set_project(project)
        self.voice.set_project(project)
        self.footage.set_project(project)
        # land where the work actually is: nothing written yet -> the script,
        # everything voiced -> the pictures, anything between -> the voices
        scenes = project.scenes if project else []
        if not scenes:
            self.set_mode(SCRIPT)
        elif all(s.audio_path for s in scenes):
            self.set_mode(FOOTAGE)
        else:
            self.set_mode(VOICE)

    def shutdown(self):
        self.voice.shutdown()
