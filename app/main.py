"""Shorts Studio — desktop entry point."""

import shutil
import sys
from pathlib import Path

# allow running as `python app/main.py` or `python -m app.main`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QMainWindow, QMessageBox, QSplitter,
    QWidget,
)

from app import config, store
from app.paths import PROJECTS_DIR, find_ffmpeg
from app.services import kie_images, worker
from app.services.ideas import fragments, youtube
from app.services.worker import run_async
from app.store import Store
from app.widgets.narrators_dialog import MEDIA_FILTER
from app.theme import qss
from app.version import APP_NAME, APP_VERSION
from app.widgets.ideas_dialog import IdeasDialog
from app.widgets.library_dialog import LibraryDialog
from app.widgets.narrators_dialog import NarratorsDialog
from app.widgets.preview import PreviewPane
from app.widgets.project_list import ProjectListPane
from app.widgets.settings_dialog import SettingsDialog
from app.widgets.workspace import WorkspacePane


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 660)

        self.store = Store()
        self.settings = config.load_settings()
        self._awaiting_source = []   # projects whose fragment still needs a file
        self._sash_restored = False
        self._build_menubar()

        central = QWidget()
        central.setObjectName("Root")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(5)
        self.splitter.setChildrenCollapsible(False)

        self.left = ProjectListPane(self.store)
        self.center = WorkspacePane(self.settings)
        self.right = PreviewPane()

        # Without these the splitter asks each pane how narrow it may go and
        # gets 369 + 1310 + 139 back — more than the window has — so it sits
        # over-constrained and refuses to move at all. An explicit minimum
        # overrides that ask and is what makes the handles draggable.
        self.left.setMinimumWidth(220)
        self.center.setMinimumWidth(560)
        self.right.setMinimumWidth(240)

        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.center)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setStretchFactor(2, 3)
        self.splitter.setSizes(self._saved_sash() or [260, 720, 420])

        lay.addWidget(self.splitter)
        self.setCentralWidget(central)

        self.left.addRequested.connect(self.new_project)
        self.left.projectSelected.connect(self.open_project)
        self.left.deleteRequested.connect(self.delete_project)
        self.left.libraryRequested.connect(self.open_library)
        self.left.ideasRequested.connect(self.open_ideas)
        self.center.projectChanged.connect(self.on_project_changed)
        self.center.log.connect(self.right.append_log)
        self.center.renderReady.connect(self.right.set_video)

        if not self.store.projects:
            self.new_project()
        else:
            self.left.select(self.store.projects[0].id)

        if not find_ffmpeg(self.settings.get("ffmpeg_path", "")):
            self.right.append_log("ffmpeg not found — set it in Settings before rendering.")

        self._offer_orphan_cleanup()
        self._collect_pictures()

    def _collect_pictures(self):
        """Pictures asked for last time and never collected.

        A drawing job lives on kie's side. If this window went away between
        asking and being handed the result, the picture was still drawn and
        still charged — so the task ids are on disk and this asks after them.
        """
        if not kie_images.pending():
            return
        self.right.append_log(
            f"{len(kie_images.pending())} pictures were still being drawn when "
            "the app last closed — asking after them…")
        run_async(self, kie_images.collect, self._on_collected,
                  self.right.append_log)

    def _on_collected(self, result: dict):
        if result["got"]:
            self.right.append_log(
                f"{len(result['got'])} pictures arrived after the app closed and "
                f"have been downloaded: {', '.join(result['got'][:6])}"
                + (" …" if len(result["got"]) > 6 else ""))
        if result["waiting"]:
            self.right.append_log(
                f"{result['waiting']} are still being drawn — they will be "
                "collected next time.")
        if result["lost"]:
            self.right.append_log(f"{result['lost']} came to nothing.")
        self.center.refresh_render_readiness()

    # ---- layout ------------------------------------------------------------

    def _saved_sash(self) -> list:
        """Pane widths from last time, or nothing if they are unusable."""
        sizes = self.settings.get("sash_sizes") or []
        if len(sizes) != 3:
            return []
        try:
            sizes = [int(s) for s in sizes]
        except (TypeError, ValueError):
            return []
        return sizes if all(s > 0 for s in sizes) else []

    def showEvent(self, event):
        """Widths are restored here, not in the constructor.

        Set before the window is maximised they are only a hint: the splitter
        hands the extra width out by stretch factor, and a saved 300/880/500
        comes back as 369/1310/231. Once the final geometry is in, they land.
        """
        super().showEvent(event)
        if self._sash_restored:
            return
        self._sash_restored = True
        sizes = self._saved_sash()
        if sizes:
            QTimer.singleShot(0, lambda: self.splitter.setSizes(sizes))

    def _save_sash(self):
        """Reread from disk before writing: the steps hold their own settings
        dict and save through it, so writing ours wholesale would undo theirs."""
        settings = config.load_settings()
        settings["sash_sizes"] = self.splitter.sizes()
        config.save_settings(settings)

    def _offer_orphan_cleanup(self):
        """Folders left behind by deletions that predate this version.

        Asked, never assumed — these are files on someone else's disk, and the
        index being briefly out of step is not a licence to delete them.
        """
        orphans = store.orphan_dirs()
        if not orphans:
            return
        total = sum(store.dir_size(d) for d in orphans)
        answer = QMessageBox.question(
            self, "Leftover folders",
            f"{len(orphans)} folders belong to projects that no longer exist "
            f"({total / 1e6:.1f} MB). Deleting a project used to leave its "
            "files behind. Remove them?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        for folder in orphans:
            shutil.rmtree(folder, ignore_errors=True)
        self.right.append_log(
            f"Removed {len(orphans)} leftover folders ({total / 1e6:.1f} MB).")

    def _build_menubar(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        file_menu.addAction("New project", self.new_project)
        file_menu.addAction("New ideas…", self.open_ideas)
        file_menu.addAction("Duplicate script", self.duplicate_project)
        file_menu.addSeparator()
        file_menu.addAction("Videos…", self.open_library).setShortcut("Ctrl+L")
        file_menu.addAction("Narrators…", self.open_narrators).setShortcut("Ctrl+N")
        file_menu.addSeparator()
        file_menu.addAction("Settings…", self.open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        help_menu = mb.addMenu("Help")
        help_menu.addAction("About", self.about)

    # ---- projects ----------------------------------------------------------

    @property
    def current(self):
        return self.store.get(self.left._selected)

    def new_project(self):
        project = self.store.create()
        self.left.refresh()
        self.left.select(project.id)
        self.center.script.topic.setFocus()

    def open_project(self, project_id: str):
        project = self.store.get(project_id)
        self.center.set_project(project)
        self.right.set_project(project)

    def delete_project(self, project_id: str):
        project = self.store.get(project_id)
        if project is None:
            return
        size = store.dir_size(PROJECTS_DIR / project_id)
        weight = f" and its {size / 1e6:.0f} MB of files" if size > 1e6 else " and its files"
        confirm = QMessageBox.question(
            self, "Delete project",
            f"Delete “{project.title}”{weight}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.store.delete(project_id)
        self.left.refresh()
        if not self.store.projects:
            self.new_project()

    def on_project_changed(self):
        project = self.current
        if project:
            self.store.touch(project)
        self.right.refresh()
        self.left.refresh()
        # voicing or attaching footage can be what makes a render possible
        self.center.refresh_render_readiness()

    # ---- misc --------------------------------------------------------------

    def duplicate_project(self):
        project = self.current
        if project is None:
            return
        copy = self.store.duplicate(project.id)
        self.left.refresh()
        self.left.select(copy.id)
        self.right.append_log(f"Duplicated “{project.title}” — script only, no media.")

    def open_ideas(self):
        dialog = IdeasDialog(self.store, self.settings, self)
        dialog.projectsCreated.connect(self._on_projects_created)
        dialog.exec()

    def _on_projects_created(self, project_ids: list):
        self.left.refresh()
        if project_ids:
            self.left.select(project_ids[0])
        self.right.append_log(f"Created {len(project_ids)} projects from a video.")
        self.fetch_fragments(project_ids)

    # ---- source fragments --------------------------------------------------

    def fetch_fragments(self, project_ids: list, local_file: str = ""):
        """Give each new project its own slice of the video it came from.

        Runs off on its own once the projects exist: the scripts are already
        written from the transcript and do not wait on any of this.
        """
        projects = [p for p in (self.store.get(i) for i in project_ids)
                    if p is not None and p.source_end > p.source_start]
        if not projects:
            return

        self._awaiting_source = [p.id for p in projects]
        self.right.append_log(
            f"Fetching the video to cut {len(projects)} fragments…")
        run_async(
            self, fragments.build, self._on_fragments, self._on_fragments_failed,
            projects, self.settings, local_file,
            on_progress=self.right.append_log,
        )

    def _on_fragments(self, results: list):
        for project, path, error in results:
            stored = self.store.get(project.id)
            if stored is None:
                continue        # deleted while the download was running
            if path:
                stored.fragment_path = path
                self.right.append_log(
                    f"“{stored.title}” — fragment ready "
                    f"({Path(path).stat().st_size / 1e6:.0f} MB).")
            else:
                self.right.append_log(f"“{stored.title}” — {error}")
        self.store.save()
        self.left.refresh()

    def _on_fragments_failed(self, message: str):
        self.right.append_log(message)
        if youtube.BOT_CHECK_MARK not in message:
            return
        answer = QMessageBox.question(
            self, "YouTube would not hand over the video",
            "The scripts are ready — only the video fragments are missing.\n\n"
            "Download the video yourself and pick it here, and every project "
            "from this analysis gets its fragment cut from it.",
            QMessageBox.Open | QMessageBox.Cancel, QMessageBox.Open,
        )
        if answer != QMessageBox.Open:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "The video these projects came from", "", MEDIA_FILTER)
        if path:
            self.fetch_fragments(self._awaiting_source, path)

    def open_narrators(self):
        dialog = NarratorsDialog(self.settings, self)
        dialog.changed.connect(self.center.reload_narrators)
        dialog.exec()
        self.center.reload_narrators()

    def open_library(self):
        dialog = LibraryDialog(self.store, self.settings, self)
        dialog.playRequested.connect(self.right.set_video)
        dialog.storeChanged.connect(self._after_library_change)
        dialog.exec()
        self._after_library_change()

    def _after_library_change(self):
        self.left.refresh()
        self.center.refresh_render_readiness()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = config.load_settings()
            self.right.append_log("Settings saved.")

    def closeEvent(self, event):
        self._save_sash()
        self.center.shutdown()
        self.right.shutdown()
        worker.shutdown_all()
        super().closeEvent(event)

    def about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Topic in, vertical short out — with a stop at every step.",
        )


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(qss())
    window = MainWindow()
    # the work is three panes wide — anything less than the whole screen means
    # scrolling something that did not need to scroll
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
