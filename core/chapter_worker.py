"""YouTube チャプターをマーカー（kind='chapter', source='youtube'）として取り込む
QThread ワーカー。

チャプター一覧が渡されればそれを使い、無ければ ``url`` から取得する（ネットワーク）。
各チャプター開始位置のサムネイルを ffmpeg で生成する。DB はこのスレッド専用接続
（``Library.open_db()``）で更新する。再取り込み時は既存の YouTube 由来チャプターを
入れ替える（重複防止）。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.library import Library
from core.chapters import fetch_chapters
from core.thumbnails import generate_thumbnail

_SOURCE = "youtube"


class ChapterImportWorker(QThread):
    log_message = Signal(str)
    finished_import = Signal(int, int)   # (clip_id, imported count)

    def __init__(
        self,
        root: str,
        name: str | None,
        clip_id: int,
        *,
        url: str | None = None,
        chapters: list[dict] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._root = root
        self._name = name
        self._clip_id = clip_id
        self._url = url
        self._chapters = chapters

    def run(self) -> None:
        lib = Library(self._root, self._name)
        db = lib.open_db()
        try:
            clip = db.get_clip(self._clip_id)
            if clip is None:
                self.finished_import.emit(self._clip_id, 0)
                return

            chapters = self._chapters
            if chapters is None:
                if not self._url:
                    self.finished_import.emit(self._clip_id, 0)
                    return
                self.log_message.emit(f"[Chapters] Fetching from {self._url}")
                chapters = fetch_chapters(self._url)

            if not chapters:
                self.log_message.emit("[Chapters] No chapters found.")
                self.finished_import.emit(self._clip_id, 0)
                return

            self._remove_existing(lib, db)

            media_abs = lib.to_abs(clip.rel_path)
            count = 0
            for ch in chapters:
                start = ch["start"]
                position_ms = int(start * 1000)
                end_ms = int(ch["end"] * 1000) if ch.get("end") is not None else None
                title = ch.get("title") or None
                mid = db.add_marker(
                    self._clip_id, position_ms,
                    end_ms=end_ms, kind="chapter", title=title, source=_SOURCE,
                )
                # 開始位置のフレームをサムネイルに
                try:
                    out = lib.markers_dir / f"{mid}.jpg"
                    if generate_thumbnail(media_abs, out, at_seconds=start):
                        db.update_marker_thumbnail(mid, lib.to_rel(out))
                except Exception as e:
                    self.log_message.emit(f"[Chapters] thumbnail failed: {e}")
                count += 1

            self.log_message.emit(f"[Chapters] Imported {count} chapter(s).")
            self.finished_import.emit(self._clip_id, count)
        except Exception as e:                      # 取り込み失敗で UI を止めない
            self.log_message.emit(f"[ERROR] Chapter import failed: {e}")
            self.finished_import.emit(self._clip_id, 0)
        finally:
            db.close()

    def _remove_existing(self, lib: Library, db) -> None:
        """既存の YouTube 由来チャプター（と画像）を削除して重複を防ぐ。"""
        for m in db.list_markers(self._clip_id):
            if m.source != _SOURCE:
                continue
            if m.thumbnail_path:
                try:
                    p = lib.to_abs(m.thumbnail_path)
                    if p.is_file():
                        p.unlink()
                except OSError:
                    pass
            db.delete_marker(m.id)
