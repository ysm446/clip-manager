"""ダウンロードキューの一覧UI（状態・進捗・キャンセル）。

``DownloadQueue`` のシグナルを購読して行を更新する。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QHeaderView,
    QAbstractItemView,
)

from core.download_queue import DownloadQueue, DOWNLOADING, QUEUED

_ROLE_ID = Qt.ItemDataRole.UserRole
_COLUMNS = ["Title / URL", "Destination", "Status", "Progress"]

_STATUS_LABEL = {
    "queued": "Queued",
    "downloading": "Downloading",
    "done": "Done",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


class QueueView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: DownloadQueue | None = None
        self._row_by_id: dict[int, int] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, stretch=1)

        bar = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancel selected")
        self._cancel_btn.clicked.connect(self._cancel_selected)
        self._retry_btn = QPushButton("Retry selected")
        self._retry_btn.setToolTip("失敗/キャンセルしたダウンロードを再開する")
        self._retry_btn.clicked.connect(self._retry_selected)
        self._clear_btn = QPushButton("Clear finished")
        self._clear_btn.clicked.connect(self._clear_finished)
        bar.addWidget(self._cancel_btn)
        bar.addWidget(self._retry_btn)
        bar.addWidget(self._clear_btn)
        bar.addStretch()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: gray; font-size: 11px;")
        bar.addWidget(self._status_label)
        layout.addLayout(bar)

    # ------------------------------------------------------------------
    # Queue 接続
    # ------------------------------------------------------------------

    def set_queue(self, queue: DownloadQueue) -> None:
        self._queue = queue
        queue.request_added.connect(self._on_added)
        queue.request_updated.connect(self._on_updated)
        self._rebuild()

    def _rebuild(self) -> None:
        self._table.setRowCount(0)
        self._row_by_id.clear()
        if self._queue is None:
            return
        for req in self._queue.requests():
            self._on_added(req)
        self._update_status()

    def _on_added(self, req) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._row_by_id[req.id] = row

        title_item = QTableWidgetItem()
        title_item.setData(_ROLE_ID, req.id)
        self._table.setItem(row, 0, title_item)
        self._table.setItem(row, 1, QTableWidgetItem())
        self._table.setItem(row, 2, QTableWidgetItem())
        bar = QProgressBar()
        bar.setRange(0, 100)
        self._table.setCellWidget(row, 3, bar)

        self._write_row(req)
        self._update_status()

    def _on_updated(self, req) -> None:
        if req.id not in self._row_by_id:
            self._on_added(req)
            return
        self._write_row(req)
        self._update_status()

    def _write_row(self, req) -> None:
        row = self._row_by_id.get(req.id)
        if row is None:
            return
        self._table.item(row, 0).setText(req.title or req.url)
        self._table.item(row, 1).setText(self._short_dest(req.dest_dir))
        status = _STATUS_LABEL.get(req.status, req.status)
        if req.status == DOWNLOADING and req.message:
            status = f"{status} — {req.message}"
        self._table.item(row, 2).setText(status)
        bar = self._table.cellWidget(row, 3)
        if bar is not None:
            bar.setValue(int(req.progress))

    @staticmethod
    def _short_dest(dest: str) -> str:
        p = Path(dest)
        parts = p.parts
        return str(Path(*parts[-2:])) if len(parts) >= 2 else dest

    def _update_status(self) -> None:
        if self._queue is None:
            self._status_label.setText("")
            return
        reqs = self._queue.requests()
        active = sum(1 for r in reqs if r.status in (QUEUED, DOWNLOADING))
        self._status_label.setText(f"{len(reqs)} item(s), {active} active")

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def _selected_id(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(_ROLE_ID) if item else None

    def _cancel_selected(self) -> None:
        if self._queue is None:
            return
        rid = self._selected_id()
        if rid is not None:
            self._queue.cancel(rid)

    def _retry_selected(self) -> None:
        if self._queue is None:
            return
        rid = self._selected_id()
        if rid is not None:
            self._queue.retry(rid)

    def _clear_finished(self) -> None:
        if self._queue is None:
            return
        self._queue.clear_finished()
        self._rebuild()
