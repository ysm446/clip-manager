"""ライブラリ走査をワーカースレッドで行う QThread。

走査はファイル数が多いと時間がかかるため、UI をブロックしないよう別スレッドで
実行する。**このスレッド専用の接続**として ``Library.open_db()`` を run() 内で
開く（DB 接続をスレッド間で共有しない原則を守る）。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.library import Library


class ScanWorker(QThread):
    progress = Signal(int, str)        # (processed count, current file path)
    log_message = Signal(str)
    finished_scan = Signal(int, int)   # (added, missing)

    def __init__(self, root: str, name: str | None = None, parent=None):
        super().__init__(parent)
        self._root = root
        self._name = name

    def run(self) -> None:
        lib = Library(self._root, self._name)
        db = lib.open_db()
        try:
            self.log_message.emit(f"Scanning: {self._root}")
            added = lib.scan(db, progress_cb=lambda n, p: self.progress.emit(n, str(p)))
            missing = lib.refresh_missing(db)
            self.finished_scan.emit(added, missing)
            self.log_message.emit(
                f"Scan complete: {added} new, {missing} missing."
            )
        finally:
            db.close()
