"""Narrators — build a voice from real writing by one author.

A narrator is how the script is written. The TTS voice is how it is read. They
are different things and live on different steps.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.models_data import new_id
from app.services import llm, narrators, prompts
from app.services.worker import run_async


class SampleRow(QFrame):
    removeRequested = Signal(int)

    def __init__(self, index: int, sample: dict):
        super().__init__()
        self.setObjectName("SceneCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 7)
        lay.setSpacing(8)

        kind = QLabel("link" if sample.get("kind") == "link" else "text")
        kind.setObjectName("Chip")
        kind.setFixedWidth(46)
        kind.setAlignment(Qt.AlignCenter)

        label = QLabel(sample.get("label") or sample.get("text", "")[:70])
        label.setObjectName("ProjMeta")
        label.setWordWrap(True)

        words = QLabel(f"{len(sample.get('text', '').split())} words")
        words.setObjectName("ProjMeta")
        words.setFixedWidth(80)
        words.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        drop = QPushButton("×")
        drop.setObjectName("GBtn")
        drop.setToolTip("Remove this sample")
        drop.clicked.connect(lambda: self.removeRequested.emit(index))

        lay.addWidget(kind, 0, Qt.AlignVCenter)
        lay.addWidget(label, 1)
        lay.addWidget(words, 0, Qt.AlignVCenter)
        lay.addWidget(drop, 0, Qt.AlignVCenter)


class NarratorsDialog(QDialog):
    changed = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Narrators")
        self.resize(980, 700)
        self.settings = settings
        self.current = None
        self._rows = []
        self._elapsed = 0
        self._message = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Narrators")
        title.setObjectName("DlgTitle")
        hint = QLabel("How the script is written — not the voice that reads it.")
        hint.setObjectName("Hint")
        head.addWidget(title)
        head.addWidget(hint)
        head.addStretch(1)
        add = QPushButton("New narrator")
        add.setObjectName("AddBtn")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.create)
        head.addWidget(add)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.list = QListWidget()
        self.list.setFixedWidth(230)
        self.list.currentRowChanged.connect(self._select_row)
        body.addWidget(self.list)

        right = QVBoxLayout()
        right.setSpacing(8)

        self.name = QLineEdit()
        self.name.setPlaceholderText("Narrator name")
        self.name.editingFinished.connect(self._rename)
        right.addWidget(self.name)

        cap = QLabel("SAMPLES — writing by this author")
        cap.setObjectName("FieldLabel")
        right.addWidget(cap)

        self.sample_scroll = QScrollArea()
        self.sample_scroll.setWidgetResizable(True)
        self.sample_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # without a floor the profile below squeezes this to a single visible row
        self.sample_scroll.setMinimumHeight(160)
        self.sample_scroll.setMaximumHeight(220)
        holder = QWidget()
        self.sample_layout = QVBoxLayout(holder)
        self.sample_layout.setContentsMargins(0, 0, 6, 0)
        self.sample_layout.setSpacing(5)
        self.sample_layout.addStretch(1)
        self.sample_scroll.setWidget(holder)
        right.addWidget(self.sample_scroll)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.paste_btn = QPushButton("Paste text…")
        self.paste_btn.clicked.connect(self.add_text)
        self.link_btn = QPushButton("From a video link…")
        self.link_btn.setToolTip("Downloads the audio and transcribes it as a sample")
        self.link_btn.clicked.connect(self.add_link)
        self.analyse_btn = QPushButton("Analyse style")
        self.analyse_btn.setObjectName("Primary")
        self.analyse_btn.setMinimumWidth(130)
        self.analyse_btn.clicked.connect(self.analyse)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_current)
        buttons.addWidget(self.paste_btn)
        buttons.addWidget(self.link_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.analyse_btn)
        right.addLayout(buttons)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("Hint")
        status_row.addWidget(self.progress, 1)
        status_row.addWidget(self.status)
        right.addLayout(status_row)

        cap2 = QLabel("PROFILE")
        cap2.setObjectName("FieldLabel")
        right.addWidget(cap2)
        self.profile = QTextEdit()
        self.profile.setReadOnly(True)
        self.profile.setPlaceholderText(
            "Add a few thousand words by one author, then analyse. The profile "
            "describes how they write, and every generated script follows it.")
        right.addWidget(self.profile, 1)

        body.addLayout(right, 1)
        root.addLayout(body, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self.reload()

    # ---- list --------------------------------------------------------------

    def reload(self, select_id: str = ""):
        self.list.blockSignals(True)
        self.list.clear()
        entries = [dict(narrators.NEUTRAL)] + narrators.load()
        for entry in entries:
            item = QListWidgetItem(entry["name"])
            item.setData(Qt.UserRole, entry["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)

        target = select_id or (self.current or {}).get("id") or "neutral"
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == target:
                self.list.setCurrentRow(i)
                return
        self.list.setCurrentRow(0)

    def _select_row(self, row: int):
        if row < 0:
            return
        self.current = narrators.get(self.list.item(row).data(Qt.UserRole))
        self._render()

    def _render(self):
        builtin = bool(self.current.get("builtin"))
        self.name.setText(self.current.get("name", ""))
        for widget in (self.name, self.paste_btn, self.link_btn,
                       self.analyse_btn, self.delete_btn):
            widget.setEnabled(not builtin)

        self._clear_samples()
        if builtin:
            self.profile.setPlainText(
                "Built in. Writes plainly and applies the anti-machine rules — "
                "no inflated significance, no rule of three, no participle tails.\n\n"
                "A narrator you build from real writing replaces those rules with "
                "its own profile.")
            self.status.setText("")
            return

        samples = self.current.get("samples", [])
        for i, sample in enumerate(samples):
            row = SampleRow(i, sample)
            row.removeRequested.connect(self.remove_sample)
            self.sample_layout.insertWidget(i, row)
            self._rows.append(row)

        profile = self.current.get("profile")
        self.profile.setPlainText(
            prompts.render_profile(profile) if profile
            else "Not analysed yet.")
        total = narrators.word_count(samples)
        short = total < narrators.MIN_SAMPLE_WORDS
        self.status.setText(
            f"{len(samples)} samples · {total} words"
            + (f" · needs at least {narrators.MIN_SAMPLE_WORDS}" if short else ""))

    def _clear_samples(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    # ---- editing -----------------------------------------------------------

    def create(self):
        name, ok = QInputDialog.getText(self, "New narrator", "Name")
        if not ok or not name.strip():
            return
        narrator = {"id": new_id(), "name": name.strip(), "samples": [], "profile": None}
        narrators.put(narrator)
        self.changed.emit()
        self.reload(narrator["id"])

    def _rename(self):
        if not self.current or self.current.get("builtin"):
            return
        name = self.name.text().strip()
        if name and name != self.current["name"]:
            self.current["name"] = name
            narrators.put(self.current)
            self.changed.emit()
            self.reload(self.current["id"])

    def _store_samples(self, samples: list):
        self.current["samples"] = samples
        narrators.put(self.current)
        self._render()

    def add_text(self):
        text, ok = QInputDialog.getMultiLineText(
            self, "Paste a sample", "Writing by this author")
        if not ok or not text.strip():
            return
        sample = {"kind": "text", "label": text.strip()[:70], "text": text.strip()}
        self._store_samples(self.current.get("samples", []) + [sample])

    def add_link(self):
        url, ok = QInputDialog.getText(self, "Sample from a video",
                                       "Link — the audio is transcribed as a sample")
        if not ok or not url.strip().startswith("http"):
            return
        self._set_busy(True, "Fetching the video")
        run_async(self, narrators.transcribe_link, self._on_link, self._fail,
                  url.strip(), self.settings, self.settings.get("cookies_path", ""),
                  on_progress=self._on_progress)

    def _on_link(self, sample: dict):
        self._set_busy(False)
        self._store_samples(self.current.get("samples", []) + [sample])

    def remove_sample(self, index: int):
        samples = list(self.current.get("samples", []))
        if 0 <= index < len(samples):
            del samples[index]
            self._store_samples(samples)

    def delete_current(self):
        if not self.current or self.current.get("builtin"):
            return
        confirm = QMessageBox.question(
            self, "Delete narrator",
            f"Delete “{self.current['name']}”? Projects using it fall back to Neutral.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        narrators.delete(self.current["id"])
        self.current = None
        self.changed.emit()
        self.reload("neutral")

    # ---- analysis ----------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        for widget in (self.list, self.name, self.paste_btn, self.link_btn,
                       self.analyse_btn, self.delete_btn):
            widget.setEnabled(not busy)
        if busy:
            self._elapsed = 0
            self._message = message
            self.status.setText(f"{message} · 0s")
            self._timer.start()
        else:
            self._timer.stop()
            if self.current:
                self._render()

    def _tick(self):
        self._elapsed += 1
        self.status.setText(f"{self._message} · {self._elapsed}s")

    def _on_progress(self, label: str):
        self._message = label
        self.status.setText(f"{label} · {self._elapsed}s")

    def _fail(self, message: str):
        self._set_busy(False)
        self.status.setText(message[:160])

    def analyse(self):
        samples = self.current.get("samples", [])
        total = narrators.word_count(samples)
        if total < narrators.MIN_SAMPLE_WORDS:
            self.status.setText(
                f"Only {total} words. Under {narrators.MIN_SAMPLE_WORDS} the profile "
                "comes back generic — add more.")
            return
        self._set_busy(True, "Reading the samples")
        run_async(self, llm.analyse_narrator, self._on_profile, self._fail,
                  self.settings, samples)

    def _on_profile(self, profile: dict):
        self.current["profile"] = profile
        narrators.put(self.current)
        self._set_busy(False)
        self.changed.emit()
