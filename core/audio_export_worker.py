"""動画から音声(MP3)を書き出す QThread ワーカー。

長尺動画の抽出は数秒〜十数秒かかりうるため、UI をブロックしないよう別スレッドで
実行する。ffmpeg 呼び出しは ``core.audio_export`` の純関数を使う。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.audio_export import extract_audio_mp3, DEFAULT_BITRATE


class AudioExportWorker(QThread):
    log_message = Signal(str)
    finished_export = Signal(bool, str)   # (ok, out_path)

    def __init__(
        self,
        src: str,
        out_path: str,
        bitrate: str = DEFAULT_BITRATE,
        parent=None,
    ):
        super().__init__(parent)
        self._src = src
        self._out_path = out_path
        self._bitrate = bitrate

    def run(self) -> None:
        try:
            ok = extract_audio_mp3(self._src, self._out_path, bitrate=self._bitrate)
        except Exception as e:                       # 抽出失敗で UI を止めない
            self.log_message.emit(f"[ERROR] Audio export failed: {e}")
            ok = False
        if ok:
            self.log_message.emit(f"[Audio] Exported {Path(self._out_path).name}")
        else:
            self.log_message.emit("[Audio] Export failed (ffmpeg unavailable or no audio track)")
        self.finished_export.emit(ok, self._out_path)
