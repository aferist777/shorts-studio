"""New ideas — a long video in, several projects out."""

from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QStyle,
    QStyledItemDelegate, QVBoxLayout, QWidget,
)

from app.services import ideas
from app.services.worker import run_async
from app.widgets.narrators_dialog import MEDIA_FILTER
from app.widgets.script_step import LANGUAGES, TONES

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# the dialog opens as a link box and only grows once there is a list to show
SMALL = (560, 210)
LARGE = (900, 760)


class DropRowDelegate(QStyledItemDelegate):
    """Draws a × on the right of every saved analysis and reports clicks on it.

    A combo box has no room for a second widget per row, so the cross is
    painted into the row itself and the click is caught before the item is
    selected — otherwise removing an entry would also load it.
    """

    removeRequested = Signal(int)
    HIT = 26                       # the square at the right edge that counts as the ×

    # taken from the theme rather than the palette: the palette's greys are
    # tuned for a light background and vanish against this one
    IDLE = QColor("#6d6a7a")
    HOT = QColor("#e0736e")

    BACKING = QColor("#1b1b22")

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        box = option.rect.adjusted(option.rect.width() - self.HIT, 0, 0, 0)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.save()
        # the row's own text runs the full width, so the cross needs its own
        # patch of background or it lands on top of the title and disappears
        painter.fillRect(box, self.BACKING)
        font = painter.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.HOT if hovered else self.IDLE)
        painter.drawText(box, Qt.AlignCenter, "×")
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 26))
        size.setWidth(size.width() + self.HIT)
        return size

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.MouseButtonRelease
                and event.pos().x() >= option.rect.right() - self.HIT):
            self.removeRequested.emit(index.row())
            return True
        return super().editorEvent(event, model, option, index)


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


