"""1 つのライブラリ（ルートディレクトリ＋自己完結 DB）を表す高レベル API。

- DB は ``<root>/.clipmanager/library.db``、サムネイルは
  ``<root>/.clipmanager/thumbnails/`` に置く。
- ファイルパスは DB ではルート相対（POSIX）で保持し、ここで絶対パスへ解決する。
- ``open_db()`` で得た ``LibraryDatabase`` は呼び出しスレッドで使うこと
  （スレッドごとに別接続。詳細は ``core.database`` 参照）。
"""
from __future__ import annotations

import shutil
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

    @property
    def markers_dir(self) -> Path:
        return self.meta_dir / "markers"

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

    # ------------------------------------------------------------------
    # 実フォルダ（ディスク上のディレクトリ）
    # ------------------------------------------------------------------

    def list_dirs(self) -> list[str]:
        """ルート配下の実ディレクトリ（ルート相対 POSIX）一覧。`.clipmanager` 除外。"""
        meta = self.meta_dir.resolve()
        dirs: list[str] = []
        for p in self.root.rglob("*"):
            if not p.is_dir():
                continue
            rp = p.resolve()
            if rp == meta or meta in rp.parents:
                continue
            dirs.append(self.to_rel(p))
        return sorted(dirs)

    def make_dir(self, parent_rel: str | None, name: str) -> str:
        """親フォルダ（ルート相対、None ならルート直下）に新フォルダを作る。"""
        name = name.strip()
        if not name or any(c in name for c in '\\/:*?"<>|'):
            raise ValueError("フォルダ名に使用できない文字が含まれています。")
        parent = self.root if not parent_rel else self.to_abs(parent_rel)
        new_dir = parent / name
        if new_dir.exists():
            raise FileExistsError(f"同名のフォルダが既に存在します: {name}")
        new_dir.mkdir(parents=True)
        return self.to_rel(new_dir)

    def rename_dir(self, db: LibraryDatabase, old_rel: str, new_name: str) -> str:
        """実フォルダを改名し、配下クリップの rel_path / subtitle_path を追従させる。"""
        new_name = new_name.strip()
        if not new_name or any(c in new_name for c in '\\/:*?"<>|'):
            raise ValueError("フォルダ名に使用できない文字が含まれています。")
        old_abs = self.to_abs(old_rel)
        if not old_abs.is_dir():
            raise FileNotFoundError("フォルダが見つかりません。")
        new_abs = old_abs.with_name(new_name)
        if new_abs.exists():
            raise FileExistsError(f"同名のフォルダが既に存在します: {new_name}")
        old_abs.rename(new_abs)

        old_prefix = old_rel.rstrip("/") + "/"
        new_rel = self.to_rel(new_abs)
        new_prefix = new_rel + "/"
        for clip in db.list_clips():
            if clip.rel_path.startswith(old_prefix):
                db.update_clip_path(clip.id, new_prefix + clip.rel_path[len(old_prefix):])
            if clip.subtitle_path and clip.subtitle_path.startswith(old_prefix):
                db.update_subtitle_path(
                    clip.id, new_prefix + clip.subtitle_path[len(old_prefix):]
                )
        return new_rel

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

    # ------------------------------------------------------------------
    # ファイル操作（実ファイルと DB を一括更新）
    # ------------------------------------------------------------------

    def _sidecar_subtitle(self, clip: Clip) -> Path | None:
        """クリップに紐づく字幕サイドカーの絶対パス（存在すれば）。"""
        if clip.subtitle_path:
            p = self.to_abs(clip.subtitle_path)
            return p if p.is_file() else None
        return None

    def rename_clip(self, db: LibraryDatabase, clip_id: int, new_stem: str) -> str:
        """クリップのファイル名（拡張子を除く部分）を変更する。

        同じディレクトリ内でリネームし、DB の rel_path / title と字幕サイドカーも
        追従させる。戻り値は新しい rel_path。失敗時は例外。
        """
        new_stem = new_stem.strip()
        if not new_stem or any(c in new_stem for c in '\\/:*?"<>|'):
            raise ValueError("ファイル名に使用できない文字が含まれています。")
        clip = db.get_clip(clip_id)
        if clip is None:
            raise ValueError("クリップが見つかりません。")
        src = self.to_abs(clip.rel_path)
        if not src.is_file():
            raise FileNotFoundError("元ファイルが見つかりません。")
        dst = src.with_name(new_stem + src.suffix)
        if dst.exists():
            raise FileExistsError(f"同名のファイルが既に存在します: {dst.name}")

        # 字幕サイドカー（タイトルと同じ stem の場合のみ追従）
        sub = self._sidecar_subtitle(clip)
        new_sub_rel = clip.subtitle_path
        if sub is not None and sub.name.startswith(src.stem):
            new_sub = sub.with_name(new_stem + sub.name[len(src.stem):])
            sub.rename(new_sub)
            new_sub_rel = self.to_rel(new_sub)

        src.rename(dst)
        new_rel = self.to_rel(dst)
        db.update_clip_path(clip_id, new_rel)
        db.update_title(clip_id, new_stem)
        if new_sub_rel != clip.subtitle_path:
            db.update_subtitle_path(clip_id, new_sub_rel)
        return new_rel

    def move_clip(self, db: LibraryDatabase, clip_id: int, dest_dir: str | Path) -> str:
        """クリップの実ファイルをライブラリ内の別ディレクトリへ移動する。

        dest_dir はライブラリ内であること。DB の rel_path と字幕サイドカーも追従。
        戻り値は新しい rel_path。
        """
        clip = db.get_clip(clip_id)
        if clip is None:
            raise ValueError("クリップが見つかりません。")
        dest = Path(dest_dir).resolve()
        if not self.is_inside(dest):
            raise ValueError("移動先がライブラリの外です。")
        dest.mkdir(parents=True, exist_ok=True)
        src = self.to_abs(clip.rel_path)
        if not src.is_file():
            raise FileNotFoundError("元ファイルが見つかりません。")
        dst = dest / src.name
        if dst.exists():
            raise FileExistsError(f"移動先に同名のファイルが既に存在します: {dst.name}")

        sub = self._sidecar_subtitle(clip)
        new_sub_rel = clip.subtitle_path
        if sub is not None:
            new_sub = dest / sub.name
            if new_sub.exists():
                raise FileExistsError(f"移動先に同名の字幕が既に存在します: {new_sub.name}")

        shutil.move(str(src), str(dst))
        if sub is not None:
            shutil.move(str(sub), str(dest / sub.name))
            new_sub_rel = self.to_rel(dest / sub.name)

        new_rel = self.to_rel(dst)
        db.update_clip_path(clip_id, new_rel)
        if new_sub_rel != clip.subtitle_path:
            db.update_subtitle_path(clip_id, new_sub_rel)
        return new_rel

    def duplicate_clip(self, db: LibraryDatabase, clip_id: int) -> int:
        """実ファイルを複製し、新しいクリップとして登録する。戻り値は新 id。"""
        clip = db.get_clip(clip_id)
        if clip is None:
            raise ValueError("クリップが見つかりません。")
        src = self.to_abs(clip.rel_path)
        if not src.is_file():
            raise FileNotFoundError("元ファイルが見つかりません。")

        # "name (copy).ext" / 衝突時は連番
        base = f"{src.stem} (copy)"
        candidate = src.with_name(base + src.suffix)
        n = 2
        while candidate.exists():
            candidate = src.with_name(f"{src.stem} (copy {n}){src.suffix}")
            n += 1
        shutil.copy2(src, candidate)

        new_clip = Clip(
            rel_path=self.to_rel(candidate),
            title=candidate.stem,
            source_url=clip.source_url,
            duration=clip.duration,
            filesize=candidate.stat().st_size,
            width=clip.width,
            height=clip.height,
            container=clip.container,
            vcodec=clip.vcodec,
            folder_id=clip.folder_id,
            downloaded_at=datetime.now().isoformat(timespec="seconds"),
        )
        return db.upsert_clip(new_clip)

    def delete_clip(
        self, db: LibraryDatabase, clip_id: int, to_trash: bool = True
    ) -> None:
        """クリップの実ファイル（＋字幕・サムネ）を削除し DB レコードも消す。

        ``to_trash=True`` ならゴミ箱へ送る（Send2Trash）。利用不可・失敗時は
        永久削除にフォールバックする。
        """
        clip = db.get_clip(clip_id)
        if clip is None:
            return
        targets: list[Path] = []
        media = self.to_abs(clip.rel_path)
        if media.is_file():
            targets.append(media)
        sub = self._sidecar_subtitle(clip)
        if sub is not None:
            targets.append(sub)
        if clip.thumbnail_path:
            thumb = self.to_abs(clip.thumbnail_path)
            if thumb.is_file():
                targets.append(thumb)

        for path in targets:
            self._remove_path(path, to_trash)
        db.delete_clip(clip_id)

    @staticmethod
    def _remove_path(path: Path, to_trash: bool) -> None:
        if to_trash:
            try:
                from send2trash import send2trash
                send2trash(str(path))
                return
            except Exception:
                pass  # ゴミ箱が使えなければ永久削除へフォールバック
        try:
            path.unlink()
        except OSError:
            pass
