"""ffmpeg を使ったサムネイル生成（Qt 非依存・純関数）。

動画の指定時刻から 1 フレームを切り出して JPEG として保存する。ffmpeg が無い、
または失敗した場合は ``False`` を返す。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0

# サムネイルの横幅（縦はアスペクト比維持）
THUMB_WIDTH = 320


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _seek_seconds(duration: float | None) -> float:
    """切り出し位置。長さが分かれば 10%（最大 10 秒）、不明なら 1 秒。"""
    if duration and duration > 0:
        return min(duration * 0.1, 10.0)
    return 1.0


def generate_thumbnail(
    src: str | Path,
    out_path: str | Path,
    duration: float | None = None,
    ffmpeg: str | None = None,
    width: int = THUMB_WIDTH,
    at_seconds: float | None = None,
) -> bool:
    """``src`` のサムネイルを ``out_path`` (JPEG) に生成する。成功で True。

    ``at_seconds`` を指定するとその時刻のフレームを使う（ブックマーク/チャプター用）。
    未指定なら長さから自動決定する。
    """
    exe = ffmpeg or ffmpeg_path()
    if not exe:
        return False
    src = Path(src)
    if not src.is_file():
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ss = at_seconds if at_seconds is not None else _seek_seconds(duration)
    ss = max(0.0, ss)
    cmd = [
        exe, "-y", "-ss", f"{ss:.2f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-1",
        "-q:v", "3", str(out_path),
    ]
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0 and out_path.is_file()
