"""左ペインの階層ツリー（実フォルダ ＋ その中のファイル ＋ タグ ＋ 欠落）。

- フォルダ階層は**ライブラリルート配下の実ディレクトリ**を表し、各フォルダ配下の
  クリップ（ファイル）もツリーに表示する。
- **ファイルを別フォルダへドラッグ&ドロップで移動**できる（実ファイル＋DB を更新）。
- フォルダ選択で一覧を絞り込み（``filter_changed``）、ファイルのダブルクリックで
  再生（``clip_activated``）。フォルダ右クリックから DL/作成/改名/Explorer。
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath

from PySide6.QtCore import Qt, Signal, QSettings, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QMessageBox,
    QMenu,
    QStyle,
    QAbstractItemView,
)

# アイコン表示の QListWidgetItem 用ロール
_IROLE_KIND = Qt.ItemDataRole.UserRole      # "up" | "folder" | "clip"
_IROLE_ID = Qt.ItemDataRole.UserRole + 1    # folder/up=rel(str) / clip=id(int)

_ROLE_KIND = Qt.ItemDataRole.UserRole       # "folder" | "clip" | "tag" | "missing" | "header"
_ROLE_ID = Qt.ItemDataRole.UserRole + 1     # folder=rel(str,""=root) / clip=id(int) / tag=id(int)


class _FolderTree(QTreeWidget):
    """フォルダへのクリップ D&D 移動・Delete キー削除に対応したツリー。"""

    clip_dropped = Signal(int, str)     # (clip_id, dest_folder_rel)
    folder_dropped = Signal(str, str)   # (src_folder_rel, dest_parent_rel)
    delete_requested = Signal(list)     # [clip_id, ...]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            ids = [
                int(it.data(0, _ROLE_ID))
                for it in self.selectedItems()
                if it.data(0, _ROLE_KIND) == "clip"
            ]
            if ids:
                self.delete_requested.emit(ids)
                return
        super().keyPressEvent(event)

    def dropEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        # ドロップ先がファイル等なら親フォルダまで遡る
        while target is not None and target.data(0, _ROLE_KIND) != "folder":
            target = target.parent()
        if target is None:
            event.ignore()
            return
        dest_rel = target.data(0, _ROLE_ID) or ""
        # ドロップ前に確定（rebuild で item が破棄されても安全なように）
        clip_ids = [
            int(it.data(0, _ROLE_ID))
            for it in self.selectedItems()
            if it.data(0, _ROLE_KIND) == "clip"
        ]
        folder_rels = [
            it.data(0, _ROLE_ID)
            for it in self.selectedItems()
            if it.data(0, _ROLE_KIND) == "folder" and it.data(0, _ROLE_ID)
        ]
        if not clip_ids and not folder_rels:
            event.ignore()
            return
        # 既定の move（モデル改変）はせず、自前で移動 → rebuild する
        event.accept()
        for clip_id in clip_ids:
            self.clip_dropped.emit(clip_id, dest_rel)
        for rel in folder_rels:
            self.folder_dropped.emit(rel, dest_rel)


class _IconList(QListWidget):
    """サムネイル（アイコン）表示。Delete キーで選択クリップ削除を要求する。"""

    delete_requested = Signal(list)   # [clip_id, ...]

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            ids = [
                int(it.data(_IROLE_ID))
                for it in self.selectedItems()
                if it.data(_IROLE_KIND) == "clip"
            ]
            if ids:
                self.delete_requested.emit(ids)
                return
        super().keyPressEvent(event)


class FilterPanel(QWidget):
    clip_activated = Signal(int)             # ファイルのダブルクリック（再生）
    clip_selected = Signal(int)              # ファイル選択（詳細表示）
    download_here_requested = Signal(str)    # 保存先（絶対パス）
    open_folder_requested = Signal(str)      # フォルダ（絶対パス）
    open_external_requested = Signal(str)    # クリップ（絶対パス）
    open_location_requested = Signal(str)    # クリップ（絶対パス）
    redownload_requested = Signal(int)       # クリップ（再ダウンロードして上書き）
    library_changed = Signal()               # 構成が変わった

    _EXPANDED_KEY = "ui/expanded_folders"
    _MODE_KEY = "ui/explorer_mode"           # "tree" | "icons"
    _TREE, _ICONS = 0, 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
        self._db = None
        self._cur_dir = ""                   # アイコン表示の現在フォルダ（rel, ""=root）
        self._settings = QSettings()         # 開閉状態・表示モードの永続化（data/）
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # --- toolbar: 表示モード切替 ＋ (アイコン時) 上へ／パス ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel("View:"))
        self._view_combo = QComboBox()
        self._view_combo.addItems(["Tree", "Icons"])
        self._view_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        bar.addWidget(self._view_combo)
        self._up_btn = QPushButton("↑ Up")
        self._up_btn.clicked.connect(self._go_up)
        bar.addWidget(self._up_btn)
        self._path_label = QLabel("")
        self._path_label.setStyleSheet("color: gray; font-size: 11px;")
        bar.addWidget(self._path_label, stretch=1)
        layout.addLayout(bar)

        # --- stacked: ツリー / アイコン ---
        self._stack = QStackedWidget()

        self._tree = _FolderTree()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_clicked)
        self._tree.clip_dropped.connect(self._on_clip_dropped)
        self._tree.folder_dropped.connect(self._on_folder_dropped)
        self._tree.delete_requested.connect(self._delete_clips)
        self._tree.itemExpanded.connect(self._on_expand_changed)
        self._tree.itemCollapsed.connect(self._on_expand_changed)
        self._stack.addWidget(self._tree)

        self._icons = _IconList()
        self._icons.setViewMode(QListWidget.ViewMode.IconMode)
        self._icons.setIconSize(QSize(96, 96))
        self._icons.setGridSize(QSize(120, 116))
        self._icons.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._icons.setMovement(QListWidget.Movement.Static)
        self._icons.setWordWrap(True)
        self._icons.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._icons.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._icons.customContextMenuRequested.connect(self._on_icon_context_menu)
        self._icons.itemDoubleClicked.connect(self._on_icon_double_clicked)
        self._icons.currentItemChanged.connect(self._on_icon_selection)
        self._icons.delete_requested.connect(self._delete_clips)
        self._stack.addWidget(self._icons)

        layout.addWidget(self._stack, stretch=1)

        # 空状態の案内
        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._hint)

        btn_row = QHBoxLayout()
        self._new_folder_btn = QPushButton("New Folder")
        self._new_folder_btn.clicked.connect(self._new_folder)
        self._new_tag_btn = QPushButton("New Tag")
        self._new_tag_btn.clicked.connect(self._new_tag)
        btn_row.addWidget(self._new_folder_btn)
        btn_row.addWidget(self._new_tag_btn)
        layout.addLayout(btn_row)

        # 保存済みの表示モードを復元
        mode = self._settings.value(self._MODE_KEY, "tree", type=str)
        self._view_combo.setCurrentIndex(self._ICONS if mode == "icons" else self._TREE)
        self._stack.setCurrentIndex(self._view_combo.currentIndex())
        self._update_toolbar()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_library(self, library, db) -> None:
        self._library = library
        self._db = db
        self._cur_dir = ""
        self.rebuild()

    def rebuild(self) -> None:
        self._rebuild_tree()
        self._populate_icons()
        self._update_hint()

    def _update_hint(self) -> None:
        if self._library is None:
            self._hint.setText(
                "ライブラリがありません。メニュー Library →"
                " 「Open / Create Library...」で開いてください。"
            )
        elif self._db is not None and self._db.count_clips() == 0:
            self._hint.setText(
                "クリップがありません。フォルダを右クリック →「Download here...」、"
                "または既存ファイルがあれば Library →「Rescan Library」。"
            )
        else:
            self._hint.setText("")
        self._hint.setVisible(bool(self._hint.text()))

    def _rebuild_tree(self) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()

        if self._library is None:
            self._tree.blockSignals(False)
            return

        # --- 実フォルダ（ルート＝ライブラリ。選択で全件） ---
        root_item = self._make_item(f"{self._library.name}  (all)", "folder", "")
        self._tree.addTopLevelItem(root_item)
        items = {"": root_item}
        for rel in self._library.list_dirs():
            parts = rel.split("/")
            parent_item = items.get("/".join(parts[:-1]), root_item)
            item = self._make_item(parts[-1], "folder", rel)
            parent_item.addChild(item)
            items[rel] = item

        # --- 各フォルダ配下のファイル（クリップ） ---
        if self._db is not None:
            for clip in self._db.list_clips(order_by="title ASC"):
                parent_rel = str(PurePosixPath(clip.rel_path).parent)
                if parent_rel == ".":
                    parent_rel = ""
                parent_item = items.get(parent_rel, root_item)
                citem = self._make_item(clip.title, "clip", clip.id)
                if clip.missing:
                    citem.setForeground(0, Qt.GlobalColor.gray)
                parent_item.addChild(citem)

        # 開閉状態を復元（ルートは常に開く）。signals は block 中なので再保存されない。
        expanded = self._expanded_set()
        for rel, item in items.items():
            if rel == "" or rel in expanded:
                item.setExpanded(True)

        self._tree.addTopLevelItem(self._make_item("Missing files", "missing"))

        # --- タグ（横断分類） ---
        if self._db is not None:
            tags_header = self._make_item("Tags", "header")
            self._tree.addTopLevelItem(tags_header)
            for t in self._db.list_tags():
                tags_header.addChild(self._make_item(f"# {t.name}", "tag", t.id))
            tags_header.setExpanded(True)

        self._tree.setCurrentItem(root_item)
        self._tree.blockSignals(False)

    # ------------------------------------------------------------------
    # フォルダ開閉状態の永続化（QSettings、ライブラリごと）
    # ------------------------------------------------------------------

    def _iter_folder_items(self):
        stack = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, _ROLE_KIND) == "folder":
                yield it
            stack.extend(it.child(k) for k in range(it.childCount()))

    def _load_expanded_map(self) -> dict:
        raw = self._settings.value(self._EXPANDED_KEY, "", type=str)
        try:
            return json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            return {}

    def _expanded_set(self) -> set:
        if self._library is None:
            return set()
        return set(self._load_expanded_map().get(str(self._library.root), []))

    def _persist_expanded(self) -> None:
        if self._library is None:
            return
        # ルート("")以外の、開いている実フォルダの rel を保存
        expanded = [
            it.data(0, _ROLE_ID)
            for it in self._iter_folder_items()
            if it.isExpanded() and it.data(0, _ROLE_ID)
        ]
        m = self._load_expanded_map()
        m[str(self._library.root)] = expanded
        self._settings.setValue(self._EXPANDED_KEY, json.dumps(m))

    def _on_expand_changed(self, item) -> None:
        if item is not None and item.data(0, _ROLE_KIND) == "folder":
            self._persist_expanded()

    def _make_item(self, label: str, kind: str, item_id=None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _ROLE_KIND, kind)
        item.setData(0, _ROLE_ID, item_id)
        base = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if kind == "folder":
            # ルート("")はドロップ先のみ、サブフォルダはドラッグ移動も可
            flags = base | Qt.ItemFlag.ItemIsDropEnabled
            if item_id:
                flags |= Qt.ItemFlag.ItemIsDragEnabled
            item.setFlags(flags)
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        elif kind == "clip":
            item.setFlags(base | Qt.ItemFlag.ItemIsDragEnabled)
            item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        elif kind == "header":
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        else:
            item.setFlags(base)
        return item

    # ------------------------------------------------------------------
    # Selection / activation
    # ------------------------------------------------------------------

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        kind = current.data(0, _ROLE_KIND)
        item_id = current.data(0, _ROLE_ID)
        if kind == "folder":
            self._apply_filter()                       # フォルダはツリーで辿る（全表示）
        elif kind == "tag":
            self._apply_filter(tag_id=item_id)         # タグでツリーを絞り込み
        elif kind == "missing":
            self._apply_filter(missing_only=True)
        elif kind == "clip":
            self.clip_selected.emit(int(item_id))      # 詳細表示

    def _on_double_clicked(self, item, _column) -> None:
        if item is not None and item.data(0, _ROLE_KIND) == "clip":
            self.clip_activated.emit(int(item.data(0, _ROLE_ID)))

    # ------------------------------------------------------------------
    # アイコン（サムネイル）表示
    # ------------------------------------------------------------------

    def _on_view_mode_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._settings.setValue(
            self._MODE_KEY, "icons" if index == self._ICONS else "tree"
        )
        self._update_toolbar()

    def _update_toolbar(self) -> None:
        icon_mode = self._stack.currentIndex() == self._ICONS
        self._up_btn.setVisible(icon_mode)
        self._path_label.setVisible(icon_mode)
        if icon_mode:
            self._up_btn.setEnabled(bool(self._cur_dir))
            if self._library is not None:
                self._path_label.setText(self._cur_dir or f"{self._library.name}  (root)")

    def _dir_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    def _file_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _clip_icon(self, clip) -> QIcon:
        if clip.thumbnail_path and self._library is not None:
            tp = self._library.to_abs(clip.thumbnail_path)
            if tp.is_file():
                pix = QPixmap(str(tp))
                if not pix.isNull():
                    return QIcon(pix)
        return self._file_icon()

    def _add_icon_item(self, text, kind, item_id, icon) -> QListWidgetItem:
        it = QListWidgetItem(icon, text)
        it.setData(_IROLE_KIND, kind)
        it.setData(_IROLE_ID, item_id)
        it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._icons.addItem(it)
        return it

    def _populate_icons(self) -> None:
        self._icons.clear()
        if self._library is None:
            self._update_toolbar()
            return
        cur = self._cur_dir

        # 「上の階層」
        if cur:
            parent = str(PurePosixPath(cur).parent)
            if parent == ".":
                parent = ""
            up = self._add_icon_item("..", "up", parent,
                                     self.style().standardIcon(
                                         QStyle.StandardPixmap.SP_FileDialogToParent))
            up.setToolTip("上の階層へ")

        # サブフォルダ（直下のみ）
        for rel in self._library.list_dirs():
            p = str(PurePosixPath(rel).parent)
            if p == ".":
                p = ""
            if p == cur:
                self._add_icon_item(rel.split("/")[-1], "folder", rel, self._dir_icon())

        # ファイル（直下のみ）
        if self._db is not None:
            for clip in self._db.list_clips(order_by="title ASC"):
                p = str(PurePosixPath(clip.rel_path).parent)
                if p == ".":
                    p = ""
                if p == cur:
                    it = self._add_icon_item(clip.title, "clip", clip.id, self._clip_icon(clip))
                    if clip.missing:
                        it.setForeground(Qt.GlobalColor.gray)
        self._update_toolbar()

    def _go_up(self) -> None:
        if not self._cur_dir:
            return
        parent = str(PurePosixPath(self._cur_dir).parent)
        self._cur_dir = "" if parent == "." else parent
        self._populate_icons()

    def _on_icon_double_clicked(self, item: QListWidgetItem) -> None:
        kind = item.data(_IROLE_KIND)
        if kind in ("up", "folder"):
            self._cur_dir = item.data(_IROLE_ID) or ""
            self._populate_icons()
        elif kind == "clip":
            self.clip_activated.emit(int(item.data(_IROLE_ID)))

    def _on_icon_selection(self, current, _previous) -> None:
        if current is not None and current.data(_IROLE_KIND) == "clip":
            self.clip_selected.emit(int(current.data(_IROLE_ID)))

    def _on_icon_context_menu(self, pos) -> None:
        item = self._icons.itemAt(pos)
        menu = QMenu(self)
        if item is None or item.data(_IROLE_KIND) == "up":
            # 余白／.. → 現在フォルダに対する操作
            cur_abs = (str(self._library.root) if not self._cur_dir
                       else str(self._library.to_abs(self._cur_dir)))
            self._add_folder_actions(menu, self._cur_dir, cur_abs)
        elif item.data(_IROLE_KIND) == "folder":
            rel = item.data(_IROLE_ID)
            self._add_folder_actions(menu, rel, str(self._library.to_abs(rel)))
        elif item.data(_IROLE_KIND) == "clip":
            cid = int(item.data(_IROLE_ID))
            ids = [int(i.data(_IROLE_ID)) for i in self._icons.selectedItems()
                   if i.data(_IROLE_KIND) == "clip"]
            if cid not in ids:
                ids = [cid]
            self._add_clip_actions(menu, cid, ids)
        if not menu.isEmpty():
            menu.exec(self._icons.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # タグ / 欠落でツリーを絞り込み（実フォルダはそのまま辿る）
    # ------------------------------------------------------------------

    def _all_items(self):
        stack = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack.extend(it.child(k) for k in range(it.childCount()))

    def _apply_filter(self, tag_id=None, missing_only=False) -> None:
        if (tag_id is None and not missing_only) or self._db is None:
            for it in self._all_items():
                it.setHidden(False)
            return
        if missing_only:
            allowed = {c.id for c in self._db.list_clips(missing_only=True)}
        else:
            allowed = {c.id for c in self._db.list_clips(tag_id=tag_id)}
        for it in self._all_items():
            if it.data(0, _ROLE_KIND) == "clip":
                it.setHidden(int(it.data(0, _ROLE_ID)) not in allowed)
        self._hide_empty_folders()

    def _hide_empty_folders(self) -> None:
        def visit(item) -> bool:
            has_visible = False
            for k in range(item.childCount()):
                child = item.child(k)
                ckind = child.data(0, _ROLE_KIND)
                if ckind == "folder":
                    has_visible = visit(child) or has_visible
                elif ckind == "clip" and not child.isHidden():
                    has_visible = True
            if item.data(0, _ROLE_ID):       # ルート("")以外
                item.setHidden(not has_visible)
            return has_visible

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.data(0, _ROLE_KIND) == "folder":
                visit(top)

    def _abs(self, clip_id) -> str:
        c = self._db.get_clip(clip_id) if self._db else None
        return str(self._library.to_abs(c.rel_path)) if c and self._library else ""

    def _selected_clip_ids(self) -> list[int]:
        return [
            int(it.data(0, _ROLE_ID))
            for it in self._tree.selectedItems()
            if it.data(0, _ROLE_KIND) == "clip"
        ]

    # ------------------------------------------------------------------
    # Delete clips (ゴミ箱へ)
    # ------------------------------------------------------------------

    def _delete_clips(self, ids: list[int]) -> None:
        if self._db is None or self._library is None or not ids:
            return
        clips = [c for c in (self._db.get_clip(i) for i in ids) if c is not None]
        if not clips:
            return
        names = "\n".join(f"・{c.title}" for c in clips[:8])
        if len(clips) > 8:
            names += f"\n…他 {len(clips) - 8} 件"
        if QMessageBox.question(
            self, "Delete",
            f"{len(clips)} 件をゴミ箱へ移動しますか？\n{names}\n"
            "（実ファイルと字幕・サムネイルを削除し、ライブラリからも除外します。）",
        ) != QMessageBox.StandardButton.Yes:
            return
        failed = []
        for c in clips:
            try:
                self._library.delete_clip(self._db, c.id, to_trash=True)
            except Exception as e:
                failed.append(f"{c.title}: {e}")
        if failed:
            QMessageBox.warning(self, "Delete failed", "\n".join(failed))
        self.rebuild()
        self.library_changed.emit()

    def _toggle_tag(self, clip_id: int, tag_id: int, checked: bool) -> None:
        if self._db is None:
            return
        if checked:
            self._db.assign_tag(clip_id, tag_id)
        else:
            self._db.unassign_tag(clip_id, tag_id)
        self.library_changed.emit()

    def _rename_clip(self, clip_id: int) -> None:
        clip = self._db.get_clip(clip_id) if self._db else None
        if clip is None:
            return
        current = PurePosixPath(clip.rel_path).stem
        name, ok = QInputDialog.getText(
            self, "Rename", "New name (without extension):", text=current
        )
        if not (ok and name.strip()):
            return
        try:
            self._library.rename_clip(self._db, clip_id, name)
        except Exception as e:
            QMessageBox.warning(self, "Rename failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    def _duplicate_clip(self, clip_id: int) -> None:
        try:
            self._library.duplicate_clip(self._db, clip_id)
        except Exception as e:
            QMessageBox.warning(self, "Duplicate failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    # ------------------------------------------------------------------
    # Drag & drop move
    # ------------------------------------------------------------------

    def _on_clip_dropped(self, clip_id: int, dest_rel: str) -> None:
        if self._db is None or self._library is None:
            return
        clip = self._db.get_clip(clip_id)
        if clip is None:
            return
        cur = str(PurePosixPath(clip.rel_path).parent)
        if cur == ".":
            cur = ""
        if cur == (dest_rel or ""):
            return   # 同じフォルダへは何もしない
        dest_abs = self._library.root if not dest_rel else self._library.to_abs(dest_rel)
        try:
            self._library.move_clip(self._db, clip_id, dest_abs)
        except Exception as e:
            QMessageBox.warning(self, "Move failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    def _on_folder_dropped(self, src_rel: str, dest_parent_rel: str) -> None:
        if self._db is None or self._library is None:
            return
        try:
            self._library.move_dir(self._db, src_rel, dest_parent_rel)
        except Exception as e:
            QMessageBox.warning(self, "Move folder failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    # ------------------------------------------------------------------
    # Folder / Tag 操作
    # ------------------------------------------------------------------

    def _selected(self) -> tuple[str | None, object]:
        item = self._tree.currentItem()
        if item is None:
            return None, None
        return item.data(0, _ROLE_KIND), item.data(0, _ROLE_ID)

    def _new_folder(self) -> None:
        if self._library is None:
            return
        if self._stack.currentIndex() == self._ICONS:
            parent_rel = self._cur_dir
        else:
            kind, ident = self._selected()
            parent_rel = ident if kind == "folder" else ""
        self._new_folder_in(parent_rel)

    def _new_folder_in(self, parent_rel: str) -> None:
        if self._library is None:
            return
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not (ok and name.strip()):
            return
        try:
            self._library.make_dir(parent_rel or None, name.strip())
        except Exception as e:
            QMessageBox.warning(self, "New Folder failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    # ------------------------------------------------------------------
    # コンテキストメニュー（ツリー / アイコン 共通の組み立て）
    # ------------------------------------------------------------------

    def _add_folder_actions(self, menu, rel: str, abs_dir: str) -> None:
        menu.addAction("Download here...").triggered.connect(
            lambda: self.download_here_requested.emit(abs_dir)
        )
        menu.addAction("New subfolder...").triggered.connect(
            lambda: self._new_folder_in(rel)
        )
        if rel:
            menu.addAction("Rename...").triggered.connect(
                lambda: self._rename_folder(rel)
            )
        menu.addAction("Open in Explorer").triggered.connect(
            lambda: self.open_folder_requested.emit(abs_dir)
        )
        if rel:
            menu.addSeparator()
            menu.addAction("Delete folder...").triggered.connect(
                lambda: self._delete_folder(rel)
            )

    def _add_clip_actions(self, menu, cid: int, ids: list[int]) -> None:
        menu.addAction("Play").triggered.connect(lambda: self.clip_activated.emit(cid))
        menu.addAction("Open externally").triggered.connect(
            lambda: self.open_external_requested.emit(self._abs(cid))
        )
        menu.addAction("Open file location").triggered.connect(
            lambda: self.open_location_requested.emit(self._abs(cid))
        )
        # 再ダウンロード（上書き）— ダウンロード元 URL が記録されているときだけ
        clip = self._db.get_clip(cid) if self._db else None
        if clip is not None and clip.source_url:
            menu.addAction("Re-download (overwrite)...").triggered.connect(
                lambda: self.redownload_requested.emit(cid)
            )
        menu.addSeparator()
        tags = self._db.list_tags() if self._db else []
        tag_menu = menu.addMenu("Tags")
        if not tags:
            tag_menu.addAction("(no tags — use New Tag)").setEnabled(False)
        else:
            assigned = {t.id for t in self._db.tags_for_clip(cid)}
            for t in tags:
                a = tag_menu.addAction(t.name)
                a.setCheckable(True)
                a.setChecked(t.id in assigned)
                a.triggered.connect(
                    lambda checked, tid=t.id: self._toggle_tag(cid, tid, checked)
                )
        menu.addSeparator()
        menu.addAction("Rename...").triggered.connect(lambda: self._rename_clip(cid))
        menu.addAction("Duplicate").triggered.connect(lambda: self._duplicate_clip(cid))
        label = "Delete..." if len(ids) == 1 else f"Delete {len(ids)} files..."
        menu.addAction(label).triggered.connect(lambda: self._delete_clips(ids))

    def _new_tag(self) -> None:
        if self._db is None:
            return
        name, ok = QInputDialog.getText(self, "New Tag", "Tag name:")
        if not (ok and name.strip()):
            return
        self._db.add_tag(name.strip())
        self.rebuild()
        self.library_changed.emit()

    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        kind = item.data(0, _ROLE_KIND)
        item_id = item.data(0, _ROLE_ID)
        menu = QMenu(self)

        if kind == "folder":
            abs_dir = (
                str(self._library.root) if not item_id
                else str(self._library.to_abs(item_id))
            )
            self._add_folder_actions(menu, item_id or "", abs_dir)
        elif kind == "clip":
            cid = int(item_id)
            ids = self._selected_clip_ids()
            if cid not in ids:
                ids = [cid]
            self._add_clip_actions(menu, cid, ids)
        elif kind == "tag":
            menu.addAction("Rename...").triggered.connect(
                lambda: self._rename_tag(item, item_id)
            )
            menu.addAction("Delete").triggered.connect(
                lambda: self._delete_tag(item, item_id)
            )
        else:
            return

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _delete_folder(self, rel: str) -> None:
        if self._db is None or self._library is None:
            return
        n = sum(1 for c in self._db.list_clips() if c.rel_path.startswith(rel + "/"))
        if QMessageBox.question(
            self, "Delete folder",
            f"フォルダ '{rel}' をゴミ箱へ移動しますか？\n"
            f"中のファイル {n} 件も削除され、ライブラリからも除外されます。",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self._library.delete_dir(self._db, rel, to_trash=True)
        except Exception as e:
            QMessageBox.warning(self, "Delete folder failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    def _rename_folder(self, rel: str) -> None:
        current = rel.split("/")[-1]
        name, ok = QInputDialog.getText(self, "Rename Folder", "New name:", text=current)
        if not (ok and name.strip()):
            return
        try:
            self._library.rename_dir(self._db, rel, name.strip())
        except Exception as e:
            QMessageBox.warning(self, "Rename failed", str(e))
            return
        self.rebuild()
        self.library_changed.emit()

    def _rename_tag(self, item, tag_id) -> None:
        current = item.text(0).lstrip("# ").strip()
        name, ok = QInputDialog.getText(self, "Rename Tag", "New name:", text=current)
        if not (ok and name.strip()):
            return
        self._db.rename_tag(tag_id, name.strip())
        self.rebuild()
        self.library_changed.emit()

    def _delete_tag(self, item, tag_id) -> None:
        if QMessageBox.question(
            self, "Delete Tag",
            f"Delete tag '{item.text(0)}'?（クリップ自体は削除されません）",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._db.delete_tag(tag_id)
        self.rebuild()
        self.library_changed.emit()
