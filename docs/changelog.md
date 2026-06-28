# 変更履歴

新しいものを上に記載する。日付は `YYYY-MM-DD`。

## 2026-06-28（階層ツリーからファイル削除）

- `ui/filter_panel.py`: ツリー上のファイルを**右クリック「Delete」または Delete キー**で
  削除（ゴミ箱へ。複数選択もまとめて、確認ダイアログ付き）。`delete_clip` で実ファイル・
  字幕・サムネイルを削除し DB からも除外→rebuild。

## 2026-06-28（階層ツリーにファイル表示＋D&D移動）

- `ui/filter_panel.py`: 階層ツリーに各フォルダ配下の**ファイル（クリップ）**を表示。
  `_FolderTree`（QTreeWidget サブクラス）で**クリップを別フォルダへドラッグ&ドロップ
  移動**（`move_clip` で実ファイル＋DB を更新→rebuild）。同一フォルダへのドロップは
  no-op。ファイルのダブルクリック/右クリック「Play」で再生（`clip_activated`）。
- `ui/main_window.py`: `clip_activated` をアプリ内プレイヤーに配線。
- テスト（ツリーのファイル表示・D&D移動・同フォルダ no-op）と既存全スイート通過。

## 2026-06-28（Phase 5: アプリ内プレイヤー）

- `core/subtitles.py`: 外部 `.srt` パーサ（`parse_srt`/`cue_at`）。
- `ui/player_widget.py`: `PlayerWidget`（QtMultimedia）。再生/一時停止・シーク・
  音量・速度・字幕オーバーレイ・Open externally・エラー表示。
- `ui/library_view.py`: `play_requested` を (動画, 字幕) に、`open_external_requested`。
- `ui/main_window.py`: Library タブを **[ツリー｜一覧｜プレイヤー]** の3ペインに。
- QtMultimedia 実機確認（h264+aac の mp4 ロード成功）。
- 旧レジストリの実ライブラリ "Youtube" を `data/` へ移行。
- Phase 5/既存テスト全通過。

## 2026-06-28（Phase 4.5: DLキュー＋実フォルダ階層へ再設計）

- 階層を**実フォルダ**主軸に再設計（横断分類はタグ）。論理フォルダは UI から撤去
  （スキーマ互換のため残置）。
- `core/library.py`: `list_dirs`/`make_dir`/`rename_dir`。
- `core/database.py`: `list_clips` に `folder_path`（前方一致）フィルタ。
- `core/download_queue.py`: 順次処理 `DownloadQueue` ＋ `DownloadRequest`。
- `ui/download_dialog.py`: 「ここにダウンロード」ポップアップ。
- `ui/queue_view.py`: キュー一覧（状態/進捗/キャンセル）。
- `ui/filter_panel.py`: 実フォルダツリー＋タグ、右クリックに Download here ほか。
- `ui/main_window.py`: Download タブ → **Queue タブ**に置換。DLキュー連携。
- Phase 4.5/既存テスト全通過。

## 2026-06-28（Phase 4: ファイル操作）

- `core/library.py`: `rename_clip`/`move_clip`/`duplicate_clip`/`delete_clip` を追加。
  実ファイル・字幕サイドカー・DB を一括更新。削除は Send2Trash でゴミ箱へ（失敗時は
  永久削除フォールバック）。ライブラリ外移動・不正名・同名衝突を拒否。
- `core/database.py`: `update_title`/`update_subtitle_path` を追加。
- `ui/library_view.py`: 右クリックに Rename/Move/Duplicate/Delete、`library_modified`。
- `requirements.txt`: `Send2Trash==2.1.0` を追加。
- Phase 4/既存テスト全通過。

## 2026-06-28（設定の保存先を data/ に集約）

- `core/config.py` を追加。`configure_settings_storage()` で QSettings の保存先を
  **開発中はプロジェクト直下の `data/`**（`data/ClipManager/Clip Manager.ini`）に
  向ける。ルートパス登録（LibraryManager）・DL設定・ウィンドウ位置（AppSettings）が
  ここに集約される。
- 配布時は `CLIP_MANAGER_PORTABLE=0` で OS 標準の場所へ戻せる
  （`CLIP_MANAGER_DATA_DIR` で上書き可）。`main.py` から呼び出し。
- `.gitignore` に `data/` を追加（マシン依存のパスを含むため追跡しない）。

## 2026-06-28（Phase 3: 整理・検索 フォルダ/タグ）

