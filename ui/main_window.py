from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCheckBox,
    QProgressBar,
    QPlainTextEdit,
    QLabel,
    QFileDialog,
    QStatusBar,
    QInputDialog,
    QMessageBox,
    QTabWidget,
    QSplitter,
)
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from core.downloader import DownloadWorker, is_audio_format, SAVE_FORMATS
from core.settings import AppSettings
from core.libraries import LibraryManager
from core.library import Library
from core.database import LibraryDatabase
from core.scan_worker import ScanWorker
from core.enrich_worker import EnrichWorker
from ui.library_view import LibraryView
from ui.filter_panel import FilterPanel
from ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._worker: DownloadWorker | None = None
        # --- Library state ---
        self._libraries = LibraryManager()
        self._active_lib: Library | None = None
        self._db: LibraryDatabase | None = None  # main-thread connection
        self._scan_worker: ScanWorker | None = None
        self._enrich_worker: EnrichWorker | None = None
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

        # --- Download tab ---
        download_tab = QWidget()
        layout = QVBoxLayout(download_tab)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # --- URL row ---
        url_row = QHBoxLayout()
        url_label = QLabel("URL:")
        url_label.setFixedWidth(50)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("Paste YouTube URL here...")
        self._url_edit.returnPressed.connect(self._start_download)
        url_row.addWidget(url_label)
        url_row.addWidget(self._url_edit)
        layout.addLayout(url_row)

        # --- Quality / Codec / Subtitle row ---
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("Format:"))
        self._format_combo = QComboBox()
        self._format_combo.addItems(list(SAVE_FORMATS))
        self._format_combo.setCurrentText(self._settings.save_format)
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        opt_row.addWidget(self._format_combo)

        opt_row.addSpacing(16)
        opt_row.addWidget(QLabel("Quality:"))
        self._quality_combo = QComboBox()
        self._quality_combo.addItems(["144p", "240p", "360p", "480p", "720p", "1080p", "best"])
        self._quality_combo.setCurrentText(self._settings.default_quality)
        opt_row.addWidget(self._quality_combo)

        opt_row.addSpacing(16)
        opt_row.addWidget(QLabel("Codec:"))
        self._codec_combo = QComboBox()
        self._codec_combo.addItems(["H.264", "VP9", "AV1"])
        self._codec_combo.setCurrentText(self._settings.default_codec)
        opt_row.addWidget(self._codec_combo)

        opt_row.addSpacing(16)
        self._subtitle_check = QCheckBox("Download English subtitles (.srt)")
        self._subtitle_check.setChecked(self._settings.write_subtitles)
        opt_row.addWidget(self._subtitle_check)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # --- Save-to row ---
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Save to:"))
        self._folder_label = QLabel(self._settings.output_dir)
        self._folder_label.setStyleSheet("color: gray; font-size: 11px;")
        folder_row.addWidget(self._folder_label, stretch=1)
        change_btn = QPushButton("Change folder...")
        change_btn.setFixedWidth(130)
        change_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(change_btn)
        layout.addLayout(folder_row)

        # --- Download / Cancel buttons ---
        btn_row = QHBoxLayout()
        self._download_btn = QPushButton("Download")
        self._download_btn.setFixedHeight(36)
        self._download_btn.clicked.connect(self._start_download)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(36)
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_download)
        btn_row.addWidget(self._download_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # --- Progress bar ---
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # --- Status line below progress bar ---
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px; color: gray;")
        layout.addWidget(self._status_label)

        # --- Log area ---
        layout.addWidget(QLabel("Log:"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setMinimumHeight(160)
        layout.addWidget(self._log)

        self._tabs.addTab(download_tab, "Download")

        # --- Library tab: [ filter tree | clip list ] ---
        self._filter_panel = FilterPanel()
        self._library_view = LibraryView()
        self._library_view.play_requested.connect(self._play_clip)
        self._library_view.enrich_requested.connect(self._enrich_library)
        self._library_view.open_location_requested.connect(self._open_location)
        self._filter_panel.filter_changed.connect(self._on_filter_changed)
        self._filter_panel.library_changed.connect(self._library_view.refresh)

        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.addWidget(self._filter_panel)
        library_split.addWidget(self._library_view)
        library_split.setStretchFactor(0, 0)
        library_split.setStretchFactor(1, 1)
        library_split.setSizes([260, 1100])
        self._tabs.addTab(library_split, "Library")

        # --- Menu bar ---
        file_menu = self.menuBar().addMenu("File")
        settings_action = file_menu.addAction("Settings...")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

        library_menu = self.menuBar().addMenu("Library")
        library_menu.addAction("Open / Create Library...").triggered.connect(
            self._open_library
        )
        library_menu.addAction("Switch Library...").triggered.connect(
            self._switch_library
        )
        library_menu.addSeparator()
        library_menu.addAction("Rescan Library").triggered.connect(
            self._rescan_library
        )

        # --- Status bar ---
        self.statusBar().showMessage("Ready")

        # Grey out quality/codec when an audio-only format is selected
        self._on_format_changed(self._format_combo.currentText())

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _start_download(self) -> None:
        url = self._url_edit.text().strip()
        if not url:
            self.statusBar().showMessage("Please enter a URL.")
            return
        if self._worker and self._worker.isRunning():
            return

        self._set_downloading(True)
        self._progress_bar.setValue(0)
        self._log.clear()
        self._status_label.setText("")

        self._worker = DownloadWorker(
            url=url,
            output_dir=self._download_output_dir(),
            quality=self._quality_combo.currentText(),
            codec=self._codec_combo.currentText(),
            write_subtitles=self._subtitle_check.isChecked(),
            save_format=self._format_combo.currentText(),
        )
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.log_message.connect(self._on_log)
        self._worker.download_succeeded.connect(self._on_download_succeeded)
        self._worker.download_finished.connect(self._on_finished)
        self._worker.start()
        self.statusBar().showMessage("Downloading...")

    def _download_output_dir(self) -> str:
        """Active library root if set (so clips land inside and auto-register),
        otherwise the configured default download folder."""
        if self._active_lib is not None:
            return str(self._active_lib.root)
        return self._settings.output_dir

    @Slot(str)
    def _on_format_changed(self, fmt: str) -> None:
        # Audio-only formats ignore the video quality/codec selections.
        audio = is_audio_format(fmt)
        self._quality_combo.setEnabled(not audio)
        self._codec_combo.setEnabled(not audio)

    @Slot()
    def _cancel_download(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self.statusBar().showMessage("Cancelling...")

    @Slot(float, str)
    def _on_progress(self, percent: float, status: str) -> None:
        self._progress_bar.setValue(int(percent))
        self._status_label.setText(status)

    @Slot(str)
    def _on_log(self, message: str) -> None:
        self._log.appendPlainText(message)

    @Slot(bool, str)
    def _on_finished(self, success: bool, message: str) -> None:
        self._set_downloading(False)
        self._status_label.setText(message)
        self.statusBar().showMessage(message)
        if success:
            self._progress_bar.setValue(100)
            self._log.appendPlainText(f"\n[SUCCESS] {message}")
        else:
            self._log.appendPlainText(f"\n[FAILED] {message}")

    @Slot()
    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Download Folder", self._settings.output_dir
        )
        if path:
            self._settings.output_dir = path
            self._folder_label.setText(path)

    @Slot()
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec():
            self._folder_label.setText(self._settings.output_dir)
            self._format_combo.setCurrentText(self._settings.save_format)
            self._quality_combo.setCurrentText(self._settings.default_quality)
            self._codec_combo.setCurrentText(self._settings.default_codec)
            self._subtitle_check.setChecked(self._settings.write_subtitles)

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
            self._folder_label.setText(str(self._active_lib.root))
        self._library_view.set_library(self._active_lib, self._db)
        self._filter_panel.set_db(self._db)
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
            self, "Select or create a library folder", self._settings.output_dir
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
        current_idx = next(
            (n for n, i in enumerate(infos) if i.root == current), 0
        )
        label, ok = QInputDialog.getItem(
            self, "Switch Library", "Active library:", labels, current_idx, False
        )
        if ok and label:
            chosen = infos[labels.index(label)]
            self._libraries.set_active(chosen.root)
            self._load_active_library()

    @Slot()
    def _rescan_library(self) -> None:
        if self._active_lib is None:
            QMessageBox.information(
                self, "No library", "Open a library before scanning."
            )
            return
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self._scan_worker = ScanWorker(
            str(self._active_lib.root), self._active_lib.name
        )
        self._scan_worker.log_message.connect(self._on_log)
        self._scan_worker.progress.connect(
            lambda n, p: self.statusBar().showMessage(f"Scanning... ({n}) {p}")
        )
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    @Slot(int, int)
    def _on_scan_finished(self, added: int, missing: int) -> None:
        self._on_log(f"[Library] Scan finished: {added} new, {missing} missing.")
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
        self._enrich_worker = EnrichWorker(
            str(self._active_lib.root), self._active_lib.name
        )
        self._enrich_worker.log_message.connect(self._on_log)
        self._enrich_worker.progress.connect(
            lambda done, total: self.statusBar().showMessage(
                f"Enriching... {done}/{total}"
            )
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
            folder_id=flt.get("folder_id"),
            tag_id=flt.get("tag_id"),
            missing_only=flt.get("missing_only", False),
        )

    @Slot(str)
    def _play_clip(self, abs_path: str) -> None:
        """クリップを既定のプレイヤーで開く（アプリ内プレイヤーは Phase 5）。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(abs_path))

    @Slot(str)
    def _open_location(self, abs_path: str) -> None:
        """クリップを含むフォルダを開く。"""
        from pathlib import Path
        folder = str(Path(abs_path).parent)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot(dict)
    def _on_download_succeeded(self, payload: dict) -> None:
        """Register a freshly downloaded clip into the active library DB."""
        if self._active_lib is None or self._db is None:
            return
        try:
            clip_id = self._active_lib.register_download(self._db, payload)
        except Exception as e:  # never let registration crash the UI
            self._on_log(f"[Library] Registration failed: {e}")
            return
        if clip_id is None:
            self._on_log(
                "[Library] Downloaded file is outside the active library — not registered."
            )
        else:
            self._on_log(f"[Library] Registered clip #{clip_id}: {payload.get('title')}")
            self._library_view.refresh()
            self._update_library_status()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_downloading(self, downloading: bool) -> None:
        self._download_btn.setEnabled(not downloading)
        self._cancel_btn.setEnabled(downloading)

    def _restore_geometry(self) -> None:
        geom, state = self._settings.load_geometry()
        if geom:
            self.restoreGeometry(geom)
        if state:
            self.restoreState(state)
        else:
            # 最終的に ~1920x1080 を想定（plan.md の UI レイアウト像）。
            # 初期はやや小さめの大画面を既定にする。
            self.resize(1280, 800)

    def closeEvent(self, event) -> None:
        self._settings.save_geometry(
            bytes(self.saveGeometry()),
            bytes(self.saveState()),
        )
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.wait(3000)
        if self._enrich_worker and self._enrich_worker.isRunning():
            self._enrich_worker.cancel()
            self._enrich_worker.wait(3000)
        if self._db is not None:
            self._db.close()
            self._db = None
        super().closeEvent(event)
