from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QPlainTextEdit,
    QLabel,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTabWidget,
    QSplitter,
)
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from core.settings import AppSettings
from core.libraries import LibraryManager
from core.library import Library
from core.database import LibraryDatabase
from core.scan_worker import ScanWorker
from core.enrich_worker import EnrichWorker
from core.download_queue import DownloadQueue, DownloadRequest
from core.thumbnails import generate_thumbnail
from ui.filter_panel import FilterPanel
from ui.queue_view import QueueView
from ui.player_widget import PlayerWidget, _fmt_ms, _fmt_pos_for_filename
from ui.clip_details import ClipDetailsPanel
from ui.download_dialog import DownloadDialog
from ui.settings_panel import SettingsPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = AppSettings()
        # --- Library state ---
        self._libraries = LibraryManager()
        self._active_lib: Library | None = None
        self._db: LibraryDatabase | None = None  # main-thread connection
        self._scan_worker: ScanWorker | None = None
        self._enrich_worker: EnrichWorker | None = None
        self._playing_clip_id: int | None = None     # プレイヤーで再生中のクリップ
        # --- Download queue ---
        self._queue = DownloadQueue()
        self._queue.download_succeeded.connect(self._on_download_succeeded)
        self._queue.queue_idle.connect(self._auto_rescan)
        self._init_ui()
        self._load_active_library()
        self._restore_geometry()
        self.setWindowTitle("Clip Manager")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        # --- Library tab: [ explorer | (player / details) ] ---
        self._filter_panel = FilterPanel()       # 左：エクスプローラ（唯一のブラウザ）
        self._player = PlayerWidget()            # 右上：プレイヤー
        self._details = ClipDetailsPanel()       # 右下：選択中クリップの詳細

        self._player.open_external_requested.connect(self._open_external)
        self._player.bookmark_add_requested.connect(self._add_bookmark)
        self._player.bookmark_rename_requested.connect(self._rename_bookmark)
        self._player.bookmark_delete_requested.connect(self._delete_bookmark)
        self._player.screenshot_requested.connect(self._save_screenshot)
        self._filter_panel.clip_activated.connect(self._play_clip_id)
        self._filter_panel.clip_selected.connect(self._show_details)
        self._filter_panel.open_external_requested.connect(self._open_external)
        self._filter_panel.open_location_requested.connect(self._open_location)
        self._filter_panel.open_folder_requested.connect(self._open_folder)
        self._filter_panel.download_here_requested.connect(self._open_download_dialog)
        self._filter_panel.library_changed.connect(self._update_library_status)

        self._right_split = QSplitter(Qt.Orientation.Vertical)
        self._right_split.addWidget(self._player)
        self._right_split.addWidget(self._details)
        self._right_split.setStretchFactor(0, 3)
        self._right_split.setStretchFactor(1, 2)
        self._right_split.setSizes([520, 300])
        self._details_sizes = [520, 300]         # 展開時のサイズ（折りたたみ時に復元）
        self._details.toggled.connect(self._on_details_toggled)

        self._library_split = QSplitter(Qt.Orientation.Horizontal)
        self._library_split.addWidget(self._filter_panel)
        self._library_split.addWidget(self._right_split)
        self._library_split.setStretchFactor(0, 0)
        self._library_split.setStretchFactor(1, 1)
        self._library_split.setSizes([320, 960])
        self._tabs.addTab(self._library_split, "Library")

        # --- Queue tab: [ queue table | log ] ---
        queue_tab = QWidget()
        qlayout = QVBoxLayout(queue_tab)
        qlayout.setContentsMargins(0, 0, 0, 0)
        self._queue_view = QueueView()
        self._queue_view.set_queue(self._queue)
        qlayout.addWidget(self._queue_view, stretch=1)
        qlayout.addWidget(QLabel("Log:"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        self._log.setFixedHeight(140)
        qlayout.addWidget(self._log)
        self._tabs.addTab(queue_tab, "Queue")

        # --- Settings tab ---
        self._settings_panel = SettingsPanel(self._settings)
        self._tabs.addTab(self._settings_panel, "Settings")

        # --- Menu bar ---
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction("Settings...").triggered.connect(self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit").triggered.connect(self.close)

        library_menu = self.menuBar().addMenu("Library")
        library_menu.addAction("Open / Create Library...").triggered.connect(
            self._open_library
        )
        library_menu.addAction("Switch Library...").triggered.connect(
            self._switch_library
        )
        library_menu.addSeparator()
        library_menu.addAction("Download to library root...").triggered.connect(
            self._download_to_root
        )
        library_menu.addAction("Rescan Library").triggered.connect(self._rescan_library)
        library_menu.addAction("Generate thumbnails & metadata").triggered.connect(
            self._enrich_library
        )

        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------------
    # Download (queue)
    # ------------------------------------------------------------------

    @Slot(str)
    def _open_download_dialog(self, dest_dir: str) -> None:
        """「ここにダウンロード」: ポップアップを開き、キューに積む。"""
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library first.")
            return
        dlg = DownloadDialog(self._settings, dest_dir, self)
        if not dlg.exec():
            return
        v = dlg.values()
        req = DownloadRequest(
            url=v["url"], dest_dir=v["dest_dir"], quality=v["quality"],
            codec=v["codec"], write_subtitles=v["write_subtitles"],
            save_format=v["save_format"],
        )
        self._queue.add(req)
        self._on_log(f"[Queue] Added: {req.url}  →  {req.dest_dir}")
        self._tabs.setCurrentWidget(self._tabs.widget(1))  # Queue タブへ

    @Slot()
    def _download_to_root(self) -> None:
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library first.")
            return
        self._open_download_dialog(str(self._active_lib.root))

    @Slot(object, dict)
    def _on_download_succeeded(self, request, payload: dict) -> None:
        """完了ファイルをアクティブライブラリへ登録する（主スレッド）。"""
        if self._active_lib is None or self._db is None:
            return
        try:
            clip_id = self._active_lib.register_download(self._db, payload)
        except Exception as e:
            self._on_log(f"[Library] Registration failed: {e}")
            return
        if clip_id is None:
            self._on_log("[Library] Downloaded file is outside the library — not registered.")
        else:
            self._on_log(f"[Library] Registered clip #{clip_id}: {payload.get('title')}")
            self._filter_panel.rebuild()   # ツリーに新ファイルを反映（開閉状態は保持）
            self._update_library_status()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @Slot()
    def _open_settings(self) -> None:
        self._tabs.setCurrentWidget(self._settings_panel)

    @Slot(str)
    def _on_log(self, message: str) -> None:
        self._log.appendPlainText(message)

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    def _load_active_library(self) -> None:
        """Open the active library's DB on the main thread (if any)."""
        # ライブラリを閉じる前に再生中クリップの位置を保存する
        self._persist_resume_position()
        self._player.stop()
        if self._db is not None:
            self._db.close()
            self._db = None
        self._active_lib = self._libraries.active_library()
        if self._active_lib is not None:
            self._db = self._active_lib.open_db()
        self._playing_clip_id = None
        self._player.set_clip(None, None)
        self._filter_panel.set_library(self._active_lib, self._db)
        self._details.set_library(self._active_lib)
        self._update_library_status()

    def _update_library_status(self) -> None:
        if self._active_lib is None:
            self.statusBar().showMessage("No library — open one from the Library menu")
            return
        count = self._db.count_clips() if self._db else 0
        self.statusBar().showMessage(
            f"Library: {self._active_lib.name}  ({count} clips)  —  {self._active_lib.root}"
        )

    @Slot()
    def _open_library(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select or create a library folder",
            str(self._active_lib.root) if self._active_lib else "",
        )
        if not path:
            return
        info = self._libraries.add(path, make_active=True)
        self._on_log(f"[Library] Opened '{info.name}' at {info.root}")
        self._load_active_library()

    @Slot()
    def _switch_library(self) -> None:
        infos = self._libraries.list()
        if not infos:
            QMessageBox.information(
                self, "No libraries",
                "No libraries registered yet. Use 'Open / Create Library...' first.",
            )
            return
        labels = [f"{i.name}  ({i.root})" for i in infos]
        current = self._libraries.active_root()
        current_idx = next((n for n, i in enumerate(infos) if i.root == current), 0)
        label, ok = QInputDialog.getItem(
            self, "Switch Library", "Active library:", labels, current_idx, False
        )
        if ok and label:
            self._libraries.set_active(infos[labels.index(label)].root)
            self._load_active_library()

    @Slot()
    def _auto_rescan(self) -> None:
        """ダウンロードキューが空になったら静かにリスキャンする。"""
        if self._active_lib is None:
            return
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self._on_log("[Library] Downloads finished — rescanning...")
        self._start_scan_worker()

    @Slot()
    def _rescan_library(self) -> None:
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library before scanning.")
            return
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self._start_scan_worker()

    def _start_scan_worker(self) -> None:
        self._scan_worker = ScanWorker(str(self._active_lib.root), self._active_lib.name)
        self._scan_worker.log_message.connect(self._on_log)
        self._scan_worker.progress.connect(
            lambda n, p: self.statusBar().showMessage(f"Scanning... ({n}) {p}")
        )
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.start()

    @Slot(int, int)
    def _on_scan_finished(self, added: int, missing: int) -> None:
        self._on_log(f"[Library] Scan finished: {added} new, {missing} missing.")
        self._filter_panel.rebuild()    # 新しい実フォルダ/ファイルをツリーに反映
        self._update_library_status()

    @Slot()
    def _enrich_library(self) -> None:
        """ffprobe メタ補完＋サムネイル生成をワーカーで実行。"""
        if self._active_lib is None:
            QMessageBox.information(self, "No library", "Open a library first.")
            return
        if self._enrich_worker and self._enrich_worker.isRunning():
            return
        self._enrich_worker = EnrichWorker(str(self._active_lib.root), self._active_lib.name)
        self._enrich_worker.log_message.connect(self._on_log)
        self._enrich_worker.progress.connect(
            lambda done, total: self.statusBar().showMessage(f"Enriching... {done}/{total}")
        )
        self._enrich_worker.finished_enrich.connect(self._on_enrich_finished)
        self._enrich_worker.start()

    @Slot(int)
    def _on_enrich_finished(self, updated: int) -> None:
        self._on_log(f"[Library] Enrich finished: {updated} clip(s) updated.")
        self._filter_panel.rebuild()
        self._update_library_status()

    @Slot(bool)
    def _on_details_toggled(self, expanded: bool) -> None:
        """詳細の開閉に合わせてプレイヤー/詳細の高さ配分を変える。"""
        sizes = self._right_split.sizes()
        if expanded:
            self._right_split.setSizes(self._details_sizes)
        else:
            if sizes[1] > 60:                    # 折りたたみ前のサイズを覚えておく
                self._details_sizes = sizes
            header = self._details.sizeHint().height()
            self._right_split.setSizes([sizes[0] + sizes[1] - header, header])
        self._settings.details_expanded = expanded   # 開閉状態を永続化

    @Slot(int)
    def _show_details(self, clip_id: int) -> None:
        """選択中クリップの詳細を右下パネルに表示する。"""
        if self._db is None:
            return
        clip = self._db.get_clip(clip_id)
        if clip is None:
            self._details.clear()
            return
        self._details.show_clip(clip, self._db.tags_for_clip(clip_id))

    @Slot(int)
    def _play_clip_id(self, clip_id: int) -> None:
        """ツリーのファイルをアプリ内プレイヤーで再生し、詳細も表示する。"""
        if self._db is None or self._active_lib is None:
            return
        clip = self._db.get_clip(clip_id)
        if clip is None:
            return
        media = str(self._active_lib.to_abs(clip.rel_path))
        if clip.subtitle_path:
            subtitle = str(self._active_lib.to_abs(clip.subtitle_path))
        else:
            subtitle = self._find_sidecar_srt(Path(media))   # 隣の .srt を自動検出
        # 直前まで再生していたクリップの位置を保存してから切り替える
        self._persist_resume_position()
        self._playing_clip_id = clip_id
        self._player.set_clip(clip_id, self._active_lib)
        resume_ms = (clip.resume_position_ms or 0) if self._settings.save_resume_position else 0
        self._player.play(media, subtitle, resume_ms=resume_ms)
        self._player.set_markers(self._db.list_markers(clip_id))
        self._show_details(clip_id)

    def _persist_resume_position(self) -> None:
        """再生中クリップの現在位置を前回位置として DB に保存する。

        ほぼ最後まで観た／ほとんど再生していない場合はレジュームしても
        うれしくないので消去（先頭から）する。
        """
        if self._db is None or self._playing_clip_id is None:
            return
        if not self._settings.save_resume_position:
            return
        pos = self._player.position_ms()
        dur = self._player.duration_ms()
        if pos < 5000 or (dur > 0 and pos >= dur - 5000):
            value = None
        else:
            value = pos
        self._db.update_resume_position(self._playing_clip_id, value)

    @staticmethod
    def _find_sidecar_srt(media_path: Path) -> str:
        """動画と同じフォルダにある .srt を探す（`<stem>.srt` / `<stem>.<lang>.srt`）。

        `<stem>.en.srt`（英語）を優先、次に `<stem>.srt`、その他は名前順で最初。
        """
        stem = media_path.stem
        exact = None
        en = None
        others = []
        try:
            for f in media_path.parent.iterdir():
                if not (f.is_file() and f.suffix.lower() == ".srt"):
                    continue
                if f.name == stem + ".srt":
                    exact = f
                elif f.name.startswith(stem + "."):
                    if f.name.lower() == (stem + ".en.srt").lower():
                        en = f
                    else:
                        others.append(f)
        except OSError:
            return ""
        chosen = en or exact or (sorted(others)[0] if others else None)
        return str(chosen) if chosen else ""

    # ------------------------------------------------------------------
    # ブックマーク（markers: 点）
    # ------------------------------------------------------------------

    def _reload_markers(self) -> None:
        if self._db is not None and self._playing_clip_id is not None:
            self._player.set_markers(self._db.list_markers(self._playing_clip_id))

    @Slot(int)
    def _add_bookmark(self, position_ms: int) -> None:
        cid = self._playing_clip_id
        if self._db is None or self._active_lib is None or cid is None:
            return
        clip = self._db.get_clip(cid)
        if clip is None:
            return
        mid = self._db.add_marker(cid, position_ms, title=_fmt_ms(position_ms))
        # その時刻のフレームを .clipmanager/markers/<id>.jpg に生成
        try:
            out = self._active_lib.markers_dir / f"{mid}.jpg"
            if generate_thumbnail(
                self._active_lib.to_abs(clip.rel_path), out,
                at_seconds=position_ms / 1000.0,
            ):
                self._db.update_marker_thumbnail(mid, self._active_lib.to_rel(out))
        except Exception as e:
            self._on_log(f"[Bookmark] thumbnail failed: {e}")
        self._reload_markers()
        self._on_log(f"[Bookmark] added at {_fmt_ms(position_ms)}")

    @Slot(int)
    def _save_screenshot(self, position_ms: int) -> None:
        """現在位置のフレームを、動画と同じフォルダにフル解像度で保存する。

        ファイル名は ``<動画名>_<再生位置>.jpg``（同名が既にあれば連番を付与）。
        """
        cid = self._playing_clip_id
        if self._db is None or self._active_lib is None or cid is None:
            return
        clip = self._db.get_clip(cid)
        if clip is None:
            return
        media = self._active_lib.to_abs(clip.rel_path)
        out = self._unique_path(
            Path(media).with_name(
                f"{Path(media).stem}_{_fmt_pos_for_filename(position_ms)}.jpg"
            )
        )
        ok = generate_thumbnail(
            media, out, at_seconds=position_ms / 1000.0, width=0, quality=2,
        )
        if ok:
            self._player.show_status(f"スクリーンショットを保存: {out.name}")
            self._on_log(f"[Screenshot] saved {out}")
        else:
            self._player.show_status(
                "スクリーンショットの保存に失敗しました（ffmpeg を確認）", error=True
            )
            self._on_log("[Screenshot] failed (ffmpeg unavailable or error)")

    @staticmethod
    def _unique_path(path: Path) -> Path:
        """``path`` が既存なら ``name_1.jpg`` のように連番で衝突を避ける。"""
        if not path.exists():
            return path
        for i in range(1, 1000):
            cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
            if not cand.exists():
                return cand
        return path

    @Slot(int, str)
    def _rename_bookmark(self, marker_id: int, current: str) -> None:
        if self._db is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename bookmark", "Label:", text=current
        )
        if not ok:
            return
        self._db.update_marker_title(marker_id, name.strip())
        self._reload_markers()

    @Slot(int)
    def _delete_bookmark(self, marker_id: int) -> None:
        if self._db is None:
            return
        marker = self._db.get_marker(marker_id)
        self._db.delete_marker(marker_id)
        if marker and marker.thumbnail_path and self._active_lib is not None:
            thumb = self._active_lib.to_abs(marker.thumbnail_path)
            try:
                if thumb.is_file():
                    thumb.unlink()
            except OSError:
                pass
        self._reload_markers()

    @Slot(str)
    def _open_external(self, abs_path: str) -> None:
        """クリップを OS 既定のプレイヤーで開く（コーデック非対応時のフォールバック）。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(abs_path))

    @Slot(str)
    def _open_location(self, abs_path: str) -> None:
        """クリップを含むフォルダを開く。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(abs_path).parent)))

    @Slot(str)
    def _open_folder(self, abs_dir: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(abs_dir))

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        geom, state = self._settings.load_geometry()
        if geom:
            self.restoreGeometry(geom)
        if state:
            self.restoreState(state)
        else:
            # 最終的に ~1920x1080 を想定（plan.md の UI レイアウト像）。
            self.resize(1280, 800)
        self._restore_layout()

    def _restore_layout(self) -> None:
        """詳細の開閉・各スプリッタのサイズを復元する。"""
        # 詳細の開閉（先に適用 → スプリッタ復元で最終サイズを上書き）
        self._details.set_expanded(self._settings.details_expanded)
        for key, splitter in (
            ("library", self._library_split), ("right", self._right_split)
        ):
            saved = self._settings.load_splitter(key)
            if saved:
                splitter.restoreState(saved)

    def closeEvent(self, event) -> None:
        self._settings.save_geometry(
            bytes(self.saveGeometry()),
            bytes(self.saveState()),
        )
        self._settings.save_splitter("library", bytes(self._library_split.saveState()))
        self._settings.save_splitter("right", bytes(self._right_split.saveState()))
        self._persist_resume_position()
        self._player.stop()
        self._queue.shutdown(3000)
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.wait(3000)
        if self._enrich_worker and self._enrich_worker.isRunning():
            self._enrich_worker.cancel()
            self._enrich_worker.wait(3000)
        if self._db is not None:
            self._db.close()
            self._db = None
        super().closeEvent(event)