- `core/database.py`: `list_clips` に `tag_id`/`missing_only` フィルタ、`rename_tag`。
- `ui/filter_panel.py`（`FilterPanel`: All/Missing/Folders/Tags ツリー、フォルダ/
  タグ CRUD、`filter_changed`）を追加。
- `ui/library_view.py`: `set_filter()` と右クリックメニュー（フォルダ移動・タグ
  トグル・再生・場所を開く）。
- `ui/main_window.py`: Library タブを QSplitter[ツリー｜一覧] に再編、デフォルト
  ウィンドウ 1280×800。最終 UI 像（~1920×1080 一画面）を plan.md に明記。
- Phase 3/既存テスト全通過。

## 2026-06-28（Phase 2: ライブラリ一覧UI・メタ補完）

- `core/metadata.py`（ffprobe）/ `core/thumbnails.py`（ffmpeg）/
  `core/enrich_worker.py`（補完用 QThread）を追加。`database.py` に
  `update_metadata()` を追加。
- `ui/library_view.py`（`LibraryView`: 詳細表/サムネイル切替・タイトル検索・
  ダブルクリック再生・欠落表示）を追加。
- `ui/main_window.py` を Download / Library のタブ構成へ再編し、Enrich/Refresh/
  再生を配線。
- `AppSettings`/`LibraryManager` を `QSettings()`（アプリスコープ）に変更して
  テスト隔離を可能に（本番のレジストリ保存は不変）。
- ffprobe/ffmpeg を実呼びする Phase 2 テストと既存テストが全通過。

## 2026-06-28（Phase 1: DB基盤・ライブラリ管理・自動登録）

- `core/models.py` / `core/database.py`（SQLite スキーマ v1・WAL・DAO）/
  `core/library.py`（ルート⇄相対パス・走査取り込み・欠落検知）/
  `core/libraries.py`（複数ライブラリの登録・切替）/ `core/scan_worker.py`
  （走査用 QThread）を追加。
- `core/downloader.py` に `download_succeeded(dict)` を追加し、DL完了時に
  メタ付きでライブラリ DB へ自動登録（主スレッドで書き込み）。
- `ui/main_window.py` に Library メニュー（Open/Create・Switch・Rescan）と
  ライブラリ状態表示を追加。アクティブライブラリがあれば保存先＝ルート。
- アプリ識別子を ClipManager / Clip Manager に変更（ウィンドウ名も更新）。
- バックエンド単体テスト・MainWindow 統合スモークテストが全通過。

## 2026-06-28（Phase 0: ベース移植）

- clip-downloader のソース一式を移植（`main.py` / `core/` / `ui/`）。
- `requirements.txt`（PySide6==6.11.1 / yt-dlp==2026.6.9）、`start.bat`、
  `.gitignore`（`models/` `runtime/` `.venv/` 等を除外）を整備。
- `.venv`（Python 3.13.11）を作成し依存をインストール。ヘッドレス起動
  スモークテストで GUI 構築・イベントループ・フォーマット生成を確認。

## 2026-06-28

- プロジェクト計画を策定。clip-downloader をベースに、ファイル管理機能
  （ライブラリ一覧 / 整理 / 検索 / ファイル操作 / アプリ内プレイヤー、
  メタデータは SQLite）を追加する方針を確定。
- `docs/plan/goal.md`・`docs/plan/plan.md`・`docs/plan/progress.md` を整備。
- `README.md` を作成。
- ライブラリ設計を確定: 複数のルートディレクトリを登録・切替でき、メタデータ
  DB は各ライブラリのルート直下（`<root>/.clipmanager/library.db`）に自己完結。
  DB内パスはルート相対、登録一覧は QSettings 管理。
- 将来構想として **ローカルLLM分析**（video-content-analyzer 相当）を追加方針に。
  GUI は **PySide を継続**し、推論は GUI と分離したワーカー/プロセスで実行、
  結果は SQLite に取り込む。Phase 7+ として plan.md §7 に記載。
- LLM 構成を具体化: モデルは `models/`、llama.cpp ランタイムは `runtime/`
  （いずれも gitignore）。**llama.cpp はアプリ内ダウンロードUIで取得・バージョン
  管理**（GitHub Releases から CPU/CUDA/Vulkan 版を選択、複数版併存・切替・削除）。
  推論サービスは `llama-server` を subprocess 起動して HTTP 連携する方針。
