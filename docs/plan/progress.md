# 進捗

> 新しい記録を各セクションの上に追記する。日付は `YYYY-MM-DD`。

## 現在地（サマリ）

- **フェーズ**: Phase 3 完了。次は Phase 4（ファイル操作：リネーム/移動/削除/複製）。
- **状態**: Library タブを [左：フォルダ/タグツリー｜中央：一覧] の QSplitter 構成に。
  フォルダ/タグの作成・改名・削除、選択での絞り込み、クリップへのフォルダ/タグ付与
  （右クリック）を実装。デフォルトウィンドウを 1280×800 に拡大。
- **UI 像（恒久）**: 最終的に ~1920×1080 で 階層／サムネイル／動画再生 を一画面に
  （plan.md「UI レイアウト像」参照）。右ペインのプレイヤーは Phase 5。

## 完了済み

- 2026-06-28: **Phase 3 完了**。
  - `core/database.py`: `list_clips` に `tag_id` / `missing_only` フィルタを追加。
    `rename_tag` を追加。
  - `ui/filter_panel.py`（`FilterPanel`: All/Missing/Folders/Tags ツリー、
    フォルダ/タグの作成・改名・削除、`filter_changed(dict)` を emit）を追加。
  - `ui/library_view.py`: `set_filter()` と右クリックメニュー（フォルダ移動・
    タグのトグル・再生・場所を開く）を追加。表示クリップを id で保持。
  - `ui/main_window.py`: Library タブを QSplitter[FilterPanel | LibraryView] に再編。
    フィルタ配線、場所を開く、デフォルト 1280×800。
  - 検証: Phase 3 テスト（folder/tag/missing フィルタ、パネル→一覧連動、付与）と
    既存テスト（backend/window/phase2）が全通過。

- 2026-06-28: **Phase 2 完了**。
  - `core/metadata.py`（ffprobe で duration/解像度/コーデック/サイズ取得・純関数）、
    `core/thumbnails.py`（ffmpeg でサムネイル JPEG 生成・純関数）、
    `core/enrich_worker.py`（補完を別スレッドで実行・専用DB接続）を追加。
  - `core/database.py` に `update_metadata()` を追加。
  - `ui/library_view.py`（`LibraryView`: 詳細表/サムネイルの切替、タイトル検索、
    ダブルクリックで既定プレイヤー起動、欠落表示）を追加。
  - `ui/main_window.py` を **Download / Library のタブ構成**へ再編。Enrich/Refresh/
    再生を配線。DL登録・scan・enrich 後に一覧を refresh。
  - **テスト分離の改善**: `AppSettings`/`LibraryManager` を `QSettings()`（アプリ
    スコープ）に変更。テストは `setDefaultFormat(Ini)`+`setPath` で隔離でき、本番は
    従来どおりレジストリ。（以前はテストがレジストリを汚染していた。掃除済み）
  - 検証: Phase 2 テスト（probe/thumbnail/整形/scan→enrich→view）と既存の
    backend・window テストが全通過。レジストリ汚染なしを確認。
  - 補足: 再生は現状 `QDesktopServices` で外部プレイヤー起動。アプリ内プレイヤーは
    Phase 5。

- 2026-06-28: **Phase 1 完了**。
  - `core/models.py`（Clip/Folder/Tag/LibraryInfo）、`core/database.py`
    （`LibraryDatabase`: スキーマ v1・WAL・clips/folders/tags の DAO）、
    `core/library.py`（`Library`: ルート⇄相対パス変換・`scan`取り込み・
    `register_download`・`refresh_missing`）、`core/libraries.py`
    （`LibraryManager`: 複数ルートの登録/切替を QSettings 管理、テスト用に
    QSettings 注入可）、`core/scan_worker.py`（走査用 QThread、専用DB接続）を追加。
  - `core/downloader.py` に `download_succeeded(dict)` シグナルを追加し、yt-dlp の
    info dict から最終ファイルパス＋メタを抽出。主スレッドで DB へ自動登録。
  - `ui/main_window.py` に Library メニュー（Open/Create・Switch・Rescan）と
    ライブラリ状態表示を追加。アクティブライブラリがあれば保存先＝ルート。
  - 識別子変更: `AppSettings.ORG/APP` と `main.py` を ClipManager / Clip Manager に。
  - 検証: バックエンド test（schema/scan冪等/相対パス/register/folder/tag/検索/
    missing/Manager）と MainWindow 統合 test（自動登録・ライブラリ外拒否・
    クリーン終了）が全通過。全モジュール py_compile OK。
  - 補足: 取り込みは基本メタのみ（duration/解像度/コーデックは None）。ffprobe
    による補完は後続フェーズ（メタ拡充）で対応予定。

