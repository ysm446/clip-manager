# 進捗

> 新しい記録を各セクションの上に追記する。日付は `YYYY-MM-DD`。

## 現在地（サマリ）

- **フェーズ**: Phase 0 完了。次は Phase 1（DB基盤・取り込み）。
- **状態**: clip-downloader のソース一式を移植済み。`.venv`（Python 3.13.11）で
  起動を確認（GUI構築・イベントループ正常終了・フォーマット生成ロジック動作）。

## 完了済み

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
- [ ] **Phase 1**: `core/database.py` / `core/models.py` / `core/libraries.py`
      を作成。ライブラリ（複数ルート）の登録・切替、DL完了時にDBへ自動登録、
      ルート走査による既存ファイル取り込み。アプリ識別子を ClipManager へ変更。
- [ ] **Phase 2**: `ui/library_view.py`（サムネイル/詳細）。
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
