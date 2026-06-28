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
main.py                  # QApplication 初期化・起動
core/settings.py         # AppSettings — QSettings ラッパー（設定の読み書き）
core/downloader.py       # DownloadWorker(QThread) + build_format_string()
ui/main_window.py        # MainWindow(QMainWindow)
ui/settings_dialog.py    # SettingsDialog(QDialog)
```

### スレッドモデル

- ダウンロードは `DownloadWorker(QThread)` で実行（メインスレッドをブロックしない）
- yt-dlp の Python API を使用（subprocess ではない）
- スレッド→UI への通知はすべて Qt Signals 経由（`progress_updated`, `log_message`, `download_finished`）
- キャンセルは `_cancelled` フラグ → yt-dlp が `DownloadCancelled` を raise

### フォーマット文字列

`build_format_string(quality)` が yt-dlp の `-f` 相当の文字列を、`build_format_sort(codec)`
が `format_sort` 相当のリストを生成する。
コーデックは**必須フィルタにしない**(`format_sort` で「同解像度なら優先」とする)。
これにより H.264 を選んでいても VP9/AV1 のみで配信される 1440p/2160p を取り逃さない
=「best」が常に真の最高画質になる。画質は `[height<=N]` で上限だけを絞る。

### 保存形式（save format）

`core/downloader.py` の `SAVE_FORMATS` が保存形式を定義する。
- 動画コンテナ: `MP4` / `MKV` / `WebM` → `merge_output_format` に渡す。
- 音声のみ: `MP3` / `M4A` → `format="bestaudio/best"` ＋ `FFmpegExtractAudio` で抽出。
  画質・コーデックは動画用の設定なので適用されない（UI 側で自動グレーアウト）。
`is_audio_format(save_format)` で動画/音声を判定する。

## 設定の永続化

`QSettings(org="ClipDownloader", app="Clip Downloader")` を使用。
Windows では レジストリに保存される。デフォルト値：
- 保存形式: `MP4`
- 画質: `720p`
- コーデック: `H.264`
- 字幕: `True`（英語 `.srt` を別ファイルで保存）

## 字幕の扱い

- `embedsubtitles=False` — 動画への埋め込み・焼き付けは行わない
- `タイトル.en.srt` として動画と同じフォルダに保存される
- 対象言語: 英語のみ（`subtitleslangs=["en"]`）

## 開発上の注意

- UI コンポーネントの変更後は必ず `.venv\Scripts\python main.py` で動作確認する
- Qt Signals を使わずにワーカースレッドから直接 UI を操作しないこと（スレッドセーフでない）
- `DownloadWorker` は毎回新しいインスタンスを生成する（再利用しない）
- `QThread` の `wait()` はアプリ終了時（`closeEvent`）に必ず呼ぶこと
