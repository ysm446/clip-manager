"""ffprobe を使ったメディアメタデータ取得（Qt 非依存・純関数）。

システムにインストール済みの ffprobe を subprocess で呼び出す。ffprobe が無い
場合や解析に失敗した場合は ``None`` を返し、呼び出し側はメタ補完をスキップする。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# Windows でコンソール窓を出さない
_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def probe(path: str | Path, ffprobe: str | None = None) -> dict | None:
    """メディアファイルを解析し、主要メタデータを返す。

    戻り値（取得できた項目のみ。失敗時は None）::

        {"duration": float|None, "width": int|None, "height": int|None,
         "vcodec": str|None, "filesize": int|None}
    """
    exe = ffprobe or ffprobe_path()
    if not exe:
        return None
    path = Path(path)
    if not path.is_file():
        return None

    cmd = [
        exe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout:
        return None

    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next(
        (s for s in streams if s.get("codec_type") == "video"
         and s.get("disposition", {}).get("attached_pic", 0) == 0),
        None,
    )

    def _to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    duration = _to_float(fmt.get("duration"))
    if duration is None and video:
        duration = _to_float(video.get("duration"))

    return {
        "duration": duration,
        "width": _to_int(video.get("width")) if video else None,
        "height": _to_int(video.get("height")) if video else None,
        "vcodec": (video.get("codec_name") if video else None) or None,
        "filesize": _to_int(fmt.get("size")),
    }
