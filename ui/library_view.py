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
    QMenu,
    QInputDialog,
    QFileDialog,
    QMessageBox,
)

_DETAILS, _THUMBS = 0, 1
_ROLE_CLIP = Qt.ItemDataRole.UserRole   # clip id (int)


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
    play_requested = Signal(str, str)   # (動画の絶対パス, 字幕の絶対パス or "")
    open_external_requested = Signal(str)
    enrich_requested = Signal()
    open_location_requested = Signal(str)
    library_modified = Signal()         # ファイル操作でクリップ件数等が変わった

    _COLUMNS = ["Title", "Duration", "Resolution", "Size", "Type", "Added"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
        self._db = None
        self._filter = {"folder_path": None, "tag_id": None, "missing_only": False}
        self._by_id: dict = {}   # clip id -> Clip（現在表示中）
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
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self._table.viewport().mapToGlobal(pos))
        )
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
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self._list.viewport().mapToGlobal(pos))
        )
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
        self._filter = {"folder_path": None, "tag_id": None, "missing_only": False}
        self.refresh()

    def set_filter(self, folder_path=None, tag_id=None, missing_only=False) -> None:
        self._filter = {
            "folder_path": folder_path, "tag_id": tag_id, "missing_only": missing_only,
        }
        self.refresh()

    def refresh(self) -> None:
        if self._db is None or self._library is None:
            self._table.setRowCount(0)
            self._list.clear()
            self._by_id = {}
            self._count_label.setText("No library")
            return
        search = self._search.text().strip() or None
        clips = self._db.list_clips(
            folder_path=self._filter["folder_path"],
            tag_id=self._filter["tag_id"],
            missing_only=self._filter["missing_only"],
            search=search,
        )
        self._by_id = {c.id: c for c in clips}
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
                    item.setData(_ROLE_CLIP, clip.id)
                if clip.missing:
                    item.setForeground(Qt.GlobalColor.gray)
                self._table.setItem(row, col, item)

    def _populate_thumbs(self, clips) -> None:
        self._list.clear()
        for clip in clips:
            item = QListWidgetItem(clip.title)
            item.setData(_ROLE_CLIP, clip.id)
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

    def _abs_path(self, clip_id) -> str | None:
        clip = self._by_id.get(clip_id)
        if clip is None or self._library is None:
            return None
        return str(self._library.to_abs(clip.rel_path))

    def _on_table_double_clicked(self, index) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            self._emit_play(item.data(_ROLE_CLIP))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._emit_play(item.data(_ROLE_CLIP))

    def _emit_play(self, clip_id) -> None:
        abs_path = self._abs_path(clip_id)
        if not abs_path:
            return
        clip = self._by_id.get(clip_id)
        subtitle = ""
        if clip and clip.subtitle_path and self._library is not None:
            subtitle = str(self._library.to_abs(clip.subtitle_path))
        self.play_requested.emit(abs_path, subtitle)

    def _emit_external(self, clip_id) -> None:
        abs_path = self._abs_path(clip_id)
        if abs_path:
            self.open_external_requested.emit(abs_path)

    # ------------------------------------------------------------------
    # Context menu (assign folder / toggle tags / play / locate)
    # ------------------------------------------------------------------

    def _current_clip_id(self):
        if self._stack.currentIndex() == _THUMBS:
            item = self._list.currentItem()
            return item.data(_ROLE_CLIP) if item else None
        item = self._table.item(self._table.currentRow(), 0)
        return item.data(_ROLE_CLIP) if item else None

    def _show_context_menu(self, global_pos) -> None:
        if self._db is None:
            return
        clip_id = self._current_clip_id()
        if clip_id is None:
            return
        menu = QMenu(self)
        menu.addAction("Play").triggered.connect(lambda: self._emit_play(clip_id))
        menu.addAction("Open externally").triggered.connect(
            lambda: self._emit_external(clip_id)
        )
        menu.addAction("Open file location").triggered.connect(
            lambda: self._emit_locate(clip_id)
        )
        menu.addSeparator()

        # Tags ▸ (checkable)
        tags = self._db.list_tags()
        tag_menu = menu.addMenu("Tags")
        if not tags:
            tag_menu.addAction("(no tags — create one in the left panel)").setEnabled(False)
        else:
            assigned = {t.id for t in self._db.tags_for_clip(clip_id)}
            for tag in tags:
                act = tag_menu.addAction(tag.name)
                act.setCheckable(True)
                act.setChecked(tag.id in assigned)
                act.triggered.connect(
                    lambda checked, tid=tag.id: self._toggle_tag(clip_id, tid, checked)
                )

        # --- file operations ---
        menu.addSeparator()
        menu.addAction("Rename...").triggered.connect(lambda: self._rename_clip(clip_id))
        menu.addAction("Move to folder...").triggered.connect(lambda: self._move_clip(clip_id))
        menu.addAction("Duplicate").triggered.connect(lambda: self._duplicate_clip(clip_id))
        menu.addAction("Delete...").triggered.connect(lambda: self._delete_clip(clip_id))

        menu.exec(global_pos)

    # ------------------------------------------------------------------
    # File operations（実ファイル＋DB を Library 経由で更新）
    # ------------------------------------------------------------------

    def _file_op(self, fn) -> bool:
        """ファイル操作を実行し、失敗時は警告を出す。成功で True。"""
        try:
            fn()
            return True
        except Exception as e:
            QMessageBox.warning(self, "File operation failed", str(e))
            return False

    def _rename_clip(self, clip_id) -> None:
        clip = self._by_id.get(clip_id)
        if clip is None:
            return
        current = Path(clip.rel_path).stem
        name, ok = QInputDialog.getText(
            self, "Rename", "New name (without extension):", text=current
        )
        if not (ok and name.strip()):
            return
        if self._file_op(lambda: self._library.rename_clip(self._db, clip_id, name)):
            self.refresh()
            self.library_modified.emit()

    def _move_clip(self, clip_id) -> None:
        dest = QFileDialog.getExistingDirectory(
            self, "Move into folder (inside the library)", str(self._library.root)
        )
        if not dest:
            return
        if self._file_op(lambda: self._library.move_clip(self._db, clip_id, dest)):
            self.refresh()
            self.library_modified.emit()

    def _duplicate_clip(self, clip_id) -> None:
        if self._file_op(lambda: self._library.duplicate_clip(self._db, clip_id)):
            self.refresh()
            self.library_modified.emit()

    def _delete_clip(self, clip_id) -> None:
        clip = self._by_id.get(clip_id)
        if clip is None:
            return
        if QMessageBox.question(
            self, "Delete",
            f"Send '{clip.title}' to the Recycle Bin?\n"
            "（実ファイルと字幕・サムネイルを削除し、ライブラリからも除外します。）",
        ) != QMessageBox.StandardButton.Yes:
            return
        if self._file_op(lambda: self._library.delete_clip(self._db, clip_id, to_trash=True)):
            self.refresh()
            self.library_modified.emit()

    def _toggle_tag(self, clip_id, tag_id, checked) -> None:
        if checked:
            self._db.assign_tag(clip_id, tag_id)
        else:
            self._db.unassign_tag(clip_id, tag_id)
        self.refresh()

    def _emit_locate(self, clip_id) -> None:
        abs_path = self._abs_path(clip_id)
        if abs_path:
            self.open_location_requested.emit(abs_path)
