# 変更履歴

新しいものを上に記載する。日付は `YYYY-MM-DD`。

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
