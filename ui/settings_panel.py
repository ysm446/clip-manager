"""設定タブ。変更は即時に ``AppSettings``（QSettings）へ反映する。

OK/Cancel は持たず、各項目を変更した時点で保存する（タブ UI として自然な挙動）。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QFileDialog,
    QCheckBox,
    QComboBox,
)

from core.downloader import SAVE_FORMATS
from core.settings import AppSettings


class SettingsPanel(QWidget):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        layout.addWidget(self._build_playback_group())
        layout.addWidget(self._build_download_group())
        layout.addStretch()

    # ------------------------------------------------------------------
    # 再生
    # ------------------------------------------------------------------

    def _build_playback_group(self) -> QGroupBox:
        group = QGroupBox("再生")
        form = QFormLayout(group)
        form.setSpacing(10)

        self._resume_check = QCheckBox("動画の再生位置を保存する")
        self._resume_check.setToolTip(
            "次回同じ動画を開いたとき、前回停止した位置から再生します。"
        )
        self._resume_check.setChecked(self._settings.save_resume_position)
        self._resume_check.toggled.connect(
            lambda v: setattr(self._settings, "save_resume_position", v)
        )
        form.addRow("再生位置:", self._resume_check)
        return group

    # ------------------------------------------------------------------
    # ダウンロード
    # ------------------------------------------------------------------

    def _build_download_group(self) -> QGroupBox:
        group = QGroupBox("ダウンロード")
        form = QFormLayout(group)
        form.setSpacing(10)

        # 保存先フォルダ
        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit(self._settings.output_dir)
        self._dir_edit.editingFinished.connect(
            lambda: setattr(self._settings, "output_dir", self._dir_edit.text())
        )
        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse)
        dir_row.addWidget(self._dir_edit)
        dir_row.addWidget(browse_btn)
        form.addRow("Default save folder:", dir_row)

        # 保存形式
        self._format_combo = QComboBox()
        self._format_combo.addItems(list(SAVE_FORMATS))
        self._format_combo.setCurrentText(self._settings.save_format)
        self._format_combo.currentTextChanged.connect(
            lambda v: setattr(self._settings, "save_format", v)
        )
        form.addRow("Default save format:", self._format_combo)

        # 画質
        self._quality_combo = QComboBox()
        self._quality_combo.addItems(
            ["144p", "240p", "360p", "480p", "720p", "1080p", "best"]
        )
        self._quality_combo.setCurrentText(self._settings.default_quality)
        self._quality_combo.currentTextChanged.connect(
            lambda v: setattr(self._settings, "default_quality", v)
        )
        form.addRow("Default quality:", self._quality_combo)

        # コーデック
        self._codec_combo = QComboBox()
        self._codec_combo.addItems(["H.264", "VP9", "AV1"])
        self._codec_combo.setCurrentText(self._settings.default_codec)
        self._codec_combo.currentTextChanged.connect(
            lambda v: setattr(self._settings, "default_codec", v)
        )
        form.addRow("Default codec:", self._codec_combo)

        # 字幕
        self._sub_check = QCheckBox("Download English subtitles by default")
        self._sub_check.setChecked(self._settings.write_subtitles)
        self._sub_check.toggled.connect(
            lambda v: setattr(self._settings, "write_subtitles", v)
        )
        form.addRow("Subtitles:", self._sub_check)

        self._chapters_check = QCheckBox("Import YouTube chapters as bookmarks by default")
        self._chapters_check.setChecked(self._settings.import_chapters)
        self._chapters_check.toggled.connect(
            lambda v: setattr(self._settings, "import_chapters", v)
        )
        form.addRow("Chapters:", self._chapters_check)
        return group

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Download Folder", self._dir_edit.text()
        )
        if path:
            self._dir_edit.setText(path)
            self._settings.output_dir = path
