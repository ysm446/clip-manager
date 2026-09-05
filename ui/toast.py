"""右下に出る通知（トースト）ウィジェット。

`ToastManager` がホストウィジェット（MainWindow）の右下に `Toast` を積み上げて
表示する。トーストはクリックできる（`on_click`）ほか、× で閉じられ、一定時間で
自動的にフェードアウトする。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

TOAST_WIDTH = 340
THUMB_W, THUMB_H = 96, 54
MARGIN = 16          # ホスト端からの余白
SPACING = 8          # トースト同士の間隔
MAX_TOASTS = 3
DEFAULT_TIMEOUT_MS = 8000


class Toast(QFrame):
    """1 件の通知。クリックで `clicked`、閉じたときに `closed` を emit する。"""

    clicked = Signal()
    closed = Signal()

    def __init__(
        self,
        parent: QWidget,
        title: str,
        body: str = "",
        thumbnail: str | Path | None = None,
        error: bool = False,
        clickable: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        super().__init__(parent)
        self._clickable = clickable
        self._closing = False
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        accent = "#c0392b" if error else "#27ae60"
        self.setStyleSheet(
            f"""
            QFrame#toast {{
                background-color: #2b2b2b;
                border: 1px solid #3d3d3d;
                border-left: 3px solid {accent};
                border-radius: 6px;
            }}
            QLabel#toastTitle {{ color: #f0f0f0; font-weight: bold; }}
            QLabel#toastBody  {{ color: #b8b8b8; font-size: 11px; }}
            QPushButton#toastClose {{
                color: #9a9a9a; border: none; background: transparent;
                font-size: 14px; padding: 0px;
            }}
            QPushButton#toastClose:hover {{ color: #f0f0f0; }}
            """
        )
        self.setFixedWidth(TOAST_WIDTH)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 8, 8)
        row.setSpacing(8)

        pix = QPixmap(str(thumbnail)) if thumbnail else QPixmap()
        if not pix.isNull():
            thumb = QLabel(self)
            thumb.setPixmap(
                pix.scaled(
                    THUMB_W, THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            thumb.setFixedSize(THUMB_W, THUMB_H)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(thumb)

        text = QVBoxLayout()
        text.setSpacing(2)
        lbl_title = QLabel(title, self)
        lbl_title.setObjectName("toastTitle")
        lbl_title.setWordWrap(True)
        text.addWidget(lbl_title)
        if body:
            lbl_body = QLabel(body, self)
            lbl_body.setObjectName("toastBody")
            lbl_body.setWordWrap(True)
            text.addWidget(lbl_body)
        row.addLayout(text, 1)

        btn = QPushButton("✕", self)
        btn.setObjectName("toastClose")
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.clicked.connect(self.close_toast)
        row.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._timeout_ms = timeout_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close_toast)
        if timeout_ms > 0:
            self._timer.start(timeout_ms)

    # -- 表示/非表示 ---------------------------------------------------

    def fade_in(self) -> None:
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def close_toast(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._finish)
        self._anim.start()

    def _finish(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()

    # -- 操作 -----------------------------------------------------------

    def enterEvent(self, event) -> None:  # ホバー中は自動で消さない
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:   # ホバーを外れたら残り時間を短めに再開
        if not self._closing and self._timeout_ms > 0:
            self._timer.start(min(self._timeout_ms, 3000))
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self.close_toast()
        super().mouseReleaseEvent(event)


class ToastManager(QObject):
    """ホストの右下にトーストを積み上げて表示する。"""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._toasts: list[Toast] = []
        host.installEventFilter(self)

    def show_toast(
        self,
        title: str,
        body: str = "",
        thumbnail: str | Path | None = None,
        on_click: Callable[[], None] | None = None,
        error: bool = False,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> Toast:
        toast = Toast(
            self._host, title, body, thumbnail,
            error=error, clickable=on_click is not None, timeout_ms=timeout_ms,
        )
        if on_click is not None:
            toast.clicked.connect(on_click)
        toast.closed.connect(lambda t=toast: self._remove(t))
        self._toasts.append(toast)
        for old in self._toasts[:-MAX_TOASTS]:
            old.close_toast()   # 古いものからフェードアウト（多重呼び出しは無害）
        toast.adjustSize()
        self._relayout()
        toast.fade_in()
        return toast

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._relayout()

    def _relayout(self) -> None:
        """右下から上へ積む。"""
        y = self._host.height() - MARGIN
        for toast in reversed(self._toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self._host.width() - toast.width() - MARGIN, y)
            toast.raise_()
            y -= SPACING

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._host and event.type() in (
            QEvent.Type.Resize, QEvent.Type.Show,
        ):
            self._relayout()
        return super().eventFilter(obj, event)
