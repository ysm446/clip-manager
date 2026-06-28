# 実装方針・計画

## 1. 全体方針

- ベース（clip-downloader）の構造を壊さず **拡張** する。
  - 既存: `main.py` / `core/settings.py` / `core/downloader.py` /
    `ui/main_window.py` / `ui/settings_dialog.py`
  - ダウンロード機能はそのまま生かし、その上に「管理レイヤ」を追加する。
- スレッド境界の原則を踏襲する。
  - 重い処理（ダウンロード・ライブラリ走査・サムネイル生成・ファイルI/O）は
    ワーカースレッドで行い、UI へは **Qt Signals 経由** でのみ通知する。
  - SQLite はスレッドごとに接続を分ける（接続をスレッド間で共有しない）。
- メタデータは **SQLite** を単一の真実とし、実ファイルと突き合わせる
  （DBが指すファイルが無ければ "missing" として扱う）。

## 2. 想定アーキテクチャ

```
main.py                  # QApplication 初期化・起動

core/
  settings.py            # 既存: AppSettings（QSettings）。ライブラリ保存先などを追加
  downloader.py          # 既存: DownloadWorker。完了時に DB 登録フックを呼ぶ
  database.py            # 新規: SQLite 接続・スキーマ・マイグレーション・DAO
  models.py              # 新規: Clip / Folder / Tag のデータモデル（dataclass）
  library.py             # 新規: 1ライブラリの走査・取り込み・欠落検知・ファイル操作
  libraries.py           # 新規: ライブラリ（複数ルート）の登録・切替・一覧管理
  thumbnails.py          # 新規: ffmpeg でサムネイル生成（ワーカー）
  metadata.py            # 新規: ffprobe 等で長さ・解像度・コーデック等を取得

ui/
  main_window.py         # 既存: 「ダウンロード」「ライブラリ」をタブ/ビューで統合
  settings_dialog.py     # 既存: ライブラリ登録/保存先などの設定を追加
  library_switcher.py    # 新規: アクティブライブラリの切替UI（追加/削除/選択）
  download_panel.py      # 新規: 既存のダウンロードUIをパネルへ切り出し（任意）
  library_view.py        # 新規: 一覧（サムネイル/詳細）ビュー
  filter_panel.py        # 新規: フォルダ/タグツリー＋検索ボックス
  player_widget.py       # 新規: アプリ内プレイヤー（QtMultimedia）
  clip_context_menu.py   # 新規: 右クリック操作（リネーム/移動/削除/タグ）
```

> 上記は方針であり、実装時に統合・分割してよい。重要なのは
> 「core にロジック、ui に表示」「スレッド越境は Signals」を守ること。

### UI レイアウト像（最終形）

最終的に **~1920×1080 程度の大きめウィンドウ**で、ファイル階層・サムネイル・
動画再生を一画面に出す。Library 画面は QSplitter ベースの多ペイン構成にする。

```
+----------------------------------------------------------+
| [Download] [Library]   ← タブ                            |
+-----------+--------------------------+-------------------+
| 階層ツリー | 一覧（サムネ/詳細）       | プレイヤー         |
| フォルダ   |  ┌────┐┌────┐┌────┐    | (Phase 5)         |
| タグ       |  │サムネ││サムネ││サムネ│  |  動画再生         |
| 欠落 等    |  └────┘└────┘└────┘    |  字幕             |
+-----------+--------------------------+-------------------+
```

- Phase 3: 左「階層ツリー（FilterPanel）」＋中央「一覧（LibraryView）」を
  QSplitter で並べる。デフォルトウィンドウも大きめにする。
- Phase 5: 右（または下）に動画プレイヤー枠を追加する。
- 各ペインはウィンドウサイズに応じてスケールするよう組む。

## 2.5 ライブラリ（複数ルート）の扱い

- **ライブラリ＝登録された1つのルートディレクトリ**。アプリは複数ライブラリを
  扱え、UI で **アクティブライブラリを切り替える**。
- **DB はライブラリごとに自己完結**して持つ（中央集約しない）。
  - 配置: `<root>/.clipmanager/library.db`
  - サムネイル: `<root>/.clipmanager/thumbnails/`
  - これにより、**フォルダごと移動/コピー/別PCへ持ち出してもメタデータが
    一緒に動く**（可搬性）。
- **登録ライブラリの一覧はポインタのみ**を QSettings に保持する
  （真実の源泉は各ライブラリ内の DB）。
  - 保持内容: 表示名 / ルートパス / 最終利用日時 / 並び順
- **DB 内のファイルパスはルート相対**で保存する（→ ライブラリ移動に強い）。
  実ファイルへアクセスする時にルートと結合して絶対パスへ解決する。
