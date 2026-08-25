"""yt-dlp の更新確認/更新を別スレッドで行う QThread ワーカー。"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core import ytdlp_updater


class YtdlpCheckWorker(QThread):
    """PyPI の最新バージョンを取得する。``finished_check(latest or "")``"""
    finished_check = Signal(str)

    def run(self) -> None:
        self.finished_check.emit(ytdlp_updater.latest_version() or "")


class YtdlpUpdateWorker(QThread):
    """``pip install -U yt-dlp`` を実行する。``finished_update(ok, new_version, output)``"""
    finished_update = Signal(bool, str, str)

    def run(self) -> None:
        try:
            ok, out = ytdlp_updater.update()
        except Exception as e:                       # 失敗で UI を止めない
            ok, out = False, str(e)
        new_ver = ytdlp_updater.installed_version() or ""
        self.finished_update.emit(ok, new_ver, out)
