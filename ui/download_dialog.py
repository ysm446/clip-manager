"""「ここにダウンロード」のポップアップ。URL と形式を入力してキューに積む。

保存先フォルダ（絶対パス）は呼び出し側から渡される。既定値は ``AppSettings``。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QLabel,
    QDialogButtonBox,
)

from core.downloader import SAVE_FORMATS, is_audio_format
from core.settings import AppSettings

_QUALITIES = ["144p", "240p", "360p", "480p", "720p", "1080p", "best"]
_CODECS = ["H.264", "VP9", "AV1"]


class DownloadDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        dest_dir: str,
        parent=None,
        *,
        initial_url: str = "",
        initial_format: str | None = None,
        note: str = "",
        window_title: str = "Download here",
    ):
        super().__init__(parent)
        self._settings = settings
        self._dest_dir = dest_dir
        self._initial_url = initial_url
        self._initial_format = initial_format
        self._note = note
        self.setWindowTitle(window_title)
        self.setMinimumWidth(520)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if self._note:
            note = QLabel(self._note)
            note.setStyleSheet("color: #c0392b; font-size: 11px;")
            note.setWordWrap(True)
            layout.addWidget(note)

        dest = QLabel(self._dest_dir)
        dest.setStyleSheet("color: gray; font-size: 11px;")
        dest.setWordWrap(True)
        layout.addWidget(QLabel("Save to:"))
        layout.addWidget(dest)

        form = QFormLayout()
        form.setSpacing(10)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("Paste YouTube URL here...")
        self._url_edit.setText(self._initial_url)
        form.addRow("URL:", self._url_edit)

        self._format_combo = QComboBox()
        self._format_combo.addItems(list(SAVE_FORMATS))
        self._format_combo.setCurrentText(self._initial_format or self._settings.save_format)
        self._format_combo.currentTextChanged.connect(self._on_format_changed)
        form.addRow("Format:", self._format_combo)

        self._quality_combo = QComboBox()
        self._quality_combo.addItems(_QUALITIES)
        self._quality_combo.setCurrentText(self._settings.default_quality)
        form.addRow("Quality:", self._quality_combo)

        self._codec_combo = QComboBox()
        self._codec_combo.addItems(_CODECS)
        self._codec_combo.setCurrentText(self._settings.default_codec)
        form.addRow("Codec:", self._codec_combo)

        self._subtitle_check = QCheckBox("Download English subtitles (.srt)")
        self._subtitle_check.setChecked(self._settings.write_subtitles)
        form.addRow("Subtitles:", self._subtitle_check)

        self._chapters_check = QCheckBox("Import YouTube chapters as bookmarks")
        self._chapters_check.setChecked(self._settings.import_chapters)
        form.addRow("Chapters:", self._chapters_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add to queue")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_format_changed(self._format_combo.currentText())
        self._url_edit.setFocus()

    def _on_format_changed(self, fmt: str) -> None:
        audio = is_audio_format(fmt)
        self._quality_combo.setEnabled(not audio)
        self._codec_combo.setEnabled(not audio)

    def _accept(self) -> None:
        if not self._url_edit.text().strip():
            self._url_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        """ダウンロード設定。``dest_dir`` を含む。"""
        return {
            "url": self._url_edit.text().strip(),
            "dest_dir": self._dest_dir,
            "quality": self._quality_combo.currentText(),
            "codec": self._codec_combo.currentText(),
            "write_subtitles": self._subtitle_check.isChecked(),
            "save_format": self._format_combo.currentText(),
            "import_chapters": self._chapters_check.isChecked(),
        }
