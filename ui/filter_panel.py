"""左ペインの絞り込みツリー（フォルダ / タグ / 欠落）。

DB アクセスは主スレッドの ``LibraryDatabase`` を ``set_db`` で受け取る。選択が
変わると ``filter_changed(dict)`` を emit する。dict のキー::

    {"folder_id": int|None, "tag_id": int|None, "missing_only": bool}

フォルダ/タグの作成・改名・削除もここで行う（変更後 ``library_changed`` を emit）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
)

# item の種別を UserRole に格納
_ROLE_KIND = Qt.ItemDataRole.UserRole       # "all" | "missing" | "folder" | "tag" | "header"
_ROLE_ID = Qt.ItemDataRole.UserRole + 1     # folder/tag id


class FilterPanel(QWidget):
    filter_changed = Signal(dict)
    library_changed = Signal()   # フォルダ/タグの構成が変わった

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
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

    def set_db(self, db) -> None:
        self._db = db
        self.rebuild()

    def rebuild(self) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()

        all_item = self._make_item("All clips", "all")
        self._tree.addTopLevelItem(all_item)
        self._tree.addTopLevelItem(self._make_item("Missing files", "missing"))

        if self._db is not None:
            # Folders（parent_id で入れ子）
            folders_header = self._make_item("Folders", "header")
            self._tree.addTopLevelItem(folders_header)
            folders = self._db.list_folders()
            by_parent: dict = {}
            for f in folders:
                by_parent.setdefault(f.parent_id, []).append(f)

            def add_children(parent_item, parent_id):
                for f in by_parent.get(parent_id, []):
                    item = self._make_item(f.name, "folder", f.id)
                    parent_item.addChild(item)
                    add_children(item, f.id)

            add_children(folders_header, None)
            folders_header.setExpanded(True)

            # Tags
            tags_header = self._make_item("Tags", "header")
            self._tree.addTopLevelItem(tags_header)
            for t in self._db.list_tags():
                tags_header.addChild(self._make_item(f"# {t.name}", "tag", t.id))
            tags_header.setExpanded(True)

        self._tree.setCurrentItem(all_item)
        self._tree.blockSignals(False)

    @staticmethod
    def _make_item(label: str, kind: str, item_id: int | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _ROLE_KIND, kind)
        item.setData(0, _ROLE_ID, item_id)
        if kind == "header":
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 選択不可（見出し）
        return item

    # ------------------------------------------------------------------
    # Selection -> filter
    # ------------------------------------------------------------------

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        kind = current.data(0, _ROLE_KIND)
        item_id = current.data(0, _ROLE_ID)
        if kind == "folder":
            self.filter_changed.emit({"folder_id": item_id, "tag_id": None, "missing_only": False})
        elif kind == "tag":
            self.filter_changed.emit({"folder_id": None, "tag_id": item_id, "missing_only": False})
        elif kind == "missing":
            self.filter_changed.emit({"folder_id": None, "tag_id": None, "missing_only": True})
        elif kind == "all":
            self.filter_changed.emit({"folder_id": None, "tag_id": None, "missing_only": False})

    # ------------------------------------------------------------------
    # Folder / Tag CRUD
    # ------------------------------------------------------------------

    def _selected(self) -> tuple[str | None, int | None]:
        item = self._tree.currentItem()
        if item is None:
            return None, None
        return item.data(0, _ROLE_KIND), item.data(0, _ROLE_ID)

    def _new_folder(self) -> None:
        if self._db is None:
            return
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not (ok and name.strip()):
            return
        # 選択中がフォルダならその子として作成
        kind, fid = self._selected()
        parent_id = fid if kind == "folder" else None
        self._db.add_folder(name.strip(), parent_id)
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
        if kind not in ("folder", "tag"):
            return
        menu = QMenu(self)
        rename_act = menu.addAction("Rename...")
        delete_act = menu.addAction("Delete")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is rename_act:
            self._rename(kind, item)
        elif chosen is delete_act:
            self._delete(kind, item)

    def _rename(self, kind: str, item: QTreeWidgetItem) -> None:
        item_id = item.data(0, _ROLE_ID)
        current = item.text(0).lstrip("# ").strip()
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=current)
        if not (ok and name.strip()):
            return
        if kind == "folder":
            self._db.rename_folder(item_id, name.strip())
        else:
            self._db.rename_tag(item_id, name.strip())
        self.rebuild()
        self.library_changed.emit()

    def _delete(self, kind: str, item: QTreeWidgetItem) -> None:
        item_id = item.data(0, _ROLE_ID)
        label = item.text(0)
        msg = (
            f"Delete {kind} '{label}'?\n"
            "（クリップ自体は削除されません。フォルダの場合、子フォルダも削除されます。）"
        )
        if QMessageBox.question(self, "Delete", msg) != QMessageBox.StandardButton.Yes:
            return
        if kind == "folder":
            self._db.delete_folder(item_id)
        else:
            self._db.delete_tag(item_id)
        self.rebuild()
        self.library_changed.emit()
