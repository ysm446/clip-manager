"""ファイルマネージャでパスを開くヘルパ。

Windows では ``explorer /select,<file>`` でファイルを選択した状態でフォルダを開く。
それ以外（または失敗時）は親フォルダを OS 既定のファイラで開く。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def reveal_in_file_manager(path: str | Path) -> None:
    """``path`` を含むフォルダを開く。可能ならそのファイルを選択状態にする。"""
    p = Path(path)
    if sys.platform.startswith("win") and p.exists():
        # explorer は「/select,<path>」を 1 つの引数として受け取るが、リスト渡しだと
        # パスに空白があるとき subprocess がスイッチごと引用符で括ってしまい、
        # explorer がスイッチを認識できずに既定フォルダ（ドキュメント）を開く。
        # そのためコマンドラインを自前で組み、引用符はパスだけに付ける。
        exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
        try:
            subprocess.Popen(
                f'"{exe}" /select,"{os.path.normpath(p)}"',
                creationflags=_NO_WINDOW,
            )
            return
        except OSError:
            pass
    target = p if p.is_dir() else p.parent
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
