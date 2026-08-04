"""Center pane — the four macro-steps. Only Script is live in this build."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from app.models_data import Scene
from app.services import llm
from app.services.worker import run_async
from app.widgets.footage_step import FootageStep
from app.widgets.render_step import RenderStep
from app.widgets.voice_step import VoiceStep

LANGUAGES = ["Russian", "English", "Spanish", "German", "French", "Portuguese"]
TONES = ["Conversational", "Documentary", "Punchy", "Calm", "Provocative", "Wry"]

STEPS = ["Script", "Voice", "Footage", "Render"]


class GrowingTextEdit(QTextEdit):
    """Sizes itself to its content so scene cards don't need inner scrollbars."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().contentsChanged.connect(self._fit)
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        height = int(self.document().size().height()) + 18
        self.setFixedHeight(max(52, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class SceneCard(QFrame):
    changed = Signal()
    rewriteRequested = Signal(int)

    def __init__(self, index: int, scene: Scene):
        super().__init__()
        self.setObjectName("SceneCard")
        self.index = index
        self.scene = scene

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(6)
        num = QLabel(f"SCENE {index + 1}")
        num.setObjectName("SceneNum")
        rewrite = QPushButton("↻")
        rewrite.setObjectName("GBtn")
        rewrite.setToolTip("Rewrite just this paragraph")
        rewrite.setCursor(Qt.PointingHandCursor)
        rewrite.clicked.connect(lambda: self.rewriteRequested.emit(self.index))
        head.addWidget(num)
        head.addStretch(1)
        head.addWidget(rewrite)
        root.addLayout(head)

        self.editor = GrowingTextEdit(scene.text)
        self.editor.textChanged.connect(self._on_edit)
        root.addWidget(self.editor)

        self.chips = QHBoxLayout()
        self.chips.setSpacing(5)
        self.chips.addStretch(1)
        root.addLayout(self.chips)
        self._render_chips()

        self._controls = [rewrite, self.editor]

    def _on_edit(self):
        self.scene.text = self.editor.toPlainText()
        self.changed.emit()

    def _render_chips(self):
        while self.chips.count() > 1:
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for term in self.scene.terms:
            chip = QLabel(term)
            chip.setObjectName("Chip")
            self.chips.insertWidget(self.chips.count() - 1, chip)

    def refresh(self):
        if self.editor.toPlainText() != self.scene.text:
            self.editor.blockSignals(True)
            self.editor.setPlainText(self.scene.text)
            self.editor.blockSignals(False)
        self._render_chips()

    def set_locked(self, locked: bool):
        for w in self._controls:
            w.setEnabled(not locked)


class ScriptStep(QWidget):
    projectChanged = Signal()
    log = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.project = None
        self._cards = []
        self._elapsed = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        topic_row = QHBoxLayout()
        topic_row.setSpacing(8)
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("What is the video about?")
        self.topic.returnPressed.connect(self.generate)
        self.generate_btn = QPushButton("Generate script")
        self.generate_btn.setObjectName("Primary")
        self.generate_btn.setCursor(Qt.PointingHandCursor)
        self.generate_btn.clicked.connect(self.generate)
        topic_row.addWidget(self.topic, 1)
        topic_row.addWidget(self.generate_btn)
        root.addLayout(topic_row)

        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.language = QComboBox()
        self.language.addItems(LANGUAGES)
        self.paragraphs = QSpinBox()
        self.paragraphs.setRange(2, 12)
        self.tone = QComboBox()
        self.tone.addItems(TONES)
        self.provider = QComboBox()
        for pid, (label, _) in llm.REGISTRY.items():
            self.provider.addItem(label, pid)
        self.model = QComboBox()
        self.effort = QComboBox()
        self.effort.addItems(llm.EFFORTS)

        for label, widget, stretch in [
            ("LANGUAGE", self.language, 1),
            ("SCENES", self.paragraphs, 0),
            ("TONE", self.tone, 1),
            ("PROVIDER", self.provider, 1),
            ("MODEL", self.model, 2),
            ("EFFORT", self.effort, 0),
        ]:
            col = QVBoxLayout()
            col.setSpacing(3)
            cap = QLabel(label)
            cap.setObjectName("FieldLabel")
            col.addWidget(cap)
            col.addWidget(widget)
            opts.addLayout(col, stretch)
        root.addLayout(opts)

        self._load_settings_into_widgets()
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        for w in (self.language, self.tone, self.model, self.effort):
            w.currentIndexChanged.connect(self._persist)
        self.paragraphs.valueChanged.connect(self._persist)

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
        self.scene_layout = QVBoxLayout(holder)
        self.scene_layout.setContentsMargins(0, 2, 6, 2)
        self.scene_layout.setSpacing(8)
        self.scene_layout.addStretch(1)
        self.scroll.setWidget(holder)
        root.addWidget(self.scroll, 1)

        self.placeholder = QLabel("Describe the topic above, then generate.\n"
                                  "Every paragraph stays editable, and any one of them can be rewritten on its own.")
        self.placeholder.setObjectName("Hint")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.scene_layout.insertWidget(0, self.placeholder)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ---- settings plumbing -------------------------------------------------

    def _load_settings_into_widgets(self):
        s = self.settings
        self.language.setCurrentText(s.get("language", "Russian"))
        self.paragraphs.setValue(int(s.get("paragraphs", 5)))
        self.tone.setCurrentText(s.get("tone", "Conversational"))
        idx = self.provider.findData(s.get("llm_provider", "anthropic"))
        self.provider.setCurrentIndex(max(0, idx))
        self._reload_models(select=s.get("llm_model", ""))
        self.effort.setCurrentText(s.get("llm_effort", "medium"))
        # effort is an Anthropic-only dial
        self.effort.setEnabled(self.provider.currentData() == "anthropic")

    def _reload_models(self, select: str = ""):
        provider = self.provider.currentData()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(llm.models_for(provider))
        if select and select in llm.models_for(provider):
            self.model.setCurrentText(select)
        self.model.blockSignals(False)

    def _on_provider_changed(self):
        self._reload_models()
        self.effort.setEnabled(self.provider.currentData() == "anthropic")
        self._persist()

    def _persist(self):
        self.settings.update({
            "language": self.language.currentText(),
            "paragraphs": self.paragraphs.value(),
            "tone": self.tone.currentText(),
            "llm_provider": self.provider.currentData(),
            "llm_model": self.model.currentText(),
            "llm_effort": self.effort.currentText(),
        })
        from app.config import save_settings
        save_settings(self.settings)

    # ---- project binding ---------------------------------------------------

    def set_project(self, project):
        self.project = project
        self.topic.setText(project.topic if project else "")
        if project:
            if project.language in LANGUAGES:
                self.language.setCurrentText(project.language)
            if project.tone in TONES:
                self.tone.setCurrentText(project.tone)
        self._rebuild_cards()

    def _rebuild_cards(self):
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        scenes = self.project.scenes if self.project else []
        self.placeholder.setVisible(not scenes)

        for i, scene in enumerate(scenes):
            card = SceneCard(i, scene)
            card.changed.connect(self.projectChanged.emit)
            card.rewriteRequested.connect(self.rewrite_one)
            self.scene_layout.insertWidget(i + 1, card)
            self._cards.append(card)

    # ---- lock / progress ---------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        self.generate_btn.setEnabled(not busy)
        for w in (self.topic, self.language, self.paragraphs, self.tone,
                  self.provider, self.model, self.effort):
            w.setEnabled(not busy)
        if busy and self.provider.currentData() != "anthropic":
            self.effort.setEnabled(False)
        for card in self._cards:
            card.set_locked(busy)
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

    def _fail(self, message: str):
        self._set_busy(False)
        self.status.setText("Failed — see log")
        self.log.emit(f"ERROR  {message}")

    # ---- generation --------------------------------------------------------

    def generate(self):
        if not self.project:
            return
        topic = self.topic.text().strip()
        if not topic:
            self.topic.setFocus()
            return

        self.project.topic = topic
        self.project.language = self.language.currentText()
        self.project.tone = self.tone.currentText()
        self._persist()

        self._set_busy(True, "Writing script")
        self.log.emit(f"Script · {self.model.currentText()} · {topic}")
        run_async(
            self, llm.generate_script, self._on_script, self._fail,
            self.settings, topic, self.project.language,
            self.paragraphs.value(), self.project.tone,
        )

    def _on_script(self, result: dict):
        self.project.title = result["title"]
        self.project.scenes = [Scene(text=p) for p in result["paragraphs"]]
        self._rebuild_cards()
        self.projectChanged.emit()
        self.log.emit(f"Script ready · {len(self.project.scenes)} scenes · \"{self.project.title}\"")

        self._set_busy(True, "Picking footage keywords")
        run_async(
            self, llm.generate_terms, self._on_terms, self._fail,
            self.settings, [s.text for s in self.project.scenes], self.project.topic,
        )

    def _on_terms(self, terms: list):
        for scene, group in zip(self.project.scenes, terms):
            scene.terms = group
        for card in self._cards:
            card.refresh()
        self._set_busy(False)
        self.projectChanged.emit()
        self.log.emit("Keywords ready")

    def rewrite_one(self, index: int):
        if not self.project or index >= len(self.project.scenes):
            return
        self._rewrite_index = index
        self._set_busy(True, f"Rewriting scene {index + 1}")
        run_async(
            self, llm.rewrite_paragraph, self._on_rewrite, self._fail,
            self.settings, self.project.topic, self.project.language,
            self.project.tone, [s.text for s in self.project.scenes], index,
        )

    def _on_rewrite(self, result: dict):
        i = self._rewrite_index
        scene = self.project.scenes[i]
        scene.text = result["paragraph"]
        scene.terms = result.get("terms", scene.terms)
        self._cards[i].refresh()
        self._set_busy(False)
        self.projectChanged.emit()
        self.log.emit(f"Scene {i + 1} rewritten")


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
            b.setEnabled(i == 0)
            b.clicked.connect(lambda _=False, idx=i: self.set_step(idx))
            hl.addWidget(b)
            self.step_buttons.append(b)
        hl.addStretch(1)
        root.addWidget(head)

        self.stack = QStackedWidget()
        self.script = ScriptStep(settings)
        self.voice = VoiceStep(settings)
        self.footage = FootageStep(settings)
        self.render = RenderStep(settings)
        for step in (self.script, self.voice, self.footage, self.render):
            step.projectChanged.connect(self.projectChanged.emit)
            step.log.connect(self.log.emit)
            self.stack.addWidget(step)
        self.render.rendered.connect(self.renderReady.emit)
        root.addWidget(self.stack, 1)

        self.script.projectChanged.connect(self._sync_step_availability)
        self.set_step(0)

    def set_step(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.step_buttons):
            b.setChecked(i == index)

    def _sync_step_availability(self):
        """Every later step needs a script to work from."""
        project = self.script.project
        has_scenes = bool(project and project.scenes)
        for i in (1, 2, 3):
            self.step_buttons[i].setEnabled(has_scenes)
        self.voice.set_project(project)
        self.footage.set_project(project)
        self.render.set_project(project)
        if not has_scenes and self.stack.currentIndex() in (1, 2, 3):
            self.set_step(0)

    def refresh_render_readiness(self):
        self.render.set_project(self.script.project)

    def set_project(self, project):
        self.script.set_project(project)
        self._sync_step_availability()   # this hands the project to the voice step

    def shutdown(self):
        self.voice.shutdown()
