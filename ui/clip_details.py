"""動画プレイヤー下部に表示する、選択中クリップの詳細パネル。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLabel,
    QScrollArea,
)

from ui.library_view import fmt_duration, fmt_size, fmt_resolution


class ClipDetailsPanel(QWidget):
    """1 クリップのメタデータ（サムネイル・解像度・コーデック・タグ等）を表示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
        self._init_ui()

    def set_library(self, library) -> None:
        self._library = library
        self.clear()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        self._title = QLabel("No clip selected")
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self._title)

        # メタ情報（スクロール可能）
        form_host = QWidget()
        self._form = QFormLayout(form_host)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setSpacing(6)

        self._fields: dict[str, QLabel] = {}
        for key in ("Folder", "Duration", "Resolution", "Codec", "Container",
                    "Size", "Tags", "Added", "Downloaded", "Source"):
            value = QLabel("—")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._fields[key] = value
            self._form.addRow(f"{key}:", value)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_host)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll, stretch=1)

    # ------------------------------------------------------------------

    def clear(self) -> None:
        self._title.setText("No clip selected")
        for v in self._fields.values():
            v.setText("—")

    def show_clip(self, clip, tags) -> None:
        if clip is None:
            self.clear()
            return
        self._title.setText(clip.title + ("   [missing]" if clip.missing else ""))

        folder = str(Path(clip.rel_path).parent)
        if folder == ".":
            folder = "(root)"
        self._fields["Folder"].setText(folder)
        self._fields["Duration"].setText(fmt_duration(clip.duration))
        self._fields["Resolution"].setText(fmt_resolution(clip.width, clip.height))
        self._fields["Codec"].setText(clip.vcodec or "—")
        self._fields["Container"].setText((clip.container or "—").upper())
        self._fields["Size"].setText(fmt_size(clip.filesize))
        self._fields["Tags"].setText(", ".join(t.name for t in tags) if tags else "—")
        self._fields["Added"].setText((clip.added_at or "—").replace("T", " "))
        self._fields["Downloaded"].setText((clip.downloaded_at or "—").replace("T", " "))
        self._fields["Source"].setText(clip.source_url or "—")
