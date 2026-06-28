"""クリップのメタデータ補完とサムネイル生成をワーカースレッドで行う QThread。

取り込み直後のクリップは duration / 解像度 / コーデック / サムネイルが未設定の
ことがある。ffprobe / ffmpeg は時間がかかるため別スレッドで実行し、DB はこの
スレッド専用接続（``Library.open_db()``）で更新する。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.library import Library
from core.metadata import probe
from core.thumbnails import generate_thumbnail


class EnrichWorker(QThread):
    progress = Signal(int, int)     # (done, total)
    clip_updated = Signal(int)      # clip id
    log_message = Signal(str)
    finished_enrich = Signal(int)   # number of clips updated

    def __init__(self, root: str, name: str | None = None, force: bool = False, parent=None):
        super().__init__(parent)
        self._root = root
        self._name = name
        self._force = force        # True: 既存メタ/サムネも作り直す
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        lib = Library(self._root, self._name)
        db = lib.open_db()
        try:
            clips = db.list_clips()
            # 補完が必要なものだけ対象に（force 時は全件）
            targets = [
                c for c in clips
                if self._force
                or c.duration is None
                or c.thumbnail_path is None
            ]
            total = len(targets)
            self.log_message.emit(f"Enriching {total} clip(s)...")
            updated = 0
            for i, clip in enumerate(targets, start=1):
                if self._cancelled:
                    break
                abs_path = lib.to_abs(clip.rel_path)
                if not abs_path.is_file():
                    self.progress.emit(i, total)
                    continue

                changed = False

                # --- metadata (ffprobe) ---
                if self._force or clip.duration is None:
                    meta = probe(abs_path)
                    if meta:
                        db.update_metadata(
                            clip.id,
                            duration=meta.get("duration"),
                            width=meta.get("width"),
                            height=meta.get("height"),
                            vcodec=meta.get("vcodec"),
                            filesize=meta.get("filesize"),
                        )
                        clip.duration = clip.duration or meta.get("duration")
                        changed = True

                # --- thumbnail (ffmpeg) ---
                if self._force or clip.thumbnail_path is None:
                    thumb_abs = lib.thumbnails_dir / f"{clip.id}.jpg"
                    if generate_thumbnail(abs_path, thumb_abs, duration=clip.duration):
                        rel = lib.to_rel(thumb_abs)
                        db.update_metadata(clip.id, thumbnail_path=rel)
                        changed = True

                if changed:
                    updated += 1
                    self.clip_updated.emit(clip.id)
                self.progress.emit(i, total)

            self.log_message.emit(f"Enrich complete: {updated} clip(s) updated.")
            self.finished_enrich.emit(updated)
        except Exception as e:                      # 補完失敗で UI を止めない
            self.log_message.emit(f"[ERROR] Enrich failed: {e}")
            self.finished_enrich.emit(0)
        finally:
            db.close()
