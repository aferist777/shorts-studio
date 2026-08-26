"""The script step — topic in, a hook, then the narration as editable scenes.

Lives apart from the workspace pane because the media step now holds it: one
step covers writing, voicing and picturing, in that order.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from app.models_data import Scene
from app.services import llm, narrators
from app.services.worker import run_async

LANGUAGES = ["Russian", "English", "Spanish", "German", "French", "Portuguese"]
TONES = ["Conversational", "Documentary", "Punchy", "Calm", "Provocative", "Wry"]

HOOKS_LABEL = "Generate hooks"
SCRIPT_LABEL = "Generate script"


class GrowingTextEdit(QTextEdit):
    """Sizes itself to its content so scene cards don't need inner scrollbars."""

    fitted = Signal(int)   # the height just settled on — for anything standing beside it

    def __init__(self, text=""):
        super().__init__(text)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().contentsChanged.connect(self._fit)
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        height = max(52, int(self.document().size().height()) + 18)
        self.setFixedHeight(height)
        self.fitted.emit(height)

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

        self._controls = [rewrite, self.editor]

    def _on_edit(self):
        self.scene.text = self.editor.toPlainText()
        self.changed.emit()

    def refresh(self):
        if self.editor.toPlainText() != self.scene.text:
            self.editor.blockSignals(True)
            self.editor.setPlainText(self.scene.text)
            self.editor.blockSignals(False)

    def set_locked(self, locked: bool):
        for w in self._controls:
            w.setEnabled(not locked)


