from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"[^0-9A-Za-z_]")


def screenshots_root() -> Path:
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation))
    return base / "screenshots"


def game_folder(game_id: int) -> Path:
    return screenshots_root() / _SAFE_ID.sub("_", str(int(game_id)))


def capture_screen(game_id: int) -> Path | None:
    try:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            return None
        folder = game_folder(game_id)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = folder / f"{stamp}.png"
        counter = 1
        while path.exists():
            path = folder / f"{stamp}-{counter}.png"
            counter += 1
        if not pixmap.save(str(path), "PNG"):
            return None
        log.info("Screenshot saved: %s", path)
        return path
    except Exception:
        log.exception("Screenshot capture failed")
        return None


def list_screenshots(game_id: int) -> list[Path]:
    folder = game_folder(game_id)
    if not folder.is_dir():
        return []
    try:
        return sorted((p for p in folder.glob("*.png") if p.is_file()),
                      key=lambda p: p.name, reverse=True)
    except OSError:
        return []


def delete_screenshot(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def delete_game_screenshots(game_id: int) -> int:
    folder = game_folder(game_id)
    if not folder.is_dir():
        return 0
    removed = 0
    try:
        for child in sorted(folder.rglob("*"), reverse=True):
            try:
                if child.is_dir():
                    child.rmdir()
                else:
                    child.unlink()
                    removed += 1
            except OSError:
                log.warning("Could not delete %s", child)
        folder.rmdir()
    except OSError:
        log.warning("Could not remove screenshot folder %s", folder)
    return removed
