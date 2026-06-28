"""複数ライブラリ（ルートディレクトリ）の登録・切替を管理する。

- 登録ライブラリの一覧と「アクティブなライブラリ」を **QSettings** に保持する
  （真実の源泉は各ライブラリ内の DB。ここはポインタのみを持つ）。
- 一覧は JSON 文字列として 1 キーに格納する。
"""
from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import QSettings

from core.library import Library
from core.models import LibraryInfo

_KEY_REGISTRY = "libraries/registry"
_KEY_ACTIVE = "libraries/active"


class LibraryManager:
    def __init__(self, settings: QSettings | None = None):
        # 既定はアプリスコープの QSettings()（main.py が org/app を設定）。
        # テスト時は IniFormat の QSettings を注入、または setDefaultFormat/
        # setPath で差し替えできる。
        self._qs = settings if settings is not None else QSettings()

    # ------------------------------------------------------------------
    # レジストリ
    # ------------------------------------------------------------------

    def _load(self) -> list[LibraryInfo]:
        raw = self._qs.value(_KEY_REGISTRY, "", type=str)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return [
            LibraryInfo(root=d["root"], name=d.get("name") or "", last_used=d.get("last_used"))
            for d in data
            if d.get("root")
        ]

    def _save(self, infos: list[LibraryInfo]) -> None:
        data = [
            {"root": i.root, "name": i.name, "last_used": i.last_used} for i in infos
        ]
        self._qs.setValue(_KEY_REGISTRY, json.dumps(data, ensure_ascii=False))

    def list(self) -> list[LibraryInfo]:
        return self._load()

    @staticmethod
    def _norm(root: str) -> str:
        from pathlib import Path
        return str(Path(root).resolve())

    def add(self, root: str, name: str | None = None, make_active: bool = True) -> LibraryInfo:
        """ライブラリを登録（既存なら既存項目を返す）。DB も初期化する。"""
        root = self._norm(root)
        infos = self._load()
        for info in infos:
            if self._norm(info.root) == root:
                if make_active:
                    self.set_active(root)
                return info

        info = LibraryInfo(
            root=root,
            name=name or Library(root).name,
            last_used=datetime.now().isoformat(timespec="seconds"),
        )
        infos.append(info)
        self._save(infos)
        # DB ファイルを作成（スキーマ初期化）
        Library(root, info.name).open_db().close()
        if make_active:
            self.set_active(root)
        return info

    def remove(self, root: str) -> None:
        """レジストリから登録解除（実ファイル・DB は削除しない）。"""
        root = self._norm(root)
        infos = [i for i in self._load() if self._norm(i.root) != root]
        self._save(infos)
        if self.active_root() and self._norm(self.active_root()) == root:
            self._qs.setValue(_KEY_ACTIVE, infos[0].root if infos else "")

    # ------------------------------------------------------------------
    # アクティブライブラリ
    # ------------------------------------------------------------------

    def active_root(self) -> str | None:
        root = self._qs.value(_KEY_ACTIVE, "", type=str)
        return root or None

    def set_active(self, root: str) -> None:
        root = self._norm(root)
        self._qs.setValue(_KEY_ACTIVE, root)
        # last_used を更新
        infos = self._load()
        for info in infos:
            if self._norm(info.root) == root:
                info.last_used = datetime.now().isoformat(timespec="seconds")
        self._save(infos)

    def active_library(self) -> Library | None:
        root = self.active_root()
        if not root:
            return None
        name = next(
            (i.name for i in self._load() if self._norm(i.root) == self._norm(root)),
            None,
        )
        return Library(root, name)
