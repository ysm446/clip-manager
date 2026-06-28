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

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
    QMessageBox,
    QMenu,
    QStyle,
    QAbstractItemView,
)

_ROLE_KIND = Qt.ItemDataRole.UserRole       # "folder" | "clip" | "tag" | "missing" | "header"
_ROLE_ID = Qt.ItemDataRole.UserRole + 1     # folder=rel(str,""=root) / clip=id(int) / tag=id(int)


class _FolderTree(QTreeWidget):
    """フォルダへのクリップ D&D 移動・Delete キー削除に対応したツリー。"""

    clip_dropped = Signal(int, str)   # (clip_id, dest_folder_rel)
    delete_requested = Signal(list)   # [clip_id, ...]

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
        # ドロップ前に id を確定（rebuild で item が破棄されても安全なように）
        ids = [
            int(it.data(0, _ROLE_ID))
            for it in self.selectedItems()
            if it.data(0, _ROLE_KIND) == "clip"
        ]
        if not ids:
            event.ignore()
            return
        # 既定の move（モデル改変）はせず、自前で移動 → rebuild する
        event.accept()
        for clip_id in ids:
            self.clip_dropped.emit(clip_id, dest_rel)


class FilterPanel(QWidget):
    filter_changed = Signal(dict)
    clip_activated = Signal(int)             # ファイルのダブルクリック（再生）
    download_here_requested = Signal(str)    # 保存先（絶対パス）
    open_folder_requested = Signal(str)      # フォルダ（絶対パス）
    library_changed = Signal()               # 構成が変わった（一覧を更新させる）

    _EXPANDED_KEY = "ui/expanded_folders"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
        self._db = None
        self._settings = QSettings()   # 開閉状態の永続化（data/ へリダイレクト済み）
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._tree = _FolderTree()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_clicked)
        self._tree.clip_dropped.connect(self._on_clip_dropped)
        self._tree.delete_requested.connect(self._delete_clips)
        self._tree.itemExpanded.connect(self._on_expand_changed)
        self._tree.itemCollapsed.connect(self._on_expand_changed)
        layout.addWidget(self._tree, stretch=1)

        btn_row = QHBoxLayout()
        self._new_folder_btn = QPushButton("New Folder")
        self._new_folder_btn.clicked.connect(self._new_folder)
        self._new_tag_btn = QPushButton("New Tag")
        self._new_tag_btn.clicked.connect(self._new_tag)
        btn_row.addWidget(self._new_folder_btn)
        btn_row.addWidget(self._new_tag_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_library(self, library, db) -> None:
        self._library = library
        self._db = db
        self.rebuild()

    def rebuild(self) -> None:
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
            item.setFlags(base | Qt.ItemFlag.ItemIsDropEnabled)
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
            self.filter_changed.emit(
                {"folder_path": item_id or None, "tag_id": None, "missing_only": False}
            )
        elif kind == "tag":
            self.filter_changed.emit(
                {"folder_path": None, "tag_id": item_id, "missing_only": False}
            )
        elif kind == "missing":
            self.filter_changed.emit(
                {"folder_path": None, "tag_id": None, "missing_only": True}
            )
        # clip 選択はフィルタを変えない（ダブルクリックで再生）

    def _on_double_clicked(self, item, _column) -> None:
        if item is not None and item.data(0, _ROLE_KIND) == "clip":
            self.clip_activated.emit(int(item.data(0, _ROLE_ID)))

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
        kind, ident = self._selected()
        parent_rel = ident if kind == "folder" else ""
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
            menu.addAction("Download here...").triggered.connect(
                lambda: self.download_here_requested.emit(abs_dir)
            )
            menu.addAction("New subfolder...").triggered.connect(self._new_folder)
            if item_id:
                menu.addAction("Rename...").triggered.connect(
                    lambda: self._rename_folder(item_id)
                )
            menu.addAction("Open in Explorer").triggered.connect(
                lambda: self.open_folder_requested.emit(abs_dir)
            )
        elif kind == "clip":
            menu.addAction("Play").triggered.connect(
                lambda: self.clip_activated.emit(int(item_id))
            )
            menu.addSeparator()
            # 右クリックしたファイルを選択に含めて、選択中のクリップをまとめて削除
            ids = self._selected_clip_ids()
            if int(item_id) not in ids:
                ids = [int(item_id)]
            label = "Delete..." if len(ids) == 1 else f"Delete {len(ids)} files..."
            menu.addAction(label).triggered.connect(lambda: self._delete_clips(ids))
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
