"""1 ライブラリ分のメタデータを保持する SQLite データベース。

- 1 つの ``LibraryDatabase`` インスタンスは 1 つの DB ファイル
  (``<root>/.clipmanager/library.db``) に対応する。
- **スレッド安全性**: 1 インスタンス＝1 接続。インスタンスを生成したスレッドで
  のみ使うこと（別スレッドからは別インスタンスを開く）。複数接続の併存に備えて
  WAL モードを有効化している。
- パスはすべてルート相対（POSIX）で保存する。絶対パス解決は ``Library`` が行う。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from core.models import Clip, Folder, Tag

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE clips (
    id             INTEGER PRIMARY KEY,
    rel_path       TEXT UNIQUE NOT NULL,
    title          TEXT NOT NULL,
    source_url     TEXT,
    duration       REAL,
    filesize       INTEGER,
    width          INTEGER,
    height         INTEGER,
    container      TEXT,
    vcodec         TEXT,
    thumbnail_path TEXT,
    subtitle_path  TEXT,
    folder_id      INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    added_at       TEXT,
    downloaded_at  TEXT,
    last_played_at TEXT,
    play_count     INTEGER NOT NULL DEFAULT 0,
    missing        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE folders (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE
);

CREATE TABLE tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT UNIQUE NOT NULL,
    color TEXT
);

CREATE TABLE clip_tags (
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (clip_id, tag_id)
);

CREATE TABLE schema_version (version INTEGER NOT NULL);

CREATE INDEX idx_clips_folder ON clips(folder_id);
CREATE INDEX idx_clips_title  ON clips(title);
"""

