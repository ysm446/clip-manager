# Clip Manager

YouTube などから動画クリップをローカルへダウンロードし、**エクスプローラ風の画面で
管理・再生**できる Windows 向けデスクトップアプリです。

[clip-downloader](https://github.com/ysm446/clip-downloader)
（PySide6 + yt-dlp + ffmpeg）のダウンロード機能をベースに、ファイル管理・再生機能を
追加しています。

## 画面構成

```
[Library] [Queue]   ← タブ
┌──────────────┬───────────────────────────┐
│ エクスプローラ      │        動画プレイヤー          │  右上
│ (Tree / Icons)   │  再生/シーク/音量/速度/字幕     │
│  フォルダ＋ファイル  ├───────────────────────────┤
│  ＋タグ＋Missing   │   詳細（解像度/コーデック/タグ…） │  右下（折りたたみ可）
└──────────────┴───────────────────────────┘
```

## 主な機能

- **ダウンロード**
  - フォルダを右クリック →「Download here」→ ポップアップで URL/形式を指定 →
    **ダウンロードキュー**（順次処理）。完了するとそのフォルダに保存され自動登録。
  - 動画: MP4 / MKV / WebM、音声: MP3 / M4A。画質・コーデック選択。英語字幕 `.srt`。
  - 完了後は自動でリスキャン。
- **エクスプローラ（唯一のブラウザ）**
  - **実フォルダ階層**＋その中のファイルを表示。**Tree / Icons（サムネイル）**を切替。
  - ファイルを別フォルダへ **ドラッグ&ドロップ移動**、Delete キー/右クリックで削除
    （ゴミ箱へ）、リネーム・複製。
  - **タグ**で横断分類（タグ/「Missing」選択でツリーを絞り込み）。
- **アプリ内プレイヤー**（QtMultimedia）
  - 再生/一時停止・シーク（溝クリックでジャンプ）・音量・速度（0.5〜2.0×）・
    外部 `.srt` 字幕オーバーレイ。コーデック非対応時は「Open externally」。
- **ライブラリ**: 複数のルートフォルダを登録・切替。メタデータは各ルート直下の
  SQLite（`<root>/.clipmanager/library.db`）に自己完結（フォルダごと移動可）。
- **UI 状態の永続化**: ウィンドウ位置、ペイン分割、詳細の開閉、表示モード、フォルダ開閉。

## 技術スタック

| 項目 | 採用 |
| --- | --- |
| 言語 | Python 3.13 |
| GUI | PySide6 6.11 |
| ダウンロード | yt-dlp（Python API） |
| 動画処理 | ffmpeg / ffprobe（システム導入） |
| 再生 | PySide6 QtMultimedia（FFmpeg バックエンド） |
| メタデータ | SQLite（ライブラリごと） |
| ゴミ箱削除 | Send2Trash |

## 動作環境

- Windows 11、Python 3.13（プロジェクト直下の `.venv`）、ffmpeg がインストール済み。

## セットアップ / 起動

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py     # または start.bat
```

初回は メニュー **Library →「Open / Create Library...」** でフォルダを選び、ライブラリを
作成してください。

## 設定の保存先

開発中は設定（ライブラリ登録・各種設定・UI状態）をプロジェクト直下の `data/` に保存します。
配布時は環境変数 `CLIP_MANAGER_PORTABLE=0` で OS 標準の場所（Windows はレジストリ）へ
切り替わります（`core/config.py`）。

## プロジェクト構成

```
main.py
core/
  config.py        # 設定保存先の切替（dev=data/ / 配布=OS標準）
  settings.py      # AppSettings（QSettings ラッパー）
  libraries.py     # 複数ライブラリの登録・切替
  library.py       # 1ライブラリ（ルート＋DB、走査/取り込み/ファイル操作）
  database.py      # LibraryDatabase（SQLite スキーマ・DAO）
  models.py        # Clip / Folder / Tag / LibraryInfo
  downloader.py    # DownloadWorker（yt-dlp）
  download_queue.py# 順次ダウンロードキュー
  scan_worker.py / enrich_worker.py  # 走査・メタ補完（QThread）
  metadata.py / thumbnails.py / subtitles.py  # ffprobe / ffmpeg / .srt
ui/
  main_window.py   # タブ・3ペインレイアウト・配線
  filter_panel.py  # エクスプローラ（Tree/Icons）
  player_widget.py # 動画プレイヤー
  clip_details.py  # 詳細パネル（折りたたみ可）
  queue_view.py / download_dialog.py / settings_dialog.py
```

## ドキュメント

- [`docs/plan/goal.md`](docs/plan/goal.md) — 目的・完成形
- [`docs/plan/plan.md`](docs/plan/plan.md) — 設計・フェーズ・UIレイアウト像
- [`docs/plan/progress.md`](docs/plan/progress.md) — 進捗・申し送り
- [`docs/changelog.md`](docs/changelog.md) — 変更履歴

## 将来構想

ローカルLLM による動画分析（字幕生成・翻訳・シーン解析・タグ付け・Q&A）。GUI は
PySide を継続し、推論は分離。モデルは `models/`、llama.cpp は `runtime/`（gitignore）。
詳細は [`docs/plan/plan.md`](docs/plan/plan.md) の §7。

## ライセンス

未定（ベースの clip-downloader に準拠予定）。
