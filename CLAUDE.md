# CLAUDE.md

このファイルは Claude Code がこのリポジトリで作業する際のガイドです。

## 作業開始時の確認

このプロジェクトで作業を始める前に、まず以下を確認する。

1. `docs/plan/goal.md`
   - プロジェクトの目的、完成形、重視する価値を把握する。

2. `docs/plan/plan.md`
   - 実装方針、優先順位、今後の予定を把握する。

3. `docs/plan/progress.md`
   - 現在の進捗、完了済み作業、未完了作業、注意点を把握する。

そのうえで、今回の依頼が現在の計画や進捗のどこに関係するかを把握してから作業する。作業内容がこれらの方針と矛盾しそうな場合は、実装前に確認する。

## 実行環境

- **仮想環境**: プロジェクト直下の `.venv`（Python 3.13）
- **起動コマンド**: `.venv\Scripts\python main.py`（または `start.bat`）
- **依存のインストール**: `.venv\Scripts\python -m pip install -r requirements.txt`
- PySide6 / yt-dlp は `requirements.txt` で管理し `.venv` にインストール済み
- ffmpeg はシステムワイドにインストール済み

## アーキテクチャ

```
main.py                  # QApplication 初期化・起動（org=ClipManager / app=Clip Manager）
core/
  settings.py            # AppSettings — QSettings ラッパー（ORG/APP 定数を保持）
  downloader.py          # DownloadWorker(QThread) + build_format_string()。
                         #   完了時 download_succeeded(dict) を emit（自動登録用）
  models.py              # Clip / Folder / Tag / LibraryInfo（dataclass）
  database.py            # LibraryDatabase — 1ライブラリの SQLite 接続・スキーマ・DAO
  library.py             # Library — ルート＋DB、相対/絶対パス変換、走査取り込み・欠落検知
  libraries.py           # LibraryManager — 複数ライブラリの登録/切替（QSettings）
  scan_worker.py         # ScanWorker(QThread) — 走査を別スレッドで実行
  metadata.py            # probe() — ffprobe で duration/解像度/コーデック取得（純関数）
  thumbnails.py          # generate_thumbnail() — ffmpeg でサムネイル生成（純関数）
  enrich_worker.py       # EnrichWorker(QThread) — メタ補完＋サムネイル生成
  download_queue.py      # DownloadQueue(順次) + DownloadRequest。worker_factory 注入可
  subtitles.py           # parse_srt()/cue_at() — 外部 .srt パーサ（純関数）
ui/
  main_window.py         # MainWindow — Library/Queue のタブ。Library は3ペイン QSplitter
  filter_panel.py        # FilterPanel — 実フォルダ/タグツリー・絞り込み・Download here
  library_view.py        # LibraryView — 詳細表/サムネイル切替・検索・付与・再生要求
  player_widget.py       # PlayerWidget — QtMultimedia 動画再生＋.srt オーバーレイ
  download_dialog.py     # DownloadDialog — 「ここにダウンロード」ポップアップ
  queue_view.py          # QueueView — ダウンロードキューの進捗一覧
  settings_dialog.py     # SettingsDialog
```

Library タブは `QSplitter[FilterPanel | LibraryView | PlayerWidget]`（3ペイン）。
~1920×1080 の一画面で階層／サムネイル／再生を出す。再生はアプリ内プレイヤー、
コーデック非対応時は「Open externally」で OS 既定プレイヤーへフォールバック。

### フォルダ階層は実フォルダ（重要な設計）

- フォルダ階層は**ライブラリルート配下の実ディレクトリ**を表す（論理フォルダでは
  ない）。ツリーは `Library.list_dirs()` で構築し、絞り込みは `rel_path` の前方一致
  （`folder_path`、サブフォルダ含む）。**FS が真実、DB は再スキャンで再構築できる索引。**
- 横断分類は**タグ**（DB `tags`）。論理フォルダ（`folders`/`folder_id`）は UI 非使用
  （スキーマは互換で残置）。
- ダウンロードはフォルダ右クリック「Download here」→ `DownloadDialog` → `DownloadQueue`
  に積む（**順次処理**）。完了ファイルはそのフォルダに保存され、`register_download`
  で自動登録される。進捗は Queue タブ（`QueueView`）。

### スレッドモデル

- 重い処理（ダウンロード・ライブラリ走査）は QThread で実行し、UI へは Qt Signals
  経由でのみ通知する。スレッドから直接 UI を触らない。
- **SQLite はスレッドごとに接続を分ける**。主スレッドは `MainWindow._db`、走査は
  `ScanWorker` が自分の接続を開く。`LibraryDatabase` は WAL モードで併存に対応。
- `DownloadWorker` / `ScanWorker` は毎回新しいインスタンスを生成する（再利用しない）。
  アプリ終了時（`closeEvent`）に `wait()` し、`_db` を close する。

### ライブラリとデータモデル

- **ライブラリ＝ルートディレクトリ**。複数登録でき、アクティブを切り替える。
- メタデータ DB は各ルート直下 `<root>/.clipmanager/library.db`（自己完結）。
  サムネイルは `<root>/.clipmanager/thumbnails/`。
- **DB 内のパスはルート相対（POSIX）**で保存し、`Library` が絶対パスへ解決する
  （ライブラリ移動・持ち出しに強い）。
- ダウンロード完了ファイルがアクティブライブラリ内なら自動登録する。外なら登録しない。

## 設定の永続化

- `QSettings()`（引数なし）を使用。`main.py` が org=`ClipManager` /
  app=`Clip Manager` を設定する。
- **保存先**: `core/config.py` の `configure_settings_storage()` が `main.py` で
  呼ばれ、**開発中はプロジェクト直下の `data/`**（`data/ClipManager/Clip Manager.ini`）
  へ保存する。`AppSettings`（DL設定・ウィンドウ位置）と `LibraryManager`
  （ライブラリのルートパス登録）の両方がここに集約される。
  - **配布時**: `CLIP_MANAGER_PORTABLE=0` で OS 標準の場所（Windows はレジストリ）に
    戻す。`CLIP_MANAGER_DATA_DIR` で保存先を上書きも可能。
  - `data/` は `.gitignore` 対象（マシン依存のパスを含むため追跡しない）。
  - テストでは `QSettings.setDefaultFormat(Ini)`＋`setPath` で一時ファイルへ隔離。
- ダウンロード既定値: 保存形式 `MP4` / 画質 `720p` / コーデック `H.264` / 字幕 `True`。
- ライブラリのレジストリ（登録一覧＋アクティブ）も QSettings に JSON で保持する。

## メタ補完・サムネイル

- 取り込み直後は duration/解像度/コーデック/サムネイルが未設定。`EnrichWorker` が
  ffprobe/ffmpeg で補完する（別スレッド・専用DB接続）。WAL のため主スレッドの
  接続は補完後の再クエリで最新を見られる。
- ffprobe/ffmpeg が無い環境では補完は no-op（アプリは動作する）。
- サムネイルは `<root>/.clipmanager/thumbnails/<clip_id>.jpg`。

## 将来構想

- ローカルLLM 分析（plan.md §7）。GUI は **PySide を継続**。モデルは `models/`、
  llama.cpp ランタイムは `runtime/`（いずれも gitignore）。詳細は `docs/plan/plan.md`。
