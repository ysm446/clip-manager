"""外部 ``.srt`` 字幕の最小パーサ（Qt 非依存・純関数）。

プレイヤーは埋め込み/焼き付けをせず、ここでパースした字幕を再生位置に応じて
オーバーレイ表示する（ベースの「字幕は外部 .srt」方針と一致）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 00:00:01,000 --> 00:00:04,000  （末尾はカンマまたはピリオド両対応）
_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str


def _to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0"))


def parse_srt(path: str | Path) -> list[Cue]:
    """SRT ファイルを Cue のリストへ。読めない場合は空リスト。"""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []

    cues: list[Cue] = []
    # 空行区切りのブロック単位で処理（CRLF/LF 両対応）
    blocks = re.split(r"\r?\n\r?\n", text)
    for block in blocks:
        lines = [ln for ln in block.splitlines()]
        # タイムコード行を探す（番号行が無い場合にも対応）
        time_idx = next((i for i, ln in enumerate(lines) if _TIME.search(ln)), None)
        if time_idx is None:
            continue
        mt = _TIME.search(lines[time_idx])
        start = _to_ms(*mt.group(1, 2, 3, 4))
        end = _to_ms(*mt.group(5, 6, 7, 8))
        body = "\n".join(lines[time_idx + 1:]).strip()
        if body:
            cues.append(Cue(start, end, body))
    cues.sort(key=lambda c: c.start_ms)
    return cues


def cue_at(cues: list[Cue], pos_ms: int) -> str:
    """再生位置 (ms) に該当する字幕テキスト（無ければ空文字）。"""
    for c in cues:
        if c.start_ms <= pos_ms <= c.end_ms:
            return c.text
        if c.start_ms > pos_ms:
            break
    return ""