- 2026-06-28: **Phase 0 完了**。clip-downloader のソースを移植
  （`main.py` / `core/{__init__,settings,downloader}.py` /
  `ui/{__init__,main_window,settings_dialog}.py`）。`requirements.txt`
  （PySide6==6.11.1 / yt-dlp==2026.6.9）・`start.bat`・`.gitignore`
  （`models/` `runtime/` `.venv/` 等を除外）を整備。`.venv` を作成し依存を
  インストール、ヘッドレス起動スモークテストで動作確認。
  - コードはベースから無改変（アプリ名は "Clip Downloader" のまま）。
    "Clip Manager" への識別子変更（ORG/APP=ClipManager 等）は Phase 1 で実施予定。
  - 実ネットワークDLは未実施（副作用回避）。`DownloadWorker` はベースの実績コード。
- 2026-06-28: 計画策定。スコープ確定（ライブラリ一覧 / 整理 / 検索 /
  ファイル操作 / アプリ内プレイヤー、メタデータは SQLite）。
  `docs/plan/goal.md`・`plan.md`・`progress.md`・`docs/changelog.md`・
  `README.md` を作成。
- 2026-06-28: ライブラリ設計を確定。**複数ルートディレクトリを登録・切替**でき、
  **DB はライブラリのルート直下 `<root>/.clipmanager/library.db` に自己完結**
  （可搬性重視）。DB内パスは**ルート相対**。登録一覧は QSettings 管理。
  関連 docs を更新。

## 未完了（次にやること）

- [x] **Phase 0**: clip-downloader のソース一式を移植し、`.venv` で起動を確認。
- [x] **Phase 1**: SQLite基盤・複数ライブラリ管理・DL自動登録・ルート走査取り込み・
      識別子の ClipManager 化を実装し、テストで検証。
- [x] **Phase 2**: ライブラリ一覧UI（詳細/サムネイル）＋ ffprobe メタ補完＋
      ffmpeg サムネイル生成。Download/Library タブ構成。テスト検証済み。
- [x] **Phase 3**: フォルダ/タグツリー＋絞り込み＋付与（右クリック）。
      Library タブを QSplitter 構成に。テスト検証済み。
- [ ] **Phase 4**: ファイル操作（リネーム/移動/削除/複製）。実ファイルと DB を
      一括更新。削除は既定でゴミ箱へ（send2trash 採否を検討）。
- [ ] **Phase 5**: `ui/player_widget.py`（アプリ内プレイヤー・字幕）。
- [ ] **Phase 6**: 欠落検知・空状態・エラー処理・動作確認・docs更新。
- [ ] **Phase 7+（将来構想）**: ローカルLLM分析。GUI は PySide 継続、推論は
      分離ワーカー/プロセス、結果は SQLite に取り込む。Phase 6 完了後に詳細化。

## 注意点・申し送り

- `.venv`（Python 3.13）を使用する。起動は `.venv\Scripts\python main.py`。
- スレッド越境は必ず Qt Signals 経由。SQLite はスレッドごとに接続を分ける。
- コーデックは必須フィルタにしない（ベースの方針を維持）。
- 字幕は焼き付けず外部 `.srt` として扱う（ベースの方針を維持）。
- QtMultimedia のコーデック対応は Phase 5 で実機確認が必要（未検証）。
- GUI は **PySide を継続**する方針で確定（将来のローカルLLM分析も PySide のまま、
  推論を分離して追加する）。Electron へは移行しない。
- 設定（ルートパス登録・DL設定・ウィンドウ位置）は開発中 `data/` に保存
  （`core/config.py`）。配布時は `CLIP_MANAGER_PORTABLE=0` で OS 標準へ。`data/` は
  gitignore。
