from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
)
from core.downloader import SAVE_FORMATS
from core.settings import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)

        # Output directory
        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit(self._settings.output_dir)
        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse)
        dir_row.addWidget(self._dir_edit)
        dir_row.addWidget(browse_btn)
        form.addRow("Default save folder:", dir_row)

        # Default save format
        self._format_combo = QComboBox()
        self._format_combo.addItems(list(SAVE_FORMATS))
        self._format_combo.setCurrentText(self._settings.save_format)
        form.addRow("Default save format:", self._format_combo)

        # Default quality
        self._quality_combo = QComboBox()
        self._quality_combo.addItems(["144p", "240p", "360p", "480p", "720p", "1080p", "best"])
        self._quality_combo.setCurrentText(self._settings.default_quality)
        form.addRow("Default quality:", self._quality_combo)

        # Default codec
        self._codec_combo = QComboBox()
        self._codec_combo.addItems(["H.264", "VP9", "AV1"])
        self._codec_combo.setCurrentText(self._settings.default_codec)
        form.addRow("Default codec:", self._codec_combo)

        # Subtitles
        self._sub_check = QCheckBox("Download English subtitles by default")
        self._sub_check.setChecked(self._settings.write_subtitles)
        form.addRow("Subtitles:", self._sub_check)

        layout.addLayout(form)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Download Folder", self._dir_edit.text()
        )
        if path:
            self._dir_edit.setText(path)

    def _save_and_accept(self) -> None:
        self._settings.output_dir = self._dir_edit.text()
        self._settings.save_format = self._format_combo.currentText()
        self._settings.default_quality = self._quality_combo.currentText()
        self._settings.default_codec = self._codec_combo.currentText()
        self._settings.write_subtitles = self._sub_check.isChecked()
        self.accept()