- **フォルダ / タグはライブラリ内スコープ**（そのライブラリの DB に属する）。
- **横断（全ライブラリ）表示** は将来対応。各 DB を順次/ATTACH して集約する
  方針とし、まずは「1ライブラリずつ」を基本動作とする。
- ダウンロードの保存先は「どのライブラリ（＋論理フォルダ）に入れるか」を選ぶ。

## 3. データモデル（SQLite スキーマ案）

> 下記スキーマは **各ライブラリの `library.db`** が持つ（ライブラリ単位）。
> 登録ライブラリ一覧は DB ではなく QSettings 側で管理する。

```sql
-- クリップ本体
CREATE TABLE clips (
  id            INTEGER PRIMARY KEY,
  rel_path      TEXT UNIQUE NOT NULL,   -- ライブラリルートからの相対パス
  title         TEXT NOT NULL,
  source_url    TEXT,                   -- ダウンロード元 URL
  duration      REAL,                   -- 秒
  filesize      INTEGER,                -- バイト
  width         INTEGER,
  height        INTEGER,
  container     TEXT,                   -- mp4 / mkv / webm / m4a / mp3
  vcodec        TEXT,
  thumbnail_path TEXT,
  subtitle_path  TEXT,
  folder_id     INTEGER REFERENCES folders(id) ON DELETE SET NULL,
  added_at      TEXT,                   -- ISO8601
  downloaded_at TEXT,
  last_played_at TEXT,
  play_count    INTEGER DEFAULT 0,
  missing       INTEGER DEFAULT 0       -- 1 = 実ファイルが見つからない
);

-- フォルダ（入れ子可）
CREATE TABLE folders (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL,
  parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE
);

-- タグ
CREATE TABLE tags (
  id    INTEGER PRIMARY KEY,
  name  TEXT UNIQUE NOT NULL,
  color TEXT                            -- 任意（表示色）
);

-- クリップ⇔タグ（多対多）
CREATE TABLE clip_tags (
  clip_id INTEGER REFERENCES clips(id) ON DELETE CASCADE,
  tag_id  INTEGER REFERENCES tags(id)  ON DELETE CASCADE,
  PRIMARY KEY (clip_id, tag_id)
);

-- スキーマ版管理
CREATE TABLE schema_version (version INTEGER);
```

- 保存場所: **各ライブラリのルート直下** `<root>/.clipmanager/library.db`。
  - 登録ライブラリ一覧（ルートパス群）は QSettings に保持する。
- `thumbnail_path` / `subtitle_path` も **ルート相対** で保存する。
- 「フォルダ」は **論理フォルダ**（DB上の分類）とし、実ディスク上の
  ディレクトリ移動は任意（Phase 4 のファイル操作で対応）。

## 4. 優先順位（フェーズ）

| Phase | 内容 | 完了の目安 |
| --- | --- | --- |
| **0** | ベース移植 | clip-downloader が `.venv` でそのまま起動・DLできる |
| **1** | DB基盤・取り込み | `database.py`/`models.py`/`libraries.py`、ライブラリ登録・切替、DL完了時に自動登録、ルート走査で取り込み |
| **2** | ライブラリ一覧UI | サムネイル/詳細ビューでクリップを閲覧できる |
| **3** | 整理・検索 | フォルダ/タグ付与、検索ボックスとツリーで絞り込める |
| **4** | ファイル操作 | リネーム・移動・削除・複製（DBと実ファイルを同期） |
| **5** | アプリ内プレイヤー | 選択クリップを内蔵プレイヤーで再生（字幕対応） |
| **6** | 仕上げ | 欠落検知、空状態、エラー処理、動作確認、ドキュメント更新 |
| **7+** | ローカルLLM分析（将来構想） | §7 参照。GUI は PySide 継続、推論は分離ワーカー |

各フェーズ完了時に `docs/plan/progress.md` と `docs/changelog.md` を更新する。
Phase 6 までを当面の目標とし、Phase 7 以降は別途計画を具体化する。

## 5. 技術選定メモ

- **アプリ内プレイヤー**: `PySide6.QtMultimedia`
  （`QMediaPlayer` + `QAudioOutput` + `QVideoWidget`）。
  - Windows の Qt Multimedia は環境により FFmpeg バックエンドを利用。
    再生不可コーデックがあり得るため、Phase 5 で対応状況を確認する。
  - 字幕は外部 `.srt` を読み込み、プレイヤー上にオーバーレイ表示する方針
    （焼き付けはしない＝ベースの字幕方針と一致）。
- **サムネイル / メタ情報**: システム導入済みの `ffmpeg` / `ffprobe` を利用。
  ダウンロード時は yt-dlp が返す info dict からも取得できる。
- **ファイル操作の安全性**: 削除は既定で「ゴミ箱へ」を検討（`send2trash` 等、
  採否は Phase 4 で決定）。リネーム/移動は実ファイルと DB を必ず一括更新する。

