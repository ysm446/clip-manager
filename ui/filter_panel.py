"""左ペインの階層ツリー（実フォルダ ＋ タグ ＋ 欠落）。

フォルダ階層は **ライブラリルート配下の実ディレクトリ**を表す。選択が変わると
``filter_changed(dict)`` を emit する::

    {"folder_path": str|None, "tag_id": int|None, "missing_only": bool}

フォルダ右クリックから「ここにダウンロード」「新規サブフォルダ」「名前変更」
「エクスプローラで開く」を行える。タグは DB の tags を使う（横断分類）。
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
    QStyle,
)

_ROLE_KIND = Qt.ItemDataRole.UserRole       # "folder" | "tag" | "missing" | "header"
_ROLE_ID = Qt.ItemDataRole.UserRole + 1     # folder=rel path(str, ""=root) / tag=id(int)


class FilterPanel(QWidget):
    filter_changed = Signal(dict)
    download_here_requested = Signal(str)    # 保存先（絶対パス）
    open_folder_requested = Signal(str)      # フォルダ（絶対パス）
    library_changed = Signal()               # フォルダ/タグ構成が変わった

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library = None
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

        # 実フォルダのルート（= ライブラリ）。選択で全件表示。
        root_item = self._make_item(f"{self._library.name}  (all)", "folder", "")
        root_item.setIcon(0, self._dir_icon())
        self._tree.addTopLevelItem(root_item)
        items = {"": root_item}
        for rel in self._library.list_dirs():
            parts = rel.split("/")
            parent_rel = "/".join(parts[:-1])
            parent_item = items.get(parent_rel, root_item)
            item = self._make_item(parts[-1], "folder", rel)
            item.setIcon(0, self._dir_icon())
            parent_item.addChild(item)
            items[rel] = item
        root_item.setExpanded(True)

        self._tree.addTopLevelItem(self._make_item("Missing files", "missing"))

        # タグ（横断分類）
        if self._db is not None:
            tags_header = self._make_item("Tags", "header")
            self._tree.addTopLevelItem(tags_header)
            for t in self._db.list_tags():
                tags_header.addChild(self._make_item(f"# {t.name}", "tag", t.id))
            tags_header.setExpanded(True)

        self._tree.setCurrentItem(root_item)
        self._tree.blockSignals(False)

    def _dir_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

    @staticmethod
    def _make_item(label: str, kind: str, item_id=None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _ROLE_KIND, kind)
        item.setData(0, _ROLE_ID, item_id)
        if kind == "header":
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
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
            # ルート("")は None（全件）、サブフォルダはその配下。
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
        kind, rel = self._selected()
        parent_rel = rel if kind == "folder" else ""   # 選択フォルダ配下、なければルート
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
            if item_id:   # ルート自体は改名しない
                menu.addAction("Rename...").triggered.connect(
                    lambda: self._rename_folder(item_id)
                )
            menu.addAction("Open in Explorer").triggered.connect(
                lambda: self.open_folder_requested.emit(abs_dir)
            )
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
