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
)
from PySide6.QtCore import Qt, Slot
from core.downloader import DownloadWorker, is_audio_format, SAVE_FORMATS
from core.settings import AppSettings
from ui.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        self._worker: DownloadWorker | None = None
        self._init_ui()
        self._restore_geometry()
        self.setWindowTitle("Clip Downloader")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
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

        # --- Menu bar ---
        file_menu = self.menuBar().addMenu("File")
        settings_action = file_menu.addAction("Settings...")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

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
            output_dir=self._settings.output_dir,
            quality=self._quality_combo.currentText(),
            codec=self._codec_combo.currentText(),
            write_subtitles=self._subtitle_check.isChecked(),
            save_format=self._format_combo.currentText(),
        )
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.log_message.connect(self._on_log)
        self._worker.download_finished.connect(self._on_finished)
        self._worker.start()
        self.statusBar().showMessage("Downloading...")

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
            self.resize(720, 540)

    def closeEvent(self, event) -> None:
        self._settings.save_geometry(
            bytes(self.saveGeometry()),
            bytes(self.saveState()),
        )
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)
