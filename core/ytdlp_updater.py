"""yt-dlp のバージョン確認と更新（Qt 非依存・純関数）。

YouTube 側の仕様変更で yt-dlp は定期的に動かなくなるため、アプリ内から
``pip install -U yt-dlp`` を実行できるようにする。更新後は新しいバージョンを
使うためにアプリの再起動が必要（既に import 済みのモジュールは差し替えない）。
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import urllib.request
from importlib import metadata

PACKAGE = "yt-dlp"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PACKAGE}/json"

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def installed_version() -> str | None:
    """インストール済みの yt-dlp バージョン。未インストールなら None。"""
    importlib.invalidate_caches()
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        return None


def latest_version(timeout: float = 10.0) -> str | None:
    """PyPI 上の最新バージョン。取得できなければ None。"""
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data["info"]["version"]
    except Exception:
        return None


def _version_key(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str | None, current: str | None) -> bool:
    """``latest`` が ``current`` より新しければ True。どちらか不明なら False。"""
    if not latest or not current:
        return False
    return _version_key(latest) > _version_key(current)


def update(timeout: int = 600) -> tuple[bool, str]:
    """このインタプリタの環境で ``pip install -U yt-dlp`` を実行する。

    戻り値は ``(成功か, pip の出力)``。
    """
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
    try:
        res = subprocess.run(
            cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (res.stdout + res.stderr).decode("utf-8", errors="replace")
    return res.returncode == 0, out