# clips テーブルの列（INSERT/UPDATE 用、id を除く）
_CLIP_COLUMNS = [
    "rel_path", "title", "source_url", "duration", "filesize",
    "width", "height", "container", "vcodec", "thumbnail_path",
    "subtitle_path", "folder_id", "added_at", "downloaded_at",
    "last_played_at", "play_count", "missing",
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LibraryDatabase:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    # ------------------------------------------------------------------
    # ライフサイクル
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "LibraryDatabase":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _migrate(self) -> None:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if row is None:
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.execute(
                "INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
            )
            self._conn.commit()
        # 将来のスキーマ変更はここでバージョンを見て移行する。

    @property
    def version(self) -> int:
        row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] if row and row["v"] is not None else 0

    # ------------------------------------------------------------------
    # 行 <-> モデル 変換
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_clip(row: sqlite3.Row) -> Clip:
        return Clip(
            id=row["id"],
            rel_path=row["rel_path"],
            title=row["title"],
            source_url=row["source_url"],
            duration=row["duration"],
            filesize=row["filesize"],
            width=row["width"],
            height=row["height"],
            container=row["container"],
            vcodec=row["vcodec"],
            thumbnail_path=row["thumbnail_path"],
            subtitle_path=row["subtitle_path"],
            folder_id=row["folder_id"],
            added_at=row["added_at"],
            downloaded_at=row["downloaded_at"],
            last_played_at=row["last_played_at"],
            play_count=row["play_count"],
            missing=bool(row["missing"]),
        )

    @staticmethod
    def _clip_values(clip: Clip) -> list:
        return [
            clip.rel_path, clip.title, clip.source_url, clip.duration,
            clip.filesize, clip.width, clip.height, clip.container,
            clip.vcodec, clip.thumbnail_path, clip.subtitle_path,
            clip.folder_id, clip.added_at, clip.downloaded_at,
            clip.last_played_at, clip.play_count, int(clip.missing),
        ]

    # ------------------------------------------------------------------
    # クリップ
    # ------------------------------------------------------------------

    def upsert_clip(self, clip: Clip) -> int:
        """rel_path をキーに挿入または更新し、クリップ id を返す。

        取り込み（同じファイルを再走査）でも重複しないよう冪等にする。
        既存行がある場合、None でない値だけ上書きする。
        """
        existing = self.get_clip_by_rel_path(clip.rel_path)
        if existing is None:
            if clip.added_at is None:
                clip.added_at = _now()
            placeholders = ", ".join("?" for _ in _CLIP_COLUMNS)
            cols = ", ".join(_CLIP_COLUMNS)
            cur = self._conn.execute(
                f"INSERT INTO clips ({cols}) VALUES ({placeholders})",
                self._clip_values(clip),
            )
            self._conn.commit()
            clip.id = cur.lastrowid
            return cur.lastrowid

        # 既存: None でないフィールドのみ更新（取り込みで既存メタを潰さない）
        updates: dict = {}
        for col in _CLIP_COLUMNS:
            if col in ("rel_path", "added_at"):
                continue
            new_val = getattr(clip, col if col != "missing" else "missing")
            if col == "missing":
                new_val = int(clip.missing)
            if new_val is not None:
                updates[col] = new_val
        if updates:
            set_clause = ", ".join(f"{c} = ?" for c in updates)
            self._conn.execute(
                f"UPDATE clips SET {set_clause} WHERE id = ?",
                [*updates.values(), existing.id],
            )
            self._conn.commit()
        clip.id = existing.id
        return existing.id

    def get_clip(self, clip_id: int) -> Clip | None:
        row = self._conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        return self._row_to_clip(row) if row else None

    def get_clip_by_rel_path(self, rel_path: str) -> Clip | None:
        row = self._conn.execute(
            "SELECT * FROM clips WHERE rel_path = ?", (rel_path,)
        ).fetchone()
        return self._row_to_clip(row) if row else None

    def list_clips(
        self,
        *,
        folder_id: int | None = None,
        tag_id: int | None = None,
        search: str | None = None,
        include_missing: bool = True,
        missing_only: bool = False,
        order_by: str = "added_at DESC",
    ) -> list[Clip]:
        sql = "SELECT c.* FROM clips c"
        where: list[str] = []
        params: list = []
        if tag_id is not None:
            sql += " JOIN clip_tags ct ON ct.clip_id = c.id AND ct.tag_id = ?"
            params.append(tag_id)
        if folder_id is not None:
            where.append("c.folder_id = ?")
            params.append(folder_id)
        if search:
            where.append("c.title LIKE ?")
            params.append(f"%{search}%")
        if missing_only:
            where.append("c.missing = 1")
        elif not include_missing:
            where.append("c.missing = 0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        # order_by は内部呼び出しのみ（外部入力を直接渡さない）
        sql += f" ORDER BY c.{order_by}"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_clip(r) for r in rows]

    def delete_clip(self, clip_id: int) -> None:
        self._conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        self._conn.commit()

    def set_missing(self, clip_id: int, missing: bool) -> None:
        self._conn.execute(
            "UPDATE clips SET missing = ? WHERE id = ?", (int(missing), clip_id)
        )
        self._conn.commit()

    def update_clip_path(self, clip_id: int, rel_path: str) -> None:
        self._conn.execute(
            "UPDATE clips SET rel_path = ? WHERE id = ?", (rel_path, clip_id)
        )
        self._conn.commit()

    def mark_played(self, clip_id: int) -> None:
        self._conn.execute(
            "UPDATE clips SET play_count = play_count + 1, last_played_at = ? WHERE id = ?",
            (_now(), clip_id),
        )
        self._conn.commit()

    def count_clips(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM clips").fetchone()["n"]

    def update_metadata(
        self,
        clip_id: int,
        *,
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
        vcodec: str | None = None,
        filesize: int | None = None,
        thumbnail_path: str | None = None,
    ) -> None:
        """ffprobe / サムネイル生成の結果で None でない項目だけ更新する。"""
        fields = {
            "duration": duration, "width": width, "height": height,
            "vcodec": vcodec, "filesize": filesize, "thumbnail_path": thumbnail_path,
        }
        updates = {k: v for k, v in fields.items() if v is not None}
        if not updates:
            return
        set_clause = ", ".join(f"{c} = ?" for c in updates)
        self._conn.execute(
            f"UPDATE clips SET {set_clause} WHERE id = ?",
            [*updates.values(), clip_id],
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # フォルダ
    # ------------------------------------------------------------------

    def add_folder(self, name: str, parent_id: int | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)", (name, parent_id)
        )
        self._conn.commit()
        return cur.lastrowid

    def list_folders(self) -> list[Folder]:
        rows = self._conn.execute("SELECT * FROM folders ORDER BY name").fetchall()
        return [Folder(id=r["id"], name=r["name"], parent_id=r["parent_id"]) for r in rows]

    def rename_folder(self, folder_id: int, name: str) -> None:
        self._conn.execute("UPDATE folders SET name = ? WHERE id = ?", (name, folder_id))
        self._conn.commit()

    def delete_folder(self, folder_id: int) -> None:
        self._conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        self._conn.commit()

    def set_clip_folder(self, clip_id: int, folder_id: int | None) -> None:
        self._conn.execute(
            "UPDATE clips SET folder_id = ? WHERE id = ?", (folder_id, clip_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # タグ
    # ------------------------------------------------------------------

    def add_tag(self, name: str, color: str | None = None) -> int:
        """タグを作成（既存なら既存 id を返す）。"""
        row = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = self._conn.execute(
            "INSERT INTO tags (name, color) VALUES (?, ?)", (name, color)
        )
        self._conn.commit()
        return cur.lastrowid

    def list_tags(self) -> list[Tag]:
        rows = self._conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
        return [Tag(id=r["id"], name=r["name"], color=r["color"]) for r in rows]

    def rename_tag(self, tag_id: int, name: str) -> None:
        self._conn.execute("UPDATE tags SET name = ? WHERE id = ?", (name, tag_id))
        self._conn.commit()

    def delete_tag(self, tag_id: int) -> None:
        self._conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        self._conn.commit()

    def assign_tag(self, clip_id: int, tag_id: int) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO clip_tags (clip_id, tag_id) VALUES (?, ?)",
            (clip_id, tag_id),
        )
        self._conn.commit()

    def unassign_tag(self, clip_id: int, tag_id: int) -> None:
        self._conn.execute(
            "DELETE FROM clip_tags WHERE clip_id = ? AND tag_id = ?", (clip_id, tag_id)
        )
        self._conn.commit()

    def tags_for_clip(self, clip_id: int) -> list[Tag]:
        rows = self._conn.execute(
            """
            SELECT t.* FROM tags t
            JOIN clip_tags ct ON ct.tag_id = t.id
            WHERE ct.clip_id = ?
            ORDER BY t.name
            """,
            (clip_id,),
        ).fetchall()
        return [Tag(id=r["id"], name=r["name"], color=r["color"]) for r in rows]