class HookCard(QFrame):
    chosen = Signal(str)

    def __init__(self, hook: dict):
        super().__init__()
        self.setObjectName("ClipTile")
        self.setCursor(Qt.PointingHandCursor)
        self.text = hook.get("text", "")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        kind = QLabel(hook.get("kind", "")[:28])
        kind.setObjectName("Chip")
        kind.setFixedWidth(120)
        kind.setAlignment(Qt.AlignCenter)
        kind.setWordWrap(True)
        body = QLabel(self.text)
        body.setWordWrap(True)
        lay.addWidget(kind, 0, Qt.AlignVCenter)
        lay.addWidget(body, 1)

    def mousePressEvent(self, event):
        self.chosen.emit(self.text)
        super().mousePressEvent(event)


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

        # the title line, with the way back to the transcript on the same row —
        # only projects spawned from a video have one
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("What is the video about?")
        self.topic.returnPressed.connect(self._on_hook_button)
        self.topic.textChanged.connect(self._sync_hook_button)
        self.source_btn = QPushButton("Source text…")
        self.source_btn.setCursor(Qt.PointingHandCursor)
        self.source_btn.clicked.connect(self._show_source_text)
        self.source_btn.setVisible(False)
        title_row.addWidget(self.topic, 1)
        title_row.addWidget(self.source_btn)
        root.addLayout(title_row)

        cap = QLabel("HOOK — the first line said out loud")
        cap.setObjectName("FieldLabel")
        root.addWidget(cap)

        # one button for the whole step, and which job it does is written on it:
        # nothing to work from yet -> hooks, a hook in hand -> the script
        hook_row = QHBoxLayout()
        hook_row.setSpacing(8)
        self.hook = GrowingTextEdit()
        self.hook.setPlaceholderText("Write it yourself, or let the model suggest five.")
        self.hook.textChanged.connect(self._on_hook_changed)
        self.hook_btn = QPushButton()
        self.hook_btn.setObjectName("Primary")
        self.hook_btn.setCursor(Qt.PointingHandCursor)
        self.hook_btn.clicked.connect(self._on_hook_button)
        # both captions have to fit, or the button jumps width as you type
        metrics = self.hook_btn.fontMetrics()
        self.hook_btn.setFixedWidth(
            max(metrics.horizontalAdvance(t) for t in (HOOKS_LABEL, SCRIPT_LABEL)) + 34)
        # it stands beside a field that grows with its text, so it takes its
        # height from the field rather than from the row
        self.hook.fitted.connect(self.hook_btn.setFixedHeight)
        hook_row.addWidget(self.hook, 1)
        hook_row.addWidget(self.hook_btn, 0, Qt.AlignTop)
        root.addLayout(hook_row)

        # candidates appear here after Generate hooks, and vanish once one is chosen
        self.hook_box = QWidget()
        self.hook_layout = QVBoxLayout(self.hook_box)
        self.hook_layout.setContentsMargins(0, 0, 0, 0)
        self.hook_layout.setSpacing(5)
        self.hook_box.setVisible(False)
        root.addWidget(self.hook_box)

        self.opts_box = QWidget()
        opts = QHBoxLayout(self.opts_box)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(8)
        self.language = QComboBox()
        self.language.addItems(LANGUAGES)
        self.paragraphs = QSpinBox()
        # a short is no longer pinned to a minute — more scenes, longer video
        self.paragraphs.setRange(2, 30)
        self.tone = QComboBox()
        self.tone.addItems(TONES)
        self.narrator = QComboBox()
        self.narrator.setToolTip("How the script is written — not the voice that reads it")
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
            ("NARRATOR", self.narrator, 1),
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
        root.addWidget(self.opts_box)

        self.reload_narrators()
        self._load_settings_into_widgets()
        self.narrator.currentIndexChanged.connect(self._on_narrator_changed)
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

        self._hook_save = QTimer(self)
        self._hook_save.setSingleShot(True)
        self._hook_save.setInterval(600)
        self._hook_save.timeout.connect(self.projectChanged.emit)

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

    def reload_narrators(self):
        """Called on start and whenever the narrators dialog changes anything."""
        wanted = self.narrator.currentData() or (
            self.project.narrator if self.project else "neutral")
        self.narrator.blockSignals(True)
        self.narrator.clear()
        for narrator_id, name in narrators.choices():
            self.narrator.addItem(name, narrator_id)
        index = self.narrator.findData(wanted)
        self.narrator.setCurrentIndex(max(0, index))
        self.narrator.blockSignals(False)

    def _on_narrator_changed(self):
        if self.project:
            self.project.narrator = self.narrator.currentData() or "neutral"
            self.projectChanged.emit()

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

    def show_options(self, on: bool):
        """The seven writing dials.

        Off the screen once the script is settled: they are no use then, and
        together they are what kept this pane from ever being made narrower.
        """
        self.opts_box.setVisible(on)

    # ---- project binding ---------------------------------------------------

    def set_project(self, project):
        self.project = project
        self._clear_hook_cards()
        self.topic.setText(project.topic if project else "")
        self.hook.blockSignals(True)
        self.hook.setPlainText(project.hook if project else "")
        self.hook.blockSignals(False)
        self._sync_hook_button()
        if project:
            if project.language in LANGUAGES:
                self.language.setCurrentText(project.language)
            if project.tone in TONES:
                self.tone.setCurrentText(project.tone)
            self.narrator.blockSignals(True)
            index = self.narrator.findData(project.narrator or "neutral")
            self.narrator.setCurrentIndex(max(0, index))
            self.narrator.blockSignals(False)
        self._refresh_source_button()
        self._rebuild_cards()

    # ---- hooks -------------------------------------------------------------

    def _sync_hook_button(self):
        """What the button says is what it will do with what is in the field."""
        has_hook = bool(self.hook.toPlainText().strip())
        self.hook_btn.setText(SCRIPT_LABEL if has_hook else HOOKS_LABEL)
        self.hook_btn.setToolTip(
            "Write the script from this hook" if has_hook
            else "Five opening lines to choose from")
        self.hook_btn.setEnabled(bool(self.topic.text().strip()))

    def _on_hook_button(self):
        if self.hook.toPlainText().strip():
            self.generate()
        else:
            self.suggest_hooks()

    def _on_hook_changed(self):
        if self.project:
            self.project.hook = self.hook.toPlainText().strip()
            self._hook_save.start()   # debounced: saving per keystroke rebuilds the panes
        self._sync_hook_button()

    def _clear_hook_cards(self):
        while self.hook_layout.count():
            item = self.hook_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.hook_box.setVisible(False)

    def suggest_hooks(self):
        if not self.project:
            return
        topic = self.topic.text().strip()
        if not topic:
            self.topic.setFocus()
            return
        self.project.topic = topic
        self._clear_hook_cards()
        self._set_busy(True, "Writing hooks")
        run_async(
            self, llm.generate_hooks, self._on_hooks, self._fail,
            self.settings, topic, self.language.currentText(),
            self.tone.currentText(), self.project.narrator, self.project.source_text,
        )

    def _on_hooks(self, hooks: list):
        self._clear_hook_cards()
        for hook in hooks:
            card = HookCard(hook)
            card.chosen.connect(self._take_hook)
            self.hook_layout.addWidget(card)
        self.hook_box.setVisible(True)
        self._set_busy(False)
        self.log.emit(f"{len(hooks)} hooks · pick one or edit it")

    def _take_hook(self, text: str):
        self.hook.setPlainText(text)
        self._clear_hook_cards()
        self.projectChanged.emit()

    def _refresh_source_button(self):
        """Where this project came from, on the button rather than in a bar of
        its own — the line was a whole row tall and read once, at most."""
        project = self.project
        if not project or not project.source_text:
            self.source_btn.setVisible(False)
            return
        start, end = int(project.source_start), int(project.source_end)
        clock = lambda s: f"{s // 60:02d}:{s % 60:02d}"
        words = len(project.source_text.split())
        self.source_btn.setToolTip(
            f"From “{project.source_title}” · {clock(start)}–{clock(end)} · {words} words")
        self.source_btn.setVisible(True)

    def _show_source_text(self):
        if not self.project:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.project.source_title or "Source text")
        dialog.resize(720, 560)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        head = QLabel(self.project.source_url)
        head.setObjectName("Hint")
        lay.addWidget(head)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(self.project.source_text)
        lay.addWidget(view, 1)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        dialog.exec()

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
        self.hook_btn.setEnabled(not busy and bool(self.topic.text().strip()))
        for w in (self.topic, self.hook, self.source_btn, self.language,
                  self.paragraphs, self.tone, self.provider, self.model, self.effort):
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
        hook = self.hook.toPlainText().strip()
        if not topic:
            self.topic.setFocus()
            return
        if not hook:
            self.hook.setFocus()
            return

        self.project.topic = topic
        self.project.hook = hook
        self.project.language = self.language.currentText()
        self.project.tone = self.tone.currentText()
        self._persist()
        self._clear_hook_cards()

        source = self.project.source_text
        self._set_busy(True, "Writing script")
        self.log.emit(f"Script · {self.model.currentText()} · "
                      f"{'from transcript' if source else 'from topic'} · {topic}")
        run_async(
            self, llm.generate_script, self._on_script, self._fail,
            self.settings, topic, self.project.language, self.paragraphs.value(),
            self.project.tone, hook, self.project.narrator, source,
        )

    def _on_script(self, result: dict):
        self.project.title = result["title"]
        self.project.scenes = [Scene(text=p) for p in result["paragraphs"]]
        self._rebuild_cards()
        self.projectChanged.emit()
        self.log.emit(f"Draft · {len(self.project.scenes)} scenes · \"{self.project.title}\"")

        # the cleaning pass runs every time, not behind a button
        self._set_busy(True, "Cleaning the draft")
        run_async(
            self, llm.humanize, self._on_humanized, self._fail,
            self.settings, [s.text for s in self.project.scenes], self.project.narrator,
        )

    def _on_humanized(self, paragraphs: list):
        changed = 0
        for scene, text in zip(self.project.scenes, paragraphs):
            if text != scene.text:
                changed += 1
            scene.text = text
        for card in self._cards:
            card.refresh()
        self._set_busy(False)
        self.projectChanged.emit()
        self.log.emit(f"Cleaned · {changed} of {len(paragraphs)} paragraphs touched")

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
        self._cards[i].refresh()
        self._set_busy(False)
        self.projectChanged.emit()
        self.log.emit(f"Scene {i + 1} rewritten")
