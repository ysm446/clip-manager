# 進捗

> 新しい記録を各セクションの上に追記する。日付は `YYYY-MM-DD`。

## 現在地（サマリ）

- **フェーズ**: Phase 1 完了。次は Phase 2（ライブラリ一覧UI）。
- **状態**: SQLite 基盤・複数ライブラリ管理・DL自動登録・ルート走査取り込みを実装。
  バックエンド単体テストと MainWindow 統合スモークテストが全通過。
  アプリ識別子を ClipManager / Clip Manager へ変更（ウィンドウ名も "Clip Manager"）。

## 完了済み

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
- [ ] **Phase 2**: `ui/library_view.py`（サムネイル/詳細）。取り込み済みクリップを
      一覧表示。あわせて duration/解像度/コーデックの ffprobe 補完を検討。
- [ ] **Phase 3**: フォルダ/タグ・検索（`ui/filter_panel.py`）。
- [ ] **Phase 4**: ファイル操作（リネーム/移動/削除/複製）。
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