def _span(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m {rest:02d}s" if minutes else f"{rest}s"


class TopicCard(QFrame):
    toggled = Signal()

    def __init__(self, index: int, topic: dict):
        super().__init__()
        self.setObjectName("SceneCard")
        self.index = index
        self.topic = topic

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        self.check = QCheckBox()
        # stateChanged carries an int; a zero-argument Signal cannot take it directly
        self.check.stateChanged.connect(lambda _: self.toggled.emit())
        lay.addWidget(self.check, 0, Qt.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(topic.get("title", ""))
        title.setObjectName("ProjName")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if topic.get("used_by"):
            used = QLabel("USED")
            used.setObjectName("ChipRendered")
            used.setFixedWidth(52)
            used.setAlignment(Qt.AlignCenter)
            head.addWidget(used, 0, Qt.AlignTop)
        body.addLayout(head)

        summary = QLabel(topic.get("summary", ""))
        summary.setObjectName("ProjMeta")
        summary.setWordWrap(True)
        body.addWidget(summary)

        row = QHBoxLayout()
        row.setSpacing(8)
        stamp = QLabel(f"{_clock(topic['start'])} – {_clock(topic['end'])} · "
                       f"{_span(topic['end'] - topic['start'])}")
        stamp.setObjectName("Chip")
        self.name = QLineEdit(topic.get("project_name", ""))
        self.name.setToolTip("Name of the project this topic becomes")
        row.addWidget(stamp, 0)
        row.addWidget(self.name, 1)
        body.addLayout(row)

        lay.addLayout(body, 1)

    def is_checked(self) -> bool:
        return self.check.isChecked()

    def set_checked(self, value: bool):
        """Tick without announcing it — the caller refreshes the count once."""
        self.check.blockSignals(True)
        self.check.setChecked(value)
        self.check.blockSignals(False)

    def payload(self) -> dict:
        return {**self.topic, "project_name": self.name.text().strip()
                or self.topic.get("title", "Untitled")}


class IdeasDialog(QDialog):
    projectsCreated = Signal(list)

    def __init__(self, store, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New ideas")
        self.resize(*SMALL)
        self.store = store
        self.settings = settings
        self._info = {}
        self._cues = []
        self._source = ""
        self._local_file = ""   # set when a video was picked off the disk
        self._cards = []
        self._elapsed = 0
        self._message = ""
        self._cost = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("New ideas")
        title.setObjectName("DlgTitle")
        root.addWidget(title)
        hint = QLabel("Paste a YouTube link, choose a video file with the folder "
                      "button, or pick one you have already analysed. Its topics "
                      "become projects, each keeping its slice of the transcript "
                      "and its timecodes.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        # editable combo: type a new link, or drop down for the ideas base
        self.url = QComboBox()
        self.url.setEditable(True)
        self.url.setInsertPolicy(QComboBox.NoInsert)
        self.url.setCompleter(None)   # or a typed link autocompletes into a saved title
        # long video titles would otherwise stretch the whole dialog
        # (Qt6 dropped the plain AdjustToMinimumContentsLength variant)
        self.url.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.url.setMinimumContentsLength(12)
        self.url.lineEdit().setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url.lineEdit().returnPressed.connect(self.analyse)
        self.url.activated.connect(self._pick_saved)
        self._rows = DropRowDelegate(self.url)
        self._rows.removeRequested.connect(self.forget_saved)
        self.url.view().setItemDelegate(self._rows)
        self.file_btn = QPushButton()
        self.file_btn.setIcon(QIcon(str(ASSETS / "folder.svg")))
        self.file_btn.setIconSize(QSize(17, 17))
        self.file_btn.setFixedWidth(40)
        self.file_btn.setCursor(Qt.PointingHandCursor)
        self.file_btn.setToolTip(
            "Analyse a video already on your disk — the way round YouTube "
            "refusing to hand one over")
        self.file_btn.clicked.connect(self.pick_file)
        self.analyse_btn = QPushButton("Analyse")
        self.analyse_btn.setObjectName("Primary")
        self.analyse_btn.setCursor(Qt.PointingHandCursor)
        self.analyse_btn.clicked.connect(self.analyse)
        url_row.addWidget(self.url, 1)
        url_row.addWidget(self.file_btn)
        url_row.addWidget(self.analyse_btn)
        root.addLayout(url_row)
        self._reload_saved()

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

        self.video_head = QLabel()
        self.video_head.setWordWrap(True)
        self.video_head.setVisible(False)
        root.addWidget(self.video_head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.card_layout = QVBoxLayout(holder)
        self.card_layout.setContentsMargins(0, 2, 6, 2)
        self.card_layout.setSpacing(6)
        self.card_layout.addStretch(1)
        self.scroll.setWidget(holder)
        self.scroll.setVisible(False)
        root.addWidget(self.scroll, 1)

        self.footer = QWidget()
        footer_lay = QHBoxLayout(self.footer)
        footer_lay.setContentsMargins(0, 0, 0, 0)
        footer_lay.setSpacing(8)
        self.language = QComboBox()
        self.language.addItems(LANGUAGES)
        self.language.setCurrentText(settings.get("language", "Russian"))
        self.tone = QComboBox()
        self.tone.addItems(TONES)
        self.tone.setCurrentText(settings.get("tone", "Conversational"))
        self.all_btn = QPushButton("Select all")
        self.all_btn.setCursor(Qt.PointingHandCursor)
        # the label follows the state, so the next press is never a guess
        self.all_btn.setMinimumWidth(96)
        self.all_btn.clicked.connect(self.toggle_all)
        self.create_btn = QPushButton("Create projects")
        self.create_btn.setObjectName("Primary")
        self.create_btn.setCursor(Qt.PointingHandCursor)
        # the label grows when a count appears; the layout won't re-measure on setText
        self.create_btn.setMinimumWidth(150)
        self.create_btn.setEnabled(False)
        self.create_btn.clicked.connect(self.create_projects)
        footer_lay.addWidget(QLabel("Language"))
        footer_lay.addWidget(self.language)
        footer_lay.addWidget(QLabel("Tone"))
        footer_lay.addWidget(self.tone)
        footer_lay.addStretch(1)
        footer_lay.addWidget(self.all_btn)
        footer_lay.addWidget(self.create_btn)
        self.footer.setVisible(False)
        root.addWidget(self.footer)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ---- busy state --------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = ""):
        self.progress.setVisible(busy)
        self.analyse_btn.setEnabled(not busy)
        self.file_btn.setEnabled(not busy)
        self.url.setEnabled(not busy)
        self.create_btn.setEnabled(not busy and bool(self._checked()))
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

    def _fail(self, message: str):
        self._set_busy(False)
        self.status.setText(message)

    # ---- pipeline ----------------------------------------------------------

    def _reload_saved(self):
        """Fill the dropdown from the ideas base without disturbing typed text."""
        typed = self.url.currentText()
        self.url.blockSignals(True)
        self.url.clear()
        for video in ideas.load_index():
            topics = video.get("topics", [])
            used = sum(1 for t in topics if t.get("used_by"))
            minutes = int(video.get("duration", 0)) // 60
            # kept short on purpose: the row also carries a × at its right edge,
            # and a full-length title runs straight under it
            title = video.get("title", "Untitled")
            if len(title) > 42:
                title = title[:41].rstrip() + "…"
            label = f"{title}  ·  {minutes} min · {len(topics)} topics"
            if used:
                label += f", {used} used"
            if video.get("local_path"):
                label += " · file"
            self.url.addItem(label, {"url": video.get("url", ""),
                                     "local_path": video.get("local_path", "")})
        self.url.setCurrentIndex(-1)
        self.url.setEditText(typed)
        self.url.blockSignals(False)

        # the popup inherits the field's width and would elide every title
        metrics = self.url.view().fontMetrics()
        widest = max((metrics.horizontalAdvance(self.url.itemText(i))
                      for i in range(self.url.count())), default=0)
        self.url.view().setMinimumWidth(min(760, widest + 40))

    def forget_saved(self, row: int):
        """Drop one analysed video from the list.

        The transcript is deliberately left where it is: re-analysing costs
        nothing once the speech-to-text has been paid for, and the row can be
        rebuilt from it in seconds.
        """
        videos = ideas.load_index()
        if not 0 <= row < len(videos):
            return
        entry = videos[row]
        used = sum(1 for t in entry.get("topics", []) if t.get("used_by"))
        note = (f"\n\n{used} of its topics already became projects — those stay."
                if used else "")
        confirm = QMessageBox.question(
            self, "Forget this video",
            f"Remove “{entry.get('title', 'Untitled')}” from the ideas base?{note}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return

        ideas.save_index([v for v in videos if v is not entry])
        self.url.hidePopup()
        self._reload_saved()
        self.status.setText(f"Removed “{entry.get('title', '')[:40]}”")

    def _pick_saved(self, index: int):
        stored = self.url.itemData(index) or {}
        # a saved analysis remembers whichever it came from, link or file
        target = stored.get("local_path") or stored.get("url")
        if not target:
            return
        self._local_file = stored.get("local_path", "")
        self.url.setEditText(target)   # the field always shows what will be analysed
        self.analyse()

    def _resize_to(self, size: tuple):
        """Grow in place rather than jumping to a corner of the screen."""
        centre = self.frameGeometry().center()
        self.resize(*size)
        frame = self.frameGeometry()
        frame.moveCenter(centre)
        self.move(frame.topLeft())

    def pick_file(self):
        """Analyse a video from disk — for the ones YouTube will not hand over."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Video file to analyse", "", MEDIA_FILTER)
        if not path:
            return
        self._local_file = path
        # the field always shows what will be analysed, link or path alike
        self.url.setEditText(path)
        self.analyse()

    def analyse(self):
        typed = self.url.currentText().strip()
        # editing the field by hand means the earlier file is no longer meant
        if self._local_file and typed != self._local_file:
            self._local_file = ""

        if not self._local_file and not typed.startswith("http"):
            self.url.setFocus()
            self.status.setText(
                "Paste a link, pick a saved video, or choose a file with the "
                "folder button.")
            return

        self._cost = 0.0
        self._clear_cards()
        self._resize_to(SMALL)
        self._set_busy(True, "Reading the video")
        if self._local_file:
            run_async(self, ideas.prepare_file, self._on_prepared, self._fail,
                      self._local_file, self.settings,
                      on_progress=self._on_progress)
        else:
            run_async(self, ideas.prepare, self._on_prepared, self._fail,
                      typed, self.settings.get("cookies_path", ""),
                      on_progress=self._on_progress)

    def _on_prepared(self, result: dict):
        self._info = result["info"]
        self._cues = result["cues"]
        self._source = result["source"]
        self._show_video_head()

        entry = result.get("entry") or {}
        if entry.get("topics"):
            self._set_busy(False)
            self.status.setText("Already analysed — showing the saved topics")
            self._render_topics(entry["topics"])
            return

        if self._cues:
            self._find_topics()
            return

        self._set_busy(True, "Fetching audio")
        run_async(self, ideas.transcribe_video, self._on_transcribed, self._fail,
                  self._info, self.settings, self.settings.get("cookies_path", ""),
                  on_progress=self._on_progress)

    def _on_transcribed(self, result: dict):
        self._cues = result["cues"]
        self._source = result["source"]
        self._cost = result.get("cost", 0.0)
        self._find_topics()

    def _find_topics(self):
        self._set_busy(True, "Finding topics")
        run_async(self, ideas.find_topics, self._on_topics, self._fail,
                  self._info, self._cues, self.settings, self._source,
                  on_progress=self._on_progress)

    def _on_topics(self, entry: dict):
        self._set_busy(False)
        note = f"{len(entry.get('topics', []))} topics · {self._source}"
        if self._cost:
            note += f" · ${self._cost:.3f}"
        self.status.setText(note)
        self._show_video_head(entry.get("video_summary", ""))
        self._render_topics(entry.get("topics", []))
        self._reload_saved()   # a newly analysed video joins the dropdown

    # ---- rendering ---------------------------------------------------------

    def _show_video_head(self, summary: str = ""):
        info = self._info
        minutes = int(info.get("duration", 0)) // 60
        line = f"<b>{info.get('title','')}</b><br>{info.get('channel','')} · {minutes} min"
        if summary:
            line += f"<br><span style='color:#8b8899'>{summary}</span>"
        self.video_head.setText(line)
        self.video_head.setVisible(True)

    def _clear_cards(self):
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self.scroll.setVisible(False)
        self.footer.setVisible(False)

    def _render_topics(self, topics: list):
        self._clear_cards()
        for i, topic in enumerate(topics):
            card = TopicCard(i, topic)
            card.toggled.connect(self._refresh_create)
            self.card_layout.insertWidget(i, card)
            self._cards.append(card)
        self.scroll.setVisible(bool(topics))
        self.footer.setVisible(bool(topics))
        if topics:
            self._resize_to(LARGE)
        self._refresh_create()

    def _checked(self) -> list:
        return [c for c in self._cards if c.is_checked()]

    def toggle_all(self):
        """Tick every topic, or clear them all if they are already ticked."""
        target = len(self._checked()) < len(self._cards)
        for card in self._cards:
            card.set_checked(target)
        self._refresh_create()

    def _refresh_create(self):
        count = len(self._checked())
        plural = "" if count == 1 else "s"
        self.create_btn.setText(
            f"Create {count} project{plural}" if count else "Create projects")
        self.create_btn.setEnabled(count > 0)
        self.all_btn.setText(
            "Clear all" if self._cards and count == len(self._cards) else "Select all")
        self.all_btn.setEnabled(bool(self._cards))

    # ---- creation ----------------------------------------------------------

    def create_projects(self):
        video = {"url": self._info.get("url", ""), "video_id": self._info.get("video_id", ""),
                 "title": self._info.get("title", "")}
        created = []
        for card in self._checked():
            project = self.store.create_from_topic(
                video, card.payload(),
                self.language.currentText(), self.tone.currentText())
            ideas.mark_used(video["video_id"], card.index, project.id)
            created.append(project.id)
        self.projectsCreated.emit(created)
        self.accept()
