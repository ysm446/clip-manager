import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from core.config import configure_settings_storage
from ui.main_window import MainWindow

ICON_PATH = Path(__file__).resolve().parent / "assets" / "app_icon.webp"
APP_ID = "ClipManager.ClipManager.App"


def _set_windows_app_id() -> None:
    """Windows のタスクバーで自前のアイコンを使わせるため AppUserModelID を設定。

    これをしないと Python から起動したアプリのタスクバーアイコンが
    python/pythonw のものになる（タイトルバーは setWindowIcon で変わる）。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def main() -> None:
    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Clip Manager")
    app.setOrganizationName("ClipManager")
    app.setStyle("Fusion")
    if ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # 設定の保存先を決定（開発中は data/、配布時は OS 標準）。
    # org/app 設定後・最初の QSettings 生成前に呼ぶ。
    configure_settings_storage()

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
