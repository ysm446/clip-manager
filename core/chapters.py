"""YouTube（yt-dlp）のチャプター情報を扱う純関数。

yt-dlp の info dict は ``chapters`` を
``[{"start_time": float, "end_time": float, "title": str}, ...]``（秒）で持つ。
これを ``[{"start": float, "end": float|None, "title": str}]`` に正規化する。
"""
from __future__ import annotations


def chapters_from_info(info: dict | None) -> list[dict]:
    """info dict からチャプター一覧を正規化して返す（無ければ空リスト）。"""
    if not isinstance(info, dict):
        return []
    raw = info.get("chapters") or []
    out: list[dict] = []
    for ch in raw:
        if not isinstance(ch, dict):
            continue
        start = ch.get("start_time")
        if start is None:
            continue
        end = ch.get("end_time")
        title = (ch.get("title") or "").strip()
        out.append({
            "start": float(start),
            "end": float(end) if end is not None else None,
            "title": title,
        })
    return out


def fetch_chapters(url: str) -> list[dict]:
    """URL の動画情報を取得し（ダウンロードはしない）チャプター一覧を返す。

    ネットワークアクセスを伴うため、呼び出しはワーカースレッドから行うこと。
    """
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return chapters_from_info(info)
