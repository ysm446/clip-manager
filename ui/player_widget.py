"""アプリ内動画プレイヤー（QtMultimedia）＋外部 .srt 字幕オーバーレイ。

字幕は埋め込み/焼き付けせず、再生位置に応じて動画上にオーバーレイ表示する。
コーデック非対応などは ``errorOccurred`` を拾ってステータスに表示する。
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QSize, QSizeF, QSettings
from PySide6.QtGui import (
    QFont, QPainter, QColor, QPen, QIcon, QPixmap, QShortcut, QKeySequence,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QToolButton,
    QSlider,
    QLabel,
    QComboBox,
    QStyle,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsRectItem,
    QFrame,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from core.subtitles import parse_srt, cue_at


def _fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _fmt_pos_for_filename(ms: int) -> str:
    """再生位置をファイル名で安全な文字列にする（例: 1h02m03s, 02m03s）。

    ``:`` は Windows のファイル名で使えないため使わない。
    """
    ms = max(0, ms)
    h, rem = divmod(ms // 1000, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m:02d}m{sec:02d}s"


class _ClickSlider(QSlider):
    """溝クリックでジャンプ＋マーカー位置にティックを描画する水平スライダー。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._marker_positions: list[int] = []

    def set_marker_positions(self, positions: list[int]) -> None:
        self._marker_positions = list(positions)
        self.update()

    def _value_for_x(self, x: float) -> int:
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), int(x), self.width()
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            value = self._value_for_x(event.position().x())
            self.setValue(value)
            self.sliderMoved.emit(value)   # 即シーク（player が setPosition）
        super().mousePressEvent(event)     # 続けてドラッグできるようにする

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._marker_positions or self.maximum() <= self.minimum():
            return
        painter = QPainter(self)
        painter.setPen(QColor("#e67e22"))
        h = self.height()
        for pos in self._marker_positions:
            x = QStyle.sliderPositionFromValue(
                self.minimum(), self.maximum(), pos, self.width()
            )
            painter.drawLine(x, 2, x, h - 2)
        painter.end()


class _VideoArea(QGraphicsView):
    """QGraphicsView 上で動画と字幕を合成表示する。

    QVideoWidget に子ウィジェットを重ねるとネイティブ動画面に隠れて字幕が
    見えないため、``QGraphicsVideoItem`` ＋ テキストアイテムで同一シーンに描く。
    クリックで再生/停止トグル。
    """

    clicked = Signal()

    def __init__(self, parent=None):
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self.setMinimumSize(320, 180)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setStyleSheet("background: black; border: none;")

        self._video_item = QGraphicsVideoItem()
        self._video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._scene.addItem(self._video_item)

        self._sub_bg = QGraphicsRectItem()
        self._sub_bg.setBrush(QColor(0, 0, 0, 160))
        self._sub_bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._sub_bg.setZValue(2)
        self._sub_bg.setVisible(False)
        self._scene.addItem(self._sub_bg)

        self._sub_text = QGraphicsTextItem()
        self._sub_text.setDefaultTextColor(QColor("white"))
        f = QFont()
        f.setPointSize(14)
        self._sub_text.setFont(f)
        self._sub_text.setZValue(3)
        self._sub_text.setVisible(False)
        self._scene.addItem(self._sub_text)

        self._cur_text = ""

    def video_output(self):
        return self._video_item

    def set_subtitle(self, text: str) -> None:
        self._cur_text = text
        visible = bool(text)
        self._sub_text.setVisible(visible)
        self._sub_bg.setVisible(visible)
        if visible:
            self._layout_subtitle()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        vp = self.viewport().size()
        self._scene.setSceneRect(0, 0, vp.width(), vp.height())
        self._video_item.setPos(0, 0)
        self._video_item.setSize(QSizeF(vp.width(), vp.height()))
        self._layout_subtitle()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _layout_subtitle(self) -> None:
        if not self._cur_text:
            return
        vp = self.viewport().size()
        margin = 16
        text_w = max(100, vp.width() - 2 * margin)
        self._sub_text.setTextWidth(text_w)
        body = html.escape(self._cur_text).replace("\n", "<br>")
        self._sub_text.setHtml(f'<div align="center">{body}</div>')
        br = self._sub_text.boundingRect()
        x = (vp.width() - br.width()) / 2
        y = vp.height() - br.height() - margin
        self._sub_text.setPos(x, y)
        pad = 4
        self._sub_bg.setRect(x + pad, y + pad, br.width() - 2 * pad, br.height() - 2 * pad)


