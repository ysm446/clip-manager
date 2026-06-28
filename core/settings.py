from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QSettings


class AppSettings:
    ORG = "ClipManager"
    APP = "Clip Manager"

    def __init__(self):
        # アプリの organizationName/applicationName（main.py で設定）を使う。
        # 引数なし QSettings はテスト時に setDefaultFormat/setPath で差し替え可能。
        self._qs = QSettings()

    # --- Download folder ---

    @property
    def output_dir(self) -> str:
        default = str(Path.home() / "Downloads")
        return self._qs.value("download/output_dir", default, type=str)

    @output_dir.setter
    def output_dir(self, path: str) -> None:
        self._qs.setValue("download/output_dir", path)

    # --- Quality / Codec ---

    @property
    def default_quality(self) -> str:
        return self._qs.value("download/default_quality", "720p", type=str)

    @default_quality.setter
    def default_quality(self, v: str) -> None:
        self._qs.setValue("download/default_quality", v)

    @property
    def default_codec(self) -> str:
        return self._qs.value("download/default_codec", "H.264", type=str)

    @default_codec.setter
    def default_codec(self, v: str) -> None:
        self._qs.setValue("download/default_codec", v)

    # --- Save format ---

    @property
    def save_format(self) -> str:
        return self._qs.value("download/save_format", "MP4", type=str)

    @save_format.setter
    def save_format(self, v: str) -> None:
        self._qs.setValue("download/save_format", v)

    # --- Subtitles ---

    @property
    def write_subtitles(self) -> bool:
        return self._qs.value("download/write_subtitles", True, type=bool)

    @write_subtitles.setter
    def write_subtitles(self, v: bool) -> None:
        self._qs.setValue("download/write_subtitles", v)

    # --- Window geometry ---

    def save_geometry(self, geometry: bytes, state: bytes) -> None:
        self._qs.setValue("ui/window_geometry", geometry)
        self._qs.setValue("ui/window_state", state)

    def load_geometry(self) -> tuple[bytes | None, bytes | None]:
        return (
            self._qs.value("ui/window_geometry"),
            self._qs.value("ui/window_state"),
        )

    # --- UI layout state ---

    @property
    def details_expanded(self) -> bool:
        return self._qs.value("ui/details_expanded", True, type=bool)

    @details_expanded.setter
    def details_expanded(self, v: bool) -> None:
        self._qs.setValue("ui/details_expanded", bool(v))

    def save_splitter(self, key: str, state: bytes) -> None:
        self._qs.setValue(f"ui/splitter/{key}", state)

    def load_splitter(self, key: str) -> bytes | None:
        return self._qs.value(f"ui/splitter/{key}")
