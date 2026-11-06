from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

PROFILE_NAME = "orbit-profile.json"
PROFILE_MARKER = "orbit_profile"
PROFILE_VERSION = 1
MAX_PROFILE_BYTES = 32_000_000

SYNCED_SETTINGS = (
    "sort_mode", "lib_filter", "tag_filter", "win_geometry",
    "weekly_goal_hours", "auto_startup", "splash_min_seconds",
    "discord_rpc_enabled",
)


def build_profile(db, settings) -> dict:
    data = db.export_profile()
    synced = {}
    for key in SYNCED_SETTINGS:
        synced[key] = settings.get(key)
    return {
        PROFILE_MARKER: PROFILE_VERSION,
        "app": "Orbit",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "settings": synced,
        "games": data["games"],
        "sessions": data["sessions"],
    }


def write_profile(directory: str | Path, profile: dict) -> Path | None:
    folder = Path(directory)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / PROFILE_NAME
        tmp = folder / (PROFILE_NAME + ".tmp")
        tmp.write_text(json.dumps(profile), encoding="utf-8")
        os.replace(tmp, target)
        return target
    except (OSError, TypeError, ValueError):
        log.exception("Cloud profile write failed")
        return None


def read_profile(directory: str | Path) -> dict | None:
    path = Path(directory) / PROFILE_NAME
    try:
        text = path.read_text(encoding="utf-8")[:MAX_PROFILE_BYTES]
        data = json.loads(text)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or PROFILE_MARKER not in data:
        return None
    if not isinstance(data.get("games"), list) \
            or not isinstance(data.get("sessions"), list):
        return None
    return data


def apply_profile(db, profile: dict, mode: str) -> dict:
    return db.import_profile(profile.get("games") or [],
                             profile.get("sessions") or [], mode)


def settings_from_profile(profile: dict) -> dict:
    raw = profile.get("settings")
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in SYNCED_SETTINGS if key in raw}


def describe_summary(summary: dict) -> str:
    added = int(summary.get("games_added") or 0)
    kept = int(summary.get("games_kept") or 0)
    sessions = int(summary.get("sessions_added") or 0)
    return f"{added} added \u00b7 {kept} merged \u00b7 {sessions} sessions"
