"""順次処理のダウンロードキュー。

リクエストを積み、先頭から 1 件ずつ ``DownloadWorker`` で処理する。各リクエストの
状態・進捗は ``request_updated`` で UI に通知する。完了ファイルの登録は
``download_succeeded(request, payload)`` を主スレッドで受けた側（MainWindow）が行う。

``worker_factory`` を差し替えることで、ネットワークなしのテスト用ワーカーを注入できる。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from core.downloader import DownloadWorker

# 状態
QUEUED = "queued"
DOWNLOADING = "downloading"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

_FINISHED_STATES = {DONE, FAILED, CANCELLED}


@dataclass
class DownloadRequest:
    url: str
    dest_dir: str            # 保存先（絶対パス）
    quality: str
    codec: str
    write_subtitles: bool
    save_format: str
    id: int = 0
    title: str = ""          # 取得後にファイル名が入る
    status: str = QUEUED
    progress: float = 0.0
    message: str = ""
    overwrite: bool = False          # 既存ファイルを上書きする（--force-overwrites）
    output_stem: str | None = None   # 出力名（拡張子なし）を固定。再DL時に同名へ上書き
    import_chapters: bool = False    # 完了後 YouTube チャプターをマーカーに取り込む

    def is_finished(self) -> bool:
        return self.status in _FINISHED_STATES


class DownloadQueue(QObject):
    request_added = Signal(object)              # DownloadRequest
    request_updated = Signal(object)            # DownloadRequest
    download_succeeded = Signal(object, dict)   # (DownloadRequest, payload)
    queue_idle = Signal()                       # 実行中が無くなった

    def __init__(self, worker_factory=DownloadWorker, parent=None):
        super().__init__(parent)
        self._factory = worker_factory
        self._requests: list[DownloadRequest] = []
        self._current: DownloadRequest | None = None
        self._worker = None
        self._next_id = 1

    # ------------------------------------------------------------------
    # 参照
    # ------------------------------------------------------------------

    def requests(self) -> list[DownloadRequest]:
        return list(self._requests)

    @property
    def current(self) -> DownloadRequest | None:
        return self._current

    # ------------------------------------------------------------------
    # 追加・除去
    # ------------------------------------------------------------------

    def add(self, request: DownloadRequest) -> DownloadRequest:
        request.id = self._next_id
        self._next_id += 1
        request.status = QUEUED
        self._requests.append(request)
        self.request_added.emit(request)
        self._pump()
        return request

    def cancel(self, request_id: int) -> None:
        req = self._find(request_id)
        if req is None or req.is_finished():
            return
        if req is self._current and self._worker is not None:
            self._worker.cancel()       # 実行中 → ワーカーへ通知
        elif req.status == QUEUED:
            req.status = CANCELLED
            self.request_updated.emit(req)

    def retry(self, request_id: int) -> None:
        """失敗/キャンセルしたリクエストを再度キューに戻して処理する。

        一覧内の位置は変えず、状態を QUEUED に戻して再実行する。完了済み(DONE)は
        対象外（同じファイルの再ダウンロードを誤って始めない）。
        """
        req = self._find(request_id)
        if req is None or req.status not in (FAILED, CANCELLED):
            return
        req.status = QUEUED
        req.progress = 0.0
        req.message = ""
        self.request_updated.emit(req)
        self._pump()

    def remove(self, request_id: int) -> None:
        """完了済みリクエストを一覧から取り除く（実行中は不可）。"""
        req = self._find(request_id)
        if req is None or req is self._current:
            return
        self._requests.remove(req)

    def clear_finished(self) -> None:
        self._requests = [r for r in self._requests if not r.is_finished()]

    def has_active(self) -> bool:
        return self._current is not None or any(
            r.status == QUEUED for r in self._requests
        )

    # ------------------------------------------------------------------
    # 実行
    # ------------------------------------------------------------------

    def _find(self, request_id: int) -> DownloadRequest | None:
        return next((r for r in self._requests if r.id == request_id), None)

    def _pump(self) -> None:
        if self._current is not None:
            return
        nxt = next((r for r in self._requests if r.status == QUEUED), None)
        if nxt is None:
            self.queue_idle.emit()
            return
        self._current = nxt
        nxt.status = DOWNLOADING
        nxt.progress = 0.0
        self.request_updated.emit(nxt)

        worker = self._factory(
            url=nxt.url,
            output_dir=nxt.dest_dir,
            quality=nxt.quality,
            codec=nxt.codec,
            write_subtitles=nxt.write_subtitles,
            save_format=nxt.save_format,
            overwrite=nxt.overwrite,
            output_stem=nxt.output_stem,
        )
        self._worker = worker
        worker.progress_updated.connect(
            lambda pct, line, r=nxt: self._on_progress(r, pct, line)
        )
        worker.download_succeeded.connect(
            lambda payload, r=nxt: self._on_success(r, payload)
        )
        worker.download_finished.connect(
            lambda ok, msg, r=nxt: self._on_finished(r, ok, msg)
        )
        worker.start()

    def _on_progress(self, req: DownloadRequest, pct: float, line: str) -> None:
        req.progress = pct
        req.message = line
        self.request_updated.emit(req)

    def _on_success(self, req: DownloadRequest, payload: dict) -> None:
        if payload.get("title"):
            req.title = payload["title"]
        self.download_succeeded.emit(req, payload)

    def _on_finished(self, req: DownloadRequest, ok: bool, msg: str) -> None:
        if ok:
            req.status = DONE
            req.progress = 100.0
        elif "cancel" in msg.lower():
            req.status = CANCELLED
        else:
            req.status = FAILED
        req.message = msg
        self.request_updated.emit(req)
        self._worker = None
        self._current = None
        self._pump()

    def shutdown(self, wait_ms: int = 3000) -> None:
        """アプリ終了時: 実行中をキャンセルして待つ。"""
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(wait_ms)
