from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

HOTKEY_CHOICES = ("ctrl+alt+space", "ctrl+alt+g", "ctrl+alt+o", "off")

_DEFAULTS: dict = {
    "version": SCHEMA_VERSION,
    "riot_clicker_enabled": False,
    "discord_rpc_enabled": True,
    "splash_min_seconds": 1.5,
    "theme": "aurora",
    "sort_mode": "favorites",
    "lib_filter": "all",
    "tag_filter": [],
    "auto_startup": True,
    "startup_notice_shown": False,
    "win_geometry": "",
    "weekly_goal_hours": 0,
    "goal_celebrated_week": "",
    "quick_hotkey": "ctrl+alt+space",
    "sync_dir": "",
    "sync_auto": True,
    "last_sync_seen": "",
}

class Settings:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from PySide6.QtCore import QStandardPaths
            base = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation))
            base.mkdir(parents=True, exist_ok=True)
            path = base / "settings.json"
        self._path = path
        self._lock = threading.RLock()
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.is_file():
                self._data = json.loads(
                    self._path.read_text(encoding="utf-8")[:262144])
            else:
                self._data = {}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Settings file unreadable (%s) - using defaults", exc)
            self._data = {}
        merged = dict(_DEFAULTS)
        merged.update({k: v for k, v in self._data.items() if k in _DEFAULTS})
        self._data = merged
        self._migrate()
        self._save()

    def _migrate(self) -> None:
        if int(self._data.get("version") or 1) >= SCHEMA_VERSION:
            return
        self._data.pop("close_to_tray", None)
        if self._data.get("splash_min_seconds") == 5.0:
            self._data["splash_min_seconds"] = 1.5
        self._data["version"] = SCHEMA_VERSION
        log.info("Settings migrated to schema v%d", SCHEMA_VERSION)

    def _save(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError as exc:
            log.error("Settings could not be saved: %s", exc)

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, _DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    @property
    def riot_clicker_enabled(self) -> bool:
        return bool(self.get("riot_clicker_enabled", False))

    @property
    def discord_rpc_enabled(self) -> bool:
        return bool(self.get("discord_rpc_enabled", True))

    @property
    def splash_min_seconds(self) -> float:
        try:
            return max(0.0, min(15.0, float(self.get("splash_min_seconds", 1.5))))
        except (TypeError, ValueError):
            return 1.5

    @property
    def theme(self) -> str:
        return str(self.get("theme", "aurora"))

    @property
    def sort_mode(self) -> str:
        mode = str(self.get("sort_mode", "favorites"))
        return mode if mode in ("favorites", "name", "last", "playtime") \
            else "favorites"

    @property
    def lib_filter(self) -> str:
        value = str(self.get("lib_filter", "all"))
        return value if value in ("all", "favorites") else "all"

    @property
    def auto_startup(self) -> bool:
        return bool(self.get("auto_startup", True))

    @property
    def win_geometry(self) -> str:
        return str(self.get("win_geometry", ""))

    @property
    def tag_filter(self) -> list:
        value = self.get("tag_filter", [])
        return [str(t) for t in value] if isinstance(value, list) else []

    @property
    def weekly_goal_hours(self) -> int:
        try:
            return max(0, min(168, int(self.get("weekly_goal_hours", 0))))
        except (TypeError, ValueError):
            return 0

    @property
    def goal_celebrated_week(self) -> str:
        return str(self.get("goal_celebrated_week", ""))

    @property
    def quick_hotkey(self) -> str:
        value = str(self.get("quick_hotkey", "ctrl+alt+space")).strip().casefold()
        return value if value in HOTKEY_CHOICES else "ctrl+alt+space"

    @property
    def sync_dir(self) -> str:
        return str(self.get("sync_dir", ""))

    @property
    def sync_auto(self) -> bool:
        return bool(self.get("sync_auto", True))

    @property
    def last_sync_seen(self) -> str:
        return str(self.get("last_sync_seen", ""))