class PlayerWidget(QWidget):
    open_external_requested = Signal(str)
    bookmark_add_requested = Signal(int)            # position_ms
    bookmark_rename_requested = Signal(int, str)    # (marker_id, current_title)
    bookmark_delete_requested = Signal(int)         # marker_id
    screenshot_requested = Signal(int)              # position_ms

    _SPEEDS = ["0.5×", "0.75×", "1.0×", "1.25×", "1.5×", "2.0×"]

    _BM_KEY = "ui/bookmarks_expanded"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cues = []
        self._current_media = ""
        self._clip_id = None
        self._library = None
        self._markers = []
        self._settings = QSettings()
        self._subtitles_on = self._settings.value("ui/subtitles_on", True, type=bool)
        self._init_ui()
        self._init_player()

    # ------------------------------------------------------------------
    # 構築
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self._video = _VideoArea()
        layout.addWidget(self._video, stretch=1)

        self._title = QLabel("No clip loaded")
        self._title.setStyleSheet("color: gray; font-size: 11px;")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        # seek 行
        seek_row = QHBoxLayout()
        self._pos_label = QLabel("0:00")
        self._pos_label.setStyleSheet("font-size: 11px;")
        self._seek = _ClickSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.sliderMoved.connect(self._on_seek_moved)
        self._dur_label = QLabel("0:00")
        self._dur_label.setStyleSheet("font-size: 11px;")
        seek_row.addWidget(self._pos_label)
        seek_row.addWidget(self._seek, stretch=1)
        seek_row.addWidget(self._dur_label)
        layout.addLayout(seek_row)

        # コントロール行
        ctl = QHBoxLayout()
        self._play_btn = QPushButton("Play")
        self._play_btn.clicked.connect(self._toggle_play)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.clicked.connect(self.stop)
        self._sub_btn = QPushButton("Subtitles")
        self._sub_btn.setCheckable(True)
        self._sub_btn.setChecked(self._subtitles_on)
        self._sub_btn.setToolTip("字幕の表示/非表示（.srt があるとき）")
        self._sub_btn.toggled.connect(self._on_subtitles_toggled)
        ctl.addWidget(self._play_btn)
        ctl.addWidget(self._stop_btn)
        ctl.addWidget(self._sub_btn)

        ctl.addSpacing(12)
        ctl.addWidget(QLabel("Speed:"))
        self._speed = QComboBox()
        self._speed.addItems(self._SPEEDS)
        self._speed.setCurrentText("1.0×")
        self._speed.currentTextChanged.connect(self._on_speed_changed)
        ctl.addWidget(self._speed)

        ctl.addSpacing(12)
        ctl.addWidget(QLabel("Vol:"))
        self._volume = _ClickSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(80)
        self._volume.setFixedWidth(100)
        self._volume.valueChanged.connect(self._on_volume_changed)
        ctl.addWidget(self._volume)

        ctl.addStretch()
        self._ext_btn = QPushButton("Open externally")
        self._ext_btn.clicked.connect(
            lambda: self._current_media and self.open_external_requested.emit(self._current_media)
        )
        ctl.addWidget(self._ext_btn)
        layout.addLayout(ctl)

        # ブックマーク行
        bm_row = QHBoxLayout()
        self._bm_toggle = QToolButton()
        self._bm_toggle.setText("Bookmarks")
        self._bm_toggle.setAutoRaise(True)
        self._bm_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._bm_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._bm_toggle.setToolTip("ブックマーク一覧を開閉（動画を広く使えます）")
        self._bm_toggle.clicked.connect(self._toggle_bookmarks)
        bm_row.addWidget(self._bm_toggle)
        self._bm_add_btn = QPushButton("＋ Bookmark (B)")
        self._bm_add_btn.setToolTip("現在位置にブックマークを追加")
        self._bm_add_btn.clicked.connect(self._request_add_bookmark)
        self._bm_prev_btn = QPushButton("◀ Prev")
        self._bm_prev_btn.clicked.connect(lambda: self._jump_marker(-1))
        self._bm_next_btn = QPushButton("Next ▶")
        self._bm_next_btn.clicked.connect(lambda: self._jump_marker(1))
        bm_row.addWidget(self._bm_add_btn)
        bm_row.addWidget(self._bm_prev_btn)
        bm_row.addWidget(self._bm_next_btn)
        bm_row.addStretch()
        layout.addLayout(bm_row)

        # ブックマーク一覧（サムネイル付き）
        self._bm_list = QListWidget()
        self._bm_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._bm_list.setIconSize(QSize(120, 68))
        self._bm_list.setGridSize(QSize(140, 104))
        self._bm_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._bm_list.setMovement(QListWidget.Movement.Static)
        self._bm_list.setWordWrap(True)
        self._bm_list.setFixedHeight(120)
        self._bm_list.itemDoubleClicked.connect(self._on_bookmark_activated)
        self._bm_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bm_list.customContextMenuRequested.connect(self._on_bookmark_menu)
        layout.addWidget(self._bm_list)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #c0392b; font-size: 11px;")
        layout.addWidget(self._status)

        # B キーで現在位置にブックマーク
        self._bm_shortcut = QShortcut(QKeySequence(Qt.Key.Key_B), self)
        self._bm_shortcut.activated.connect(self._request_add_bookmark)
        # F12 で現在位置のスクリーンショットを動画と同じフォルダへ保存
        self._shot_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F12), self)
        self._shot_shortcut.activated.connect(self._request_screenshot)
        self._update_bookmark_enabled()

        # 開閉状態を復元
        self._bm_expanded = self._settings.value(self._BM_KEY, True, type=bool)
        self._apply_bookmark_visibility()

    def _init_player(self) -> None:
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video.video_output())
        self._audio.setVolume(self._volume.value() / 100)

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)
        self._video.clicked.connect(self._on_video_clicked)

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def play(self, media_abs: str, subtitle_abs: str = "") -> None:
        self._status.clear()
        self._cues = parse_srt(subtitle_abs) if subtitle_abs else []
        self._current_media = media_abs
        self._title.setText(Path(media_abs).name)
        self._video.set_subtitle("")
        self._sub_btn.setEnabled(bool(self._cues))   # 字幕があるときだけ有効
        self._player.setSource(QUrl.fromLocalFile(media_abs))
        self._player.setPlaybackRate(self._current_speed())
        self._player.play()

    def stop(self) -> None:
        self._player.stop()
        self._video.set_subtitle("")

    # ------------------------------------------------------------------
    # ブックマーク
    # ------------------------------------------------------------------

    def set_clip(self, clip_id, library) -> None:
        """再生対象クリップのコンテキスト（ブックマーク保存用）を設定。"""
        self._clip_id = clip_id
        self._library = library
        self.set_markers([])

    def set_markers(self, markers) -> None:
        self._markers = sorted(markers, key=lambda m: m.position_ms)
        self._bm_list.clear()
        for m in self._markers:
            label = _fmt_ms(m.position_ms)
            if m.title and m.title != label:
                label = f"{label}  {m.title}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, m.position_ms)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            icon = self._marker_icon(m)
            if icon is not None:
                item.setIcon(icon)
            self._bm_list.addItem(item)
        self._seek.set_marker_positions([m.position_ms for m in self._markers])
        self._update_bookmark_enabled()

    def _marker_icon(self, marker):
        if marker.thumbnail_path and self._library is not None:
            tp = self._library.to_abs(marker.thumbnail_path)
            if Path(tp).is_file():
                pix = QPixmap(str(tp))
                if not pix.isNull():
                    return QIcon(pix)
        return None

    def _update_bookmark_enabled(self) -> None:
        has_clip = self._clip_id is not None
        self._bm_add_btn.setEnabled(has_clip)
        has_marks = bool(self._markers)
        self._bm_prev_btn.setEnabled(has_marks)
        self._bm_next_btn.setEnabled(has_marks)

    def _toggle_bookmarks(self) -> None:
        self._bm_expanded = not self._bm_expanded
        self._apply_bookmark_visibility()
        self._settings.setValue(self._BM_KEY, self._bm_expanded)

    def _apply_bookmark_visibility(self) -> None:
        self._bm_list.setVisible(self._bm_expanded)
        self._bm_toggle.setArrowType(
            Qt.ArrowType.DownArrow if self._bm_expanded else Qt.ArrowType.RightArrow
        )

    def _request_add_bookmark(self) -> None:
        if self._clip_id is not None:
            self.bookmark_add_requested.emit(int(self._player.position()))

    def _request_screenshot(self) -> None:
        if self._current_media:
            self.screenshot_requested.emit(int(self._player.position()))

    def show_status(self, message: str, error: bool = False) -> None:
        """ステータス行に短いメッセージを表示する（成功は緑、失敗は赤）。"""
        color = "#c0392b" if error else "#27ae60"
        self._status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._status.setText(message)

    def _on_bookmark_activated(self, item: QListWidgetItem) -> None:
        self._player.setPosition(int(item.data(Qt.ItemDataRole.UserRole + 1)))

    def _jump_marker(self, direction: int) -> None:
        if not self._markers:
            return
        pos = self._player.position()
        if direction > 0:
            nxt = next((m for m in self._markers if m.position_ms > pos + 50), None)
        else:
            nxt = next((m for m in reversed(self._markers) if m.position_ms < pos - 50), None)
        if nxt is not None:
            self._player.setPosition(nxt.position_ms)

    def _on_bookmark_menu(self, pos) -> None:
        item = self._bm_list.itemAt(pos)
        if item is None:
            return
        mid = int(item.data(Qt.ItemDataRole.UserRole))
        marker = next((m for m in self._markers if m.id == mid), None)
        menu = QMenu(self)
        menu.addAction("Jump").triggered.connect(lambda: self._on_bookmark_activated(item))
        menu.addAction("Rename...").triggered.connect(
            lambda: self.bookmark_rename_requested.emit(mid, (marker.title or "") if marker else "")
        )
        menu.addAction("Delete").triggered.connect(
            lambda: self.bookmark_delete_requested.emit(mid)
        )
        menu.exec(self._bm_list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # ハンドラ
    # ------------------------------------------------------------------

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_video_clicked(self) -> None:
        # 動画クリックで再生/一時停止トグル（メディア未ロード時は無視）
        if self._current_media:
            self._toggle_play()

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setText("Pause" if playing else "Play")

    def _on_subtitles_toggled(self, checked: bool) -> None:
        self._subtitles_on = checked
        self._settings.setValue("ui/subtitles_on", checked)
        if not checked:
            self._video.set_subtitle("")
        else:
            self._on_position(self._player.position())   # 現在位置の字幕を即反映

    def _on_position(self, pos: int) -> None:
        if not self._seek.isSliderDown():
            self._seek.setValue(pos)
        self._pos_label.setText(_fmt_ms(pos))
        if self._subtitles_on and self._cues:
            self._video.set_subtitle(cue_at(self._cues, pos))

    def _on_duration(self, dur: int) -> None:
        self._seek.setRange(0, dur)
        self._dur_label.setText(_fmt_ms(dur))

    def _on_seek_moved(self, value: int) -> None:
        self._player.setPosition(value)

    def _on_speed_changed(self, _text: str) -> None:
        self._player.setPlaybackRate(self._current_speed())

    def _current_speed(self) -> float:
        return float(self._speed.currentText().rstrip("×"))

    def _on_volume_changed(self, value: int) -> None:
        self._audio.setVolume(value / 100)

    def _on_error(self, error, error_string: str = "") -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        msg = error_string or self._player.errorString()
        self._status.setText(
            f"再生エラー: {msg}（コーデック未対応の可能性。Open externally をお試しください）"
        )
