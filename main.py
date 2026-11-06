from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading

from PySide6.QtWidgets import QApplication

from core.database import Database
from core.settings import Settings
from ui.logo import app_icon
from ui.styles import apply_app_style
from ui.window import OrbitWindow

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    app.setOrganizationName("D6VAlex")
    app.setApplicationName("Orbit")
    app.setWindowIcon(app_icon())

    db = Database.default()
    settings = Settings()
    apply_app_style(app)

    window = OrbitWindow(db, settings)
    window._launch_splash()

    exit_code = app.exec()
    threading.Timer(2.0, os._exit, (exit_code,)).start()
    with contextlib.suppress(Exception):
        db.close()
    for handler in logging.getLogger().handlers:
        with contextlib.suppress(Exception):
            handler.flush()

    os._exit(exit_code)

if __name__ == "__main__":
    raise SystemExit(main())
