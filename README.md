# Clip Manager

YouTube などから動画クリップをローカルへダウンロードし、ダウンロード済みの
クリップを **一元的に管理・視聴** できる Windows 向けデスクトップアプリです。

[clip-downloader](https://github.com/ysm446/clip-downloader)
（PySide6 + yt-dlp + ffmpeg）をベースに、**ファイル管理機能** を追加しています。

> ⚠️ 開発中です。現在の進捗は [`docs/plan/progress.md`](docs/plan/progress.md)
> を参照してください。

## 主な機能

- **ダウンロード**（ベース機能）
  - 動画: MP4 / MKV / WebM、音声のみ: MP3 / M4A
  - 画質: 480p / 720p / 1080p / best、コーデック: H.264 / VP9 / AV1
  - 英語字幕を `.srt` として保存
  - 進捗・速度・ETA 表示、キャンセル対応
- **ライブラリ管理**（追加機能）
  - **複数のルートディレクトリ**を「ライブラリ」として登録・切替
    （用途別に分けられる。DB はルート直下に持つため移動・持ち出しに強い）
  - ダウンロード済みクリップを **一覧表示**（サムネイル / 詳細）
  - **フォルダ・タグ** による整理
  - タイトル・タグ・画質・日付などでの **検索 / 絞り込み**
  - **リネーム・移動・削除・複製** などのファイル操作
  - **アプリ内プレイヤー** での再生（字幕対応）
- クリップのメタデータは **SQLite**（ライブラリごとに1つ）で管理
- **ローカルLLM による動画分析**（字幕生成・翻訳・シーン解析・タグ付け・Q&A など）
  を将来構想として予定（GUI は PySide のまま、推論は分離して追加）。
  モデルは `models/`、llama.cpp ランタイムは `runtime/` に配置し、**llama.cpp は
  アプリ内のダウンロードUIで取得・バージョン管理**できるようにする。
  詳細は [`docs/plan/plan.md`](docs/plan/plan.md) の「§7 将来構想」を参照。

## 技術スタック

| 項目 | 採用 |
| --- | --- |
| 言語 | Python 3.13 |
| GUI | PySide6 |
| ダウンロード | yt-dlp（Python API） |
| 動画処理 | ffmpeg / ffprobe（システム導入） |
| 再生 | PySide6 QtMultimedia |
| メタデータ | SQLite |

## 動作環境

- Windows 11
- Python 3.13（プロジェクト直下の `.venv` を使用）
- ffmpeg がシステムにインストール済みであること

## セットアップ

```powershell
# 仮想環境の作成（初回のみ）
py -3.13 -m venv .venv

# 依存のインストール
.venv\Scripts\python -m pip install -r requirements.txt
```

> `requirements.txt` および各ソースは Phase 0（ベース移植）で追加されます。

## 起動

```powershell
.venv\Scripts\python main.py
```

または `start.bat` をダブルクリック。

## プロジェクト構成（予定）

```
main.py                  # 起動
core/
  settings.py            # 設定（QSettings ラッパー）
  downloader.py          # ダウンロード（QThread ワーカー）
  database.py            # SQLite 接続・スキーマ・DAO
  models.py              # Clip / Folder / Tag データモデル
  library.py             # 1ライブラリの走査・取り込み・ファイル操作
  libraries.py           # ライブラリ（複数ルート）の登録・切替・一覧管理
  thumbnails.py          # サムネイル生成
  metadata.py            # メタ情報取得（ffprobe 等）
ui/
  main_window.py         # メインウィンドウ（ダウンロード/ライブラリ統合）
  settings_dialog.py     # 設定ダイアログ
  library_switcher.py    # アクティブライブラリの切替UI
  library_view.py        # 一覧ビュー
  filter_panel.py        # フォルダ/タグ＋検索
  player_widget.py       # アプリ内プレイヤー
```

各ライブラリのルート直下には、メタデータを保持する `.clipmanager/` が作られます。

```
<ライブラリのルート>/
  ├─ .clipmanager/
  │    ├─ library.db     # このライブラリのメタデータ（clips/folders/tags）
  │    └─ thumbnails/    # サムネイルキャッシュ
  └─ （動画ファイル群…）
```

詳細な設計と実装計画は [`docs/plan/plan.md`](docs/plan/plan.md) を参照。

## ドキュメント

- [`docs/plan/goal.md`](docs/plan/goal.md) — 目的・完成形・スコープ
- [`docs/plan/plan.md`](docs/plan/plan.md) — 実装方針・アーキテクチャ・フェーズ
- [`docs/plan/progress.md`](docs/plan/progress.md) — 進捗・申し送り
- [`docs/changelog.md`](docs/changelog.md) — 変更履歴

## ベースプロジェクトとの関係

本アプリは clip-downloader のダウンロード機能をそのまま内包し、その上に
管理レイヤ（ライブラリ・整理・検索・ファイル操作・プレイヤー）を追加します。
スレッドモデル（QThread ＋ Qt Signals）、コーデックを必須フィルタにしない
フォーマット選択方針、字幕を焼き付けず外部 `.srt` で保存する方針は踏襲します。

## ライセンス

未定（ベースの clip-downloader に準拠予定）。
