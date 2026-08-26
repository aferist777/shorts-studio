"""Center pane — two macro-steps.

Writing, voicing and picturing are one step now: they are one job done in one
order, and splitting them into tabs only ever asked the user to remember that
order. Rendering stays separate — it is the one thing you come back to.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app.widgets.media_step import MediaStep
from app.widgets.render_step import RenderStep

STEPS = ["Script", "Render"]

MAKE, RENDER = 0, 1


class WorkspacePane(QWidget):
    projectChanged = Signal()
    log = Signal(str)
    renderReady = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.setObjectName("Pane")
        self.settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("PaneHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 7, 10, 7)
        hl.setSpacing(3)
        self.step_buttons = []
        for i, name in enumerate(STEPS):
            b = QPushButton(name)
            b.setObjectName("Step")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(i == MAKE)
            b.clicked.connect(lambda _=False, idx=i: self.set_step(idx))
            hl.addWidget(b)
            self.step_buttons.append(b)
        hl.addStretch(1)
        root.addWidget(head)

        self.stack = QStackedWidget()
        self.media = MediaStep(settings)
        self.render = RenderStep(settings)
        # script, voice and footage live behind one step now; these keep the
        # older call sites working without each of them learning the new shape
        self.script = self.media.script
        self.voice = self.media.voice
        self.footage = self.media.footage
        for step in (self.media, self.render):
            step.projectChanged.connect(self._on_step_changed)
            step.log.connect(self.log.emit)
            self.stack.addWidget(step)
        self.render.rendered.connect(self.renderReady.emit)
        root.addWidget(self.stack, 1)

        self.set_step(MAKE)

    def set_step(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.step_buttons):
            b.setChecked(i == index)

    def _on_step_changed(self):
        self._sync_step_availability()
        self.projectChanged.emit()

    def _sync_step_availability(self):
        """Rendering needs a script to work from."""
        project = self.media.project
        has_scenes = bool(project and project.scenes)
        self.step_buttons[RENDER].setEnabled(has_scenes)
        self.render.set_project(project)
        if not has_scenes and self.stack.currentIndex() == RENDER:
            self.set_step(MAKE)

    def refresh_render_readiness(self):
        self.render.set_project(self.media.project)

    def reload_narrators(self):
        self.script.reload_narrators()

    def set_project(self, project):
        self.media.set_project(project)   # hands it on to all three modes
        self._sync_step_availability()

    def shutdown(self):
        self.media.shutdown()
