"""1 つのライブラリ（ルートディレクトリ＋自己完結 DB）を表す高レベル API。

- DB は ``<root>/.clipmanager/library.db``、サムネイルは
  ``<root>/.clipmanager/thumbnails/`` に置く。
- ファイルパスは DB ではルート相対（POSIX）で保持し、ここで絶対パスへ解決する。
- ``open_db()`` で得た ``LibraryDatabase`` は呼び出しスレッドで使うこと
  （スレッドごとに別接続。詳細は ``core.database`` 参照）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.database import LibraryDatabase
from core.models import Clip

# ライブラリ走査で取り込む拡張子（動画＋音声）
MEDIA_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".ts", ".m4v",
    ".m4a", ".mp3", ".aac", ".flac", ".wav", ".opus", ".ogg",
}

META_DIRNAME = ".clipmanager"
DB_FILENAME = "library.db"
THUMBS_DIRNAME = "thumbnails"


class Library:
    def __init__(self, root: str | Path, name: str | None = None):
        self.root = Path(root)
        self.name = name or self.root.name

    # ------------------------------------------------------------------
    # パス
    # ------------------------------------------------------------------

    @property
    def meta_dir(self) -> Path:
        return self.root / META_DIRNAME

    @property
    def db_path(self) -> Path:
        return self.meta_dir / DB_FILENAME

    @property
    def thumbnails_dir(self) -> Path:
        return self.meta_dir / THUMBS_DIRNAME

    def open_db(self) -> LibraryDatabase:
        """このライブラリの DB を開く（呼び出しスレッド専用の接続）。"""
        return LibraryDatabase(self.db_path)

    def to_rel(self, abs_path: str | Path) -> str:
        """絶対パス → ルート相対（POSIX）。ルート外なら ValueError。"""
        rel = Path(abs_path).resolve().relative_to(self.root.resolve())
        return rel.as_posix()

    def to_abs(self, rel_path: str) -> Path:
        """ルート相対 → 絶対パス。"""
        return (self.root / Path(rel_path)).resolve()

    def is_inside(self, abs_path: str | Path) -> bool:
        try:
            Path(abs_path).resolve().relative_to(self.root.resolve())
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # 取り込み
    # ------------------------------------------------------------------

    @staticmethod
    def is_media_file(path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS

    def _clip_from_file(self, abs_path: Path) -> Clip:
        """ファイルから基本メタのみのクリップを作る（ffprobe は使わない）。

        duration / 解像度 / コーデックは後続フェーズで補完する（None のまま）。
        """
        stat = abs_path.stat()
        downloaded_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        return Clip(
            rel_path=self.to_rel(abs_path),
            title=abs_path.stem,
            filesize=stat.st_size,
            container=abs_path.suffix.lower().lstrip("."),
            downloaded_at=downloaded_at,
        )

    def scan(self, db: LibraryDatabase, progress_cb=None) -> int:
        """ルート配下のメディアファイルを走査して DB に取り込む。

        ``.clipmanager/`` 配下は除外。戻り値は新規に取り込んだ件数。
        ``progress_cb(processed, abs_path)`` があれば各ファイルで呼ぶ。
        """
        added = 0
        processed = 0
        meta = self.meta_dir.resolve()
        for path in self.root.rglob("*"):
            if meta in path.resolve().parents or path.resolve() == meta:
                continue
            if not self.is_media_file(path):
                continue
            processed += 1
            rel = self.to_rel(path)
            if db.get_clip_by_rel_path(rel) is None:
                db.upsert_clip(self._clip_from_file(path))
                added += 1
            if progress_cb:
                progress_cb(processed, path)
        return added

    def register_download(self, db: LibraryDatabase, payload: dict) -> int | None:
        """ダウンロード完了ペイロードをライブラリへ登録し clip id を返す。

        ファイルがライブラリ外なら登録せず None を返す。
        payload は ``core.downloader`` の ``download_succeeded`` シグナルの dict。
        """
        file_path = payload.get("file_path")
        if not file_path:
            return None
        abs_path = Path(file_path)
        if not self.is_inside(abs_path):
            return None

        rel = self.to_rel(abs_path)
        sub = payload.get("subtitle_path")
        sub_rel = None
        if sub and self.is_inside(sub):
            sub_rel = self.to_rel(sub)

        clip = Clip(
            rel_path=rel,
            title=payload.get("title") or abs_path.stem,
            source_url=payload.get("source_url"),
            duration=payload.get("duration"),
            filesize=payload.get("filesize"),
            width=payload.get("width"),
            height=payload.get("height"),
            container=payload.get("container") or abs_path.suffix.lower().lstrip("."),
            vcodec=payload.get("vcodec"),
            subtitle_path=sub_rel,
            downloaded_at=datetime.now().isoformat(timespec="seconds"),
        )
        return db.upsert_clip(clip)

    def refresh_missing(self, db: LibraryDatabase) -> int:
        """DB の各クリップの実ファイル存在を確認し missing を更新。

        戻り値は「見つからない」クリップ件数。
        """
        missing = 0
        for clip in db.list_clips():
            exists = self.to_abs(clip.rel_path).is_file()
            if clip.missing != (not exists):
                db.set_missing(clip.id, not exists)
            if not exists:
                missing += 1
        return missing
