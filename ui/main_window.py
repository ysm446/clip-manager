from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QPlainTextEdit,
    QLabel,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTabWidget,
    QSplitter,
)
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from core.settings import AppSettings
from core.libraries import LibraryManager
from core.library import Library
from core.database import LibraryDatabase
from core.scan_worker import ScanWorker
from core.enrich_worker import EnrichWorker
from core.download_queue import DownloadQueue, DownloadRequest
from ui.library_view import LibraryView
from ui.filter_panel import FilterPanel
from ui.queue_view import QueueView
from ui.player_widget import PlayerWidget
from ui.download_dialog import DownloadDialog
from ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        # --- Library state ---
        self._libraries = LibraryManager()
        self._active_lib: Library | None = None
        self._db: LibraryDatabase | None = None  # main-thread connection
        self._scan_worker: ScanWorker | None = None
        self._enrich_worker: EnrichWorker | None = None
        # --- Download queue ---
        self._queue = DownloadQueue()
        self._queue.download_succeeded.connect(self._on_download_succeeded)
        self._init_ui()
        self._load_active_library()
        self._restore_geometry()
        self.setWindowTitle("Clip Manager")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        # --- Library tab: [ folder/tag tree | clip list | player ] ---
        self._filter_panel = FilterPanel()
        self._library_view = LibraryView()
        self._player = PlayerWidget()
        self._library_view.play_requested.connect(self._player.play)
        self._library_view.open_external_requested.connect(self._open_external)
        self._player.open_external_requested.connect(self._open_external)
        self._library_view.enrich_requested.connect(self._enrich_library)
        self._library_view.open_location_requested.connect(self._open_location)
        self._library_view.library_modified.connect(self._update_library_status)
        self._filter_panel.filter_changed.connect(self._on_filter_changed)
        self._filter_panel.library_changed.connect(self._library_view.refresh)
        self._filter_panel.download_here_requested.connect(self._open_download_dialog)
        self._filter_panel.open_folder_requested.connect(self._open_folder)

        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.addWidget(self._filter_panel)
        library_split.addWidget(self._library_view)
        library_split.addWidget(self._player)
        library_split.setStretchFactor(0, 0)
        library_split.setStretchFactor(1, 1)
        library_split.setStretchFactor(2, 1)
        library_split.setSizes([240, 640, 680])
        self._tabs.addTab(library_split, "Library")

        # --- Queue tab: [ queue table | log ] ---
        queue_tab = QWidget()
        qlayout = QVBoxLayout(queue_tab)
        qlayout.setContentsMargins(0, 0, 0, 0)
        self._queue_view = QueueView()
        self._queue_view.set_queue(self._queue)
        qlayout.addWidget(self._queue_view, stretch=1)
        qlayout.addWidget(QLabel("Log:"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setFixedHeight(140)
        qlayout.addWidget(self._log)
        self._tabs.addTab(queue_tab, "Queue")

        # --- Menu bar ---
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction("Settings...").triggered.connect(self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit").triggered.connect(self.close)

        library_menu = self.menuBar().addMenu("Library")
        library_menu.addAction("Open / Create Library...").triggered.connect(
            self._open_library
        )
        library_menu.addAction("Switch Library...").triggered.connect(
            self._switch_library
        )
        library_menu.addSeparator()
        library_menu.addAction("Download to library root...").triggered.connect(
            self._download_to_root
        )
        library_menu.addAction("Rescan Library").triggered.connect(self._rescan_library)

        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------------
    # Download (queue)
    # ------------------------------------------------------------------

    @Slot(str)
    def _open_download_dialog(self, dest_dir: str) -> None:
        """「ここにダウンロード」: ポップアップを開き、キューに積む。"""
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library first.")
            return
        dlg = DownloadDialog(self._settings, dest_dir, self)
        if not dlg.exec():
            return
        v = dlg.values()
        req = DownloadRequest(
            url=v["url"], dest_dir=v["dest_dir"], quality=v["quality"],
            codec=v["codec"], write_subtitles=v["write_subtitles"],
            save_format=v["save_format"],
        )
        self._queue.add(req)
        self._on_log(f"[Queue] Added: {req.url}  →  {req.dest_dir}")
        self._tabs.setCurrentWidget(self._tabs.widget(1))  # Queue タブへ

    @Slot()
    def _download_to_root(self) -> None:
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library first.")
            return
        self._open_download_dialog(str(self._active_lib.root))

    @Slot(object, dict)
    def _on_download_succeeded(self, request, payload: dict) -> None:
        """完了ファイルをアクティブライブラリへ登録する（主スレッド）。"""
        if self._active_lib is None or self._db is None:
            return
        try:
            clip_id = self._active_lib.register_download(self._db, payload)
        except Exception as e:
            self._on_log(f"[Library] Registration failed: {e}")
            return
        if clip_id is None:
            self._on_log("[Library] Downloaded file is outside the library — not registered.")
        else:
            self._on_log(f"[Library] Registered clip #{clip_id}: {payload.get('title')}")
            self._library_view.refresh()
            self._update_library_status()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @Slot()
    def _open_settings(self) -> None:
        SettingsDialog(self._settings, self).exec()

    @Slot(str)
    def _on_log(self, message: str) -> None:
        self._log.appendPlainText(message)

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def _load_active_library(self) -> None:
        """Open the active library's DB on the main thread (if any)."""
        if self._db is not None:
            self._db.close()
            self._db = None
        self._active_lib = self._libraries.active_library()
        if self._active_lib is not None:
            self._db = self._active_lib.open_db()
        self._library_view.set_library(self._active_lib, self._db)
        self._filter_panel.set_library(self._active_lib, self._db)
        self._update_library_status()

    def _update_library_status(self) -> None:
        if self._active_lib is None:
            self.statusBar().showMessage("No library — open one from the Library menu")
            return
        count = self._db.count_clips() if self._db else 0
        self.statusBar().showMessage(
            f"Library: {self._active_lib.name}  ({count} clips)  —  {self._active_lib.root}"
        )

    @Slot()
    def _open_library(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select or create a library folder",
            str(self._active_lib.root) if self._active_lib else "",
        )
        if not path:
            return
        info = self._libraries.add(path, make_active=True)
        self._on_log(f"[Library] Opened '{info.name}' at {info.root}")
        self._load_active_library()

    @Slot()
    def _switch_library(self) -> None:
        infos = self._libraries.list()
        if not infos:
            QMessageBox.information(
                self, "No libraries",
                "No libraries registered yet. Use 'Open / Create Library...' first.",
            )
            return
        labels = [f"{i.name}  ({i.root})" for i in infos]
        current = self._libraries.active_root()
        current_idx = next((n for n, i in enumerate(infos) if i.root == current), 0)
        label, ok = QInputDialog.getItem(
            self, "Switch Library", "Active library:", labels, current_idx, False
        )
        if ok and label:
            self._libraries.set_active(infos[labels.index(label)].root)
            self._load_active_library()

    @Slot()
    def _rescan_library(self) -> None:
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library before scanning.")
            return
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self._scan_worker = ScanWorker(str(self._active_lib.root), self._active_lib.name)
        self._scan_worker.log_message.connect(self._on_log)
        self._scan_worker.progress.connect(
            lambda n, p: self.statusBar().showMessage(f"Scanning... ({n}) {p}")
        )
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    @Slot(int, int)
    def _on_scan_finished(self, added: int, missing: int) -> None:
        self._on_log(f"[Library] Scan finished: {added} new, {missing} missing.")
        self._filter_panel.rebuild()    # 新しい実フォルダをツリーに反映
        self._library_view.refresh()
        self._update_library_status()

    @Slot()
    def _enrich_library(self) -> None:
        """ffprobe メタ補完＋サムネイル生成をワーカーで実行。"""
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library first.")
            return
        if self._enrich_worker and self._enrich_worker.isRunning():
            return
        self._enrich_worker = EnrichWorker(str(self._active_lib.root), self._active_lib.name)
        self._enrich_worker.log_message.connect(self._on_log)
        self._enrich_worker.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"Enriching... {done}/{total}")
        )
        self._enrich_worker.finished_enrich.connect(self._on_enrich_finished)
        self._enrich_worker.start()

    @Slot(int)
    def _on_enrich_finished(self, updated: int) -> None:
        self._on_log(f"[Library] Enrich finished: {updated} clip(s) updated.")
        self._library_view.refresh()
        self._update_library_status()

    @Slot(dict)
    def _on_filter_changed(self, flt: dict) -> None:
        self._library_view.set_filter(
            folder_path=flt.get("folder_path"),
            tag_id=flt.get("tag_id"),
            missing_only=flt.get("missing_only", False),
        )

    @Slot(str)
    def _open_external(self, abs_path: str) -> None:
        """クリップを OS 既定のプレイヤーで開く（コーデック非対応時のフォールバック）。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(abs_path))

    @Slot(str)
    def _open_location(self, abs_path: str) -> None:
        """クリップを含むフォルダを開く。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(abs_path).parent)))

    @Slot(str)
    def _open_folder(self, abs_dir: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(abs_dir))

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        geom, state = self._settings.load_geometry()
        if geom:
            self.restoreGeometry(geom)
        if state:
            self.restoreState(state)
        else:
            # 最終的に ~1920x1080 を想定（plan.md の UI レイアウト像）。
            self.resize(1280, 800)

    def closeEvent(self, event) -> None:
        self._settings.save_geometry(
            bytes(self.saveGeometry()),
            bytes(self.saveState()),
        )
        self._player.stop()
        self._queue.shutdown(3000)
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.wait(3000)
        if self._enrich_worker and self._enrich_worker.isRunning():
            self._enrich_worker.cancel()
            self._enrich_worker.wait(3000)
        if self._db is not None:
            self._db.close()
            self._db = None
        super().closeEvent(event)
