# 変更履歴

新しいものを上に記載する。日付は `YYYY-MM-DD`。

## 2026-06-28（ブックマーク一覧の開閉）

- `ui/player_widget.py`: ブックマーク一覧を**折りたたみ可能**に（「Bookmarks ▾/▸」）。
  折りたたむと動画を広く使える。開閉状態は QSettings に永続化。

## 2026-06-28（ブックマーク機能 / markers 基盤）

- **共通マーカー基盤**を追加（点=ブックマーク／区間=チャプターを 1 テーブルで表現）。
  将来の LLM 自動チャプターも同じ仕組みに流し込める設計。
- `core/database.py`: **スキーマ v2** に。`markers` テーブル（position_ms/end_ms/kind/
  title/source/color/thumbnail_path）＋ v1→v2 マイグレーション＋ DAO。
- `core/models.py`: `Marker`。`core/library.py`: `markers_dir`。
  `core/thumbnails.py`: `generate_thumbnail(at_seconds=...)` で指定時刻のフレーム。
- `ui/player_widget.py`: 「＋ Bookmark（B キー）」、**シークバー上のティック描画**、
  **サムネイル付きブックマーク一覧**（ダブルクリックでジャンプ・前/次・右クリックで
  リネーム/削除）。
- `ui/main_window.py`: 再生時にプレイヤーへクリップ文脈を渡し、ブックマーク追加で
  その時刻のサムネイルを `<root>/.clipmanager/markers/<id>.jpg` に生成・登録。
- スキーマ v1→v2 マイグレーションとブックマーク一連の流れをテストで検証。

## 2026-06-28（画質デフォルトを best に）

- `core/settings.py`: `default_quality` の既定値を `720p` → `best` に変更。
  ダウンロードポップアップの画質プルダウンが既定で `best` に。

## 2026-06-28（Phase 6: 仕上げ）

- `ui/filter_panel.py`: 空状態の案内（ライブラリ未選択／クリップ0件のヒント）。
- `core/scan_worker.py` / `core/enrich_worker.py`: 例外処理を追加し、失敗時も
  finished シグナルを出して UI を止めない。
- `README.md` を現行アプリ（エクスプローラ/プレイヤー/詳細・DLキュー）に全面刷新。
- 実ライブラリ "Youtube"（Violin/ 4本・非ASCIIファイル名・最大1.3GB・サブフォルダ）で
  scan/missing を通し確認。

## 2026-06-28（UI状態の永続化: 詳細開閉・ペイン分割サイズ）

- `core/settings.py`: `details_expanded` と `save_splitter`/`load_splitter` を追加。
- `ui/main_window.py`: 詳細の開閉状態と各スプリッタ（左右・プレイヤー/詳細）の
  サイズを保存し、起動時に復元。詳細の開閉はトグル時に即永続化。
- （既存の永続化: ウィンドウ位置、エクスプローラ表示モード、フォルダ開閉、設定）。
- 新規テスト（再起動で詳細開閉・分割サイズが復元）と既存全スイート通過。

## 2026-06-28（詳細の折りたたみ＋スライダーのクリックシーク）

- `ui/clip_details.py`: 詳細パネルを**折りたたみ可能**に（ヘッダーの ▾/▸ ボタン）。
  折りたたむとプレイヤーを広く使える。`toggled` シグナルを追加。
- `ui/main_window.py`: 詳細の開閉に合わせて右側スプリッタの高さ配分を調整
  （折りたたみで前のサイズを記憶→展開で復元）。
- `ui/player_widget.py`: シーク/音量スライダーを `_ClickSlider` に。**溝をクリックで
  その位置へジャンプ**（クリック後そのままドラッグも可）。
- 新規テスト（クリックシークの値・詳細開閉・分割サイズ変化）と既存全スイート通過。

## 2026-06-28（エクスプローラの表示モード切替: ツリー／サムネイル）

- `ui/filter_panel.py`: 表示モードを **Tree / Icons** で切り替え可能に（ツールバーの
  View 切替、選択は QSettings に永続化）。
- **Icons（サムネイル）表示**: 現在フォルダの中身を大アイコンで表示。先頭に
  「**..（上の階層）**」エントリ、サブフォルダ、ファイル（サムネイルがあれば表示）。
  ダブルクリックでフォルダ移動/再生、選択で詳細表示、右クリックでツリーと同じ操作。
- ツリー/アイコンでコンテキストメニュー（フォルダ操作・クリップ操作）を共通化。
- 新規テスト（モード切替・現在フォルダ表示・上へ移動・選択/起動・永続化）通過。

## 2026-06-28（レイアウト刷新: 左エクスプローラ／右上プレイヤー／右下詳細）

- Library タブを **[左：エクスプローラ｜右上：プレイヤー｜右下：詳細]** に再構成。
  中央のサムネイル一覧（LibraryView）は撤去し、**エクスプローラ（FilterPanel）を
  唯一のブラウザ**に。
- `ui/clip_details.py`（`ClipDetailsPanel`）: 選択中クリップの詳細（サムネイル・
  解像度・コーデック・サイズ・タグ・日付・ソースURL）を右下に表示。クリップ選択/
  再生で更新。
- `ui/filter_panel.py`: クリップ操作を集約（右クリックに Play/Open externally/
  Open file location/Tags/Rename/Duplicate/Delete）。**タグ・「Missing」選択で
  ツリーを絞り込み**（非該当ファイルと空フォルダを隠す）。`clip_selected` 追加。
- メタ補完/サムネイル生成は **Library メニュー**へ。`library_view.py` は未使用化
  （fmt ヘルパ＋将来のサムネイル一覧用に残置）。
- 既存全スイート＋更新テスト通過。
- **次の予定**: エクスプローラの表示モード切替（ツリー／サムネイル表示）。

## 2026-06-28（DL完了後の自動リスキャン＋フォルダ開閉状態の永続化）

- `ui/main_window.py`: ダウンロードキューが空になったら**自動でリスキャン**
  （`queue_idle`→静かにスキャン）。各登録時にツリーも再構築。
- `ui/filter_panel.py`: フォルダの**開閉状態を QSettings に永続化**（ライブラリごと）。
  rebuild/リスキャン/再起動をまたいで開閉状態を保持。
- テスト（開閉の保持・再起動復元・ライブラリ別分離、queue_idle→自動取り込み）と
  既存全スイート通過。

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
