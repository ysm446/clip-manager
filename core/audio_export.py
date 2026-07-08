"""ffmpeg を使った音声抽出（Qt 非依存・純関数）。

動画（mp4 等）から音声トラックだけを取り出して MP3 として保存する。ffmpeg が
無い、または失敗した場合は ``False`` を返す。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0

# 既定のオーディオビットレート（MP3）
DEFAULT_BITRATE = "192k"


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def extract_audio_mp3(
    src: str | Path,
    out_path: str | Path,
    bitrate: str = DEFAULT_BITRATE,
    ffmpeg: str | None = None,
    timeout: int = 3600,
) -> bool:
    """``src`` の音声を ``out_path`` (MP3) に書き出す。成功で True。

    映像トラックは破棄し（``-vn``）、libmp3lame で ``bitrate`` へ再エンコードする。
    ``src`` に音声トラックが無い場合や ffmpeg が無い場合は False。
    """
    exe = ffmpeg or ffmpeg_path()
    if not exe:
        return False
    src = Path(src)
    if not src.is_file():
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        exe, "-y", "-i", str(src),
        "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
        str(out_path),
    ]
    try:
        # 出力（stderr）はデコードしない（bytes のまま）。text=True だと
        # Windows 既定の cp932 で UTF-8 メタデータの復号に失敗するため。
        res = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0 and out_path.is_file()
