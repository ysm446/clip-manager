"""アプリ設定（QSettings）の保存先を制御する。

開発中はプロジェクト直下の ``data/`` に INI ファイルとして保存する。
``AppSettings``（DL設定・ウィンドウ位置）も ``LibraryManager``（ライブラリの
ルートパス登録）も引数なし ``QSettings()`` を使うため、ここで保存先を切り替えれば
両方まとめて ``data/`` に集約できる。

**配布時**: OS 標準の場所（Windows はレジストリ、他は ~/.config 等）へ戻す。
環境変数 ``CLIP_MANAGER_PORTABLE=0`` を設定すると ``data/`` へのリダイレクトを
行わず標準の場所を使う。``CLIP_MANAGER_DATA_DIR`` で保存先を上書きもできる。
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

# このファイルの 2 つ上 = プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_DATA_DIR = PROJECT_ROOT / "data"


def configure_settings_storage() -> Path | None:
    """QSettings の保存先を開発用 ``data/`` に向ける。

    ``main.py`` で QApplication の org/app 名を設定した後、最初に QSettings を
    生成する前に呼ぶこと。実際の設定ファイルは
    ``<data_dir>/<org>/<app>.ini`` に作られる。

    戻り値: 使用した設定ディレクトリ。リダイレクトしない場合は ``None``。
    """
    if os.environ.get("CLIP_MANAGER_PORTABLE", "1") == "0":
        # 配布モード: OS 標準の保存先を使う（リダイレクトしない）。
        return None

    data_dir = Path(os.environ.get("CLIP_MANAGER_DATA_DIR", str(DEV_DATA_DIR)))
    data_dir.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(data_dir),
    )
    return data_dir
