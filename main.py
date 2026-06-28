import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from core.config import configure_settings_storage
from ui.main_window import MainWindow


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Clip Manager")
    app.setOrganizationName("ClipManager")
    app.setStyle("Fusion")

    # 設定の保存先を決定（開発中は data/、配布時は OS 標準）。
    # org/app 設定後・最初の QSettings 生成前に呼ぶ。
    configure_settings_storage()

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
