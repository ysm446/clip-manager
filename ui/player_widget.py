"""アプリ内動画プレイヤー（QtMultimedia）＋外部 .srt 字幕オーバーレイ。

字幕は埋め込み/焼き付けせず、再生位置に応じて動画上にオーバーレイ表示する。
コーデック非対応などは ``errorOccurred`` を拾ってステータスに表示する。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QLabel,
    QComboBox,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from core.subtitles import parse_srt, cue_at


def _fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class _VideoArea(QVideoWidget):
    """動画表示＋下部に字幕オーバーレイ（子 QLabel）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self._subtitle = QLabel(self)
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._subtitle.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 150);"
            "padding: 4px 8px; border-radius: 4px;"
        )
        f = QFont()
        f.setPointSize(13)
        self._subtitle.setFont(f)
        self._subtitle.hide()

    def set_subtitle(self, text: str) -> None:
        if text:
            self._subtitle.setText(text)
            self._subtitle.show()
            self._reposition()
        else:
            self._subtitle.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self) -> None:
        margin = 16
        width = max(0, self.width() - 2 * margin)
        self._subtitle.setFixedWidth(width)
        h = self._subtitle.heightForWidth(width) if width else self._subtitle.sizeHint().height()
        if h <= 0:
            h = self._subtitle.sizeHint().height()
        self._subtitle.setFixedHeight(h)
        self._subtitle.move(margin, self.height() - h - margin)


class PlayerWidget(QWidget):
    open_external_requested = Signal(str)

    _SPEEDS = ["0.5×", "0.75×", "1.0×", "1.25×", "1.5×", "2.0×"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cues = []
        self._current_media = ""
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
        self._seek = QSlider(Qt.Orientation.Horizontal)
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
        ctl.addWidget(self._play_btn)
        ctl.addWidget(self._stop_btn)

        ctl.addSpacing(12)
        ctl.addWidget(QLabel("Speed:"))
        self._speed = QComboBox()
        self._speed.addItems(self._SPEEDS)
        self._speed.setCurrentText("1.0×")
        self._speed.currentTextChanged.connect(self._on_speed_changed)
        ctl.addWidget(self._speed)

        ctl.addSpacing(12)
        ctl.addWidget(QLabel("Vol:"))
        self._volume = QSlider(Qt.Orientation.Horizontal)
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

        self._status = QLabel("")
        self._status.setStyleSheet("color: #c0392b; font-size: 11px;")
        layout.addWidget(self._status)

    def _init_player(self) -> None:
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._audio.setVolume(self._volume.value() / 100)

        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    def play(self, media_abs: str, subtitle_abs: str = "") -> None:
        self._status.clear()
        self._cues = parse_srt(subtitle_abs) if subtitle_abs else []
        self._current_media = media_abs
        self._title.setText(Path(media_abs).name)
        self._video.set_subtitle("")
        self._player.setSource(QUrl.fromLocalFile(media_abs))
        self._player.setPlaybackRate(self._current_speed())
        self._player.play()

    def stop(self) -> None:
        self._player.stop()
        self._video.set_subtitle("")

    # ------------------------------------------------------------------
    # ハンドラ
    # ------------------------------------------------------------------

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setText("Pause" if playing else "Play")

    def _on_position(self, pos: int) -> None:
        if not self._seek.isSliderDown():
            self._seek.setValue(pos)
        self._pos_label.setText(_fmt_ms(pos))
        if self._cues:
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
