"""ライブラリで扱うエンティティのデータモデル。

DB 行との変換は ``core.database`` 側で行う（モデルは純粋なデータ保持に徹する）。
パスはすべて **ライブラリルートからの相対パス**（POSIX 形式）で保持する。
絶対パスへの解決は ``core.library.Library`` が担当する。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Clip:
    """1 本のクリップ（動画/音声ファイル）。"""

    rel_path: str                       # ライブラリルートからの相対パス（POSIX）
    title: str
    id: int | None = None
    source_url: str | None = None
    duration: float | None = None       # 秒
    filesize: int | None = None         # バイト
    width: int | None = None
    height: int | None = None
    container: str | None = None        # mp4 / mkv / webm / m4a / mp3 ...
    vcodec: str | None = None
    thumbnail_path: str | None = None   # ルート相対
    subtitle_path: str | None = None    # ルート相対
    folder_id: int | None = None
    added_at: str | None = None         # ISO8601
    downloaded_at: str | None = None    # ISO8601
    last_played_at: str | None = None   # ISO8601
    play_count: int = 0
    missing: bool = False               # True = 実ファイルが見つからない
    tags: list["Tag"] = field(default_factory=list)  # 付随情報（DB列ではない）


@dataclass
class Folder:
    """論理フォルダ（入れ子可）。"""

    name: str
    id: int | None = None
    parent_id: int | None = None


@dataclass
class Tag:
    """タグ。"""

    name: str
    id: int | None = None
    color: str | None = None


@dataclass
class Marker:
    """動画上の時間アンカー。点（ブックマーク）と区間（チャプター）を共通で表す。

    ``end_ms`` が None なら点（ブックマーク）、値があれば区間（チャプター）。
    """

    clip_id: int
    position_ms: int                    # 開始位置（ミリ秒）
    id: int | None = None
    end_ms: int | None = None           # None=点 / 値=区間
    kind: str = "bookmark"              # 'bookmark' | 'chapter'
    title: str | None = None
    source: str = "user"               # 'user' | 'llm' | 'scene'
    color: str | None = None
    thumbnail_path: str | None = None   # ルート相対（.clipmanager/markers/<id>.jpg）
    created_at: str | None = None


@dataclass
class LibraryInfo:
    """登録済みライブラリのレジストリ項目（QSettings に保持される）。"""

    root: str                           # ルートディレクトリの絶対パス
    name: str
    last_used: str | None = None        # ISO8601