## 6. リスク・要確認事項

- QtMultimedia のコーデック対応（特に AV1/VP9 や MKV）→ Phase 5 で実機確認。
- ライブラリ保存先を後から変更した場合のパス整合（絶対パス保持の方針で対応）。
- 大量クリップ時の一覧描画性能 → 必要なら遅延サムネイル読み込み・仮想化を検討。
- ライブラリのルートを後から移動した場合のパス整合 → **ルート相対パス保持**で対応。

## 7. 将来構想: ローカルLLM分析（Phase 7+）

[video-content-analyzer](https://github.com/ysm446/video-content-analyzer)
のような、ローカルLLMによる動画分析機能を後続で追加する。

### 方針

- **GUI は PySide を継続する。** ML/LLM（transformers・llama-cpp-python・
  ffmpeg 等）はすべて Python であり GUI 非依存。Electron に移行しても LLM 統合に
  利点はなく、二言語化・二重ランタイム配布のコストだけが増える。
- **推論は GUI と分離して実行する**（モデルロードでの長時間フリーズ、VRAM管理、
  クラッシュの隔離のため）。既存の「重い処理はワーカー、UIへは Signals」原則の
  延長線上に置く。実装は2段階で検討:
  1. **QThread 推論ワーカー** — 軽量で既存方針と一致。小〜中規模モデル向け。
  2. **別プロセスの推論サービス** — **llama.cpp サーバ（`llama-server`）を
     subprocess として起動**し、アプリは HTTP 経由で推論を依頼する。大型モデル・
     VRAM管理・堅牢性で有利。video-content-analyzer と同じ思想。
- **分析結果はライブラリの SQLite に取り込む**（タグ・要約・チャプター・
  シーン情報など）。これにより既存の検索・整理・一覧がそのまま分析結果に使える。

### ディレクトリ構成（モデル / ランタイム）

LLM 関連の重い成果物はリポジトリに含めず、専用フォルダで管理する。

```
models/                  # ローカルLLM のモデルファイル（GGUF 等）。gitignore
  <model-name>.gguf

runtime/                 # llama.cpp サーバ等のランタイム。gitignore
  llama-cpp/
    <version>/           # 例: b4321。バージョンごとに分離して併存可能
      llama-server.exe
      *.dll …
    current -> <version> # アクティブ版（ジャンクション/設定で参照）
```

- `models/` と `runtime/` は **配布物・git に含めない**（`.gitignore` に追加）。
- どの版を使うか・モデルの所在は **設定（QSettings）** に保持する。

### llama.cpp ランタイム管理（ダウンロードUI）

`llama.cpp` 本体（`llama-server`）を **アプリ内のダウンロードUIで取得・更新・
切替** できるようにする。

- **取得元**: GitHub Releases（`ggml-org/llama.cpp`）の Windows 用ビルド。
  - リリースAPIで利用可能な **バージョン一覧**を取得して提示する。
  - バックエンド種別（**CPU / CUDA / Vulkan** 等）を選択可能にする。
- **インストール**: 選択した zip をダウンロードし `runtime/llama-cpp/<version>/`
  へ展開する（ダウンロードは既存方針どおりワーカースレッドで、進捗を Signals）。
- **バージョン管理**: 複数版を併存させ、**アクティブ版の切替**・**旧版の削除**が
  できる。アクティブ版の `llama-server` を推論サービス起動に使う。
- **担当モジュール（案）**:
  - `core/runtime_manager.py` — リリース照会・DL・展開・版の列挙/切替/削除
  - `ui/runtime_dialog.py` — バージョン一覧・DL進捗・切替の UI
- yt-dlp の自己更新と同様、**ランタイム更新もアプリ内で完結**させ、ユーザーが
  手動でバイナリ配置をしなくてよい状態を目指す。

### 想定する分析機能（参照プロジェクト由来、取捨は後で決定）

- 字幕生成（ASR、例: Qwen3-ASR）＋ word単位タイムスタンプ
- 翻訳字幕・二言語表示・ホバー辞書
- フレームサンプリング＋VLモデルによるシーン解析（概要/タグ/ジャンル）
- 自動チャプター生成、分析フレーム参照の Q&A

### 留意点

- **VRAM管理**: モデルの同時ロードを避ける／使用後アンロード／上限キャップ。
- **モデル/ランタイム配布**: GGUF 等の重みは `models/`、`llama-server` 等は
  `runtime/` に置き、いずれも配布物・git に含めない（gitignore）。llama.cpp は
  アプリ内ダウンロードUIで取得・バージョン管理する（上記参照）。
- **任意機能化**: LLM依存はオプションとし、未導入でも管理アプリとして動くこと。
- これらは Phase 6 完了後に、専用の計画として詳細化する（現時点では方針のみ）。
