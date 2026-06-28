"""ライブラリ一覧ビュー（詳細表 / サムネイル切替）。

DB アクセスは主スレッドの ``LibraryDatabase`` 接続を ``set_library`` で受け取る。
重い処理（メタ補完・サムネイル生成）は持たず、``enrich_requested`` を emit して
``MainWindow`` 側のワーカーに委ねる。再生は ``play_requested(abs_path)`` を emit。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QPushButton,
    QLabel,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QListWidget,
    QListWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QStyle,
)

_DETAILS, _THUMBS = 0, 1
_ROLE_CLIP = Qt.ItemDataRole.UserRole


def fmt_duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "—"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def fmt_size(num: int | None) -> str:
    if not num:
        return "—"
    val = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


def fmt_resolution(w: int | None, h: int | None) -> str:
    return f"{w}×{h}" if w and h else "—"


class LibraryView(QWidget):
    play_requested = Signal(str)        # 絶対パス
    enrich_requested = Signal()
    open_location_requested = Signal(str)

    _COLUMNS = ["Title", "Duration", "Resolution", "Size", "Type", "Added"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
        self._db = None
        self._init_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- toolbar ---
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search title...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.refresh)
        bar.addWidget(self._search, stretch=1)

        self._view_combo = QComboBox()
        self._view_combo.addItems(["Details", "Thumbnails"])
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        bar.addWidget(QLabel("View:"))
        bar.addWidget(self._view_combo)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self._refresh_btn)

        self._enrich_btn = QPushButton("Enrich (metadata + thumbnails)")
        self._enrich_btn.clicked.connect(self.enrich_requested.emit)
        bar.addWidget(self._enrich_btn)
        layout.addLayout(bar)

        # --- stacked views ---
        self._stack = QStackedWidget()

        # details: table
        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.doubleClicked.connect(self._on_table_double_clicked)
        self._stack.addWidget(self._table)

        # thumbnails: icon list
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(160, 90))
        self._list.setGridSize(QSize(184, 140))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setWordWrap(True)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._stack.addWidget(self._list)

        layout.addWidget(self._stack, stretch=1)

        # --- status line ---
        self._count_label = QLabel("No library")
        self._count_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._count_label)

        self._placeholder_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileIcon
        )

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_library(self, library, db) -> None:
        self._library = library
        self._db = db
        self.refresh()

    def refresh(self) -> None:
        if self._db is None or self._library is None:
            self._table.setRowCount(0)
            self._list.clear()
            self._count_label.setText("No library")
            return
        search = self._search.text().strip() or None
        clips = self._db.list_clips(search=search)
        self._populate_details(clips)
        self._populate_thumbs(clips)
        missing = sum(1 for c in clips if c.missing)
        suffix = f"  ({missing} missing)" if missing else ""
        self._count_label.setText(f"{len(clips)} clip(s){suffix}")

    def _populate_details(self, clips) -> None:
        self._table.setRowCount(0)
        for clip in clips:
            row = self._table.rowCount()
            self._table.insertRow(row)
            title = clip.title + ("  [missing]" if clip.missing else "")
            cells = [
                title,
                fmt_duration(clip.duration),
                fmt_resolution(clip.width, clip.height),
                fmt_size(clip.filesize),
                (clip.container or "").upper(),
                (clip.added_at or "").replace("T", " "),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(_ROLE_CLIP, clip.rel_path)
                if clip.missing:
                    item.setForeground(Qt.GlobalColor.gray)
                self._table.setItem(row, col, item)

    def _populate_thumbs(self, clips) -> None:
        self._list.clear()
        for clip in clips:
            item = QListWidgetItem(clip.title)
            item.setData(_ROLE_CLIP, clip.rel_path)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            icon = self._placeholder_icon
            if clip.thumbnail_path:
                abs_thumb = self._library.to_abs(clip.thumbnail_path)
                if Path(abs_thumb).is_file():
                    pix = QPixmap(str(abs_thumb))
                    if not pix.isNull():
                        icon = QIcon(pix)
            item.setIcon(icon)
            self._list.addItem(item)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_view_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _abs_from_rel(self, rel_path: str) -> str | None:
        if not rel_path or self._library is None:
            return None
        return str(self._library.to_abs(rel_path))

    def _on_table_double_clicked(self, index) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            self._emit_play(item.data(_ROLE_CLIP))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._emit_play(item.data(_ROLE_CLIP))

    def _emit_play(self, rel_path) -> None:
        abs_path = self._abs_from_rel(rel_path)
        if abs_path:
            self.play_requested.emit(abs_path)
