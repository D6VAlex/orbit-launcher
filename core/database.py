from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from parsers.base import GameEntry

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    platform_id     TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    install_path    TEXT,
    executable_path TEXT,
    launch_uri      TEXT,
    size_on_disk    INTEGER,
    state_flags     INTEGER,
    is_installed    INTEGER NOT NULL DEFAULT 1,
    cover_url       TEXT,
    hero_url        TEXT,
    total_playtime  INTEGER NOT NULL DEFAULT 0,
    launch_count    INTEGER NOT NULL DEFAULT 0,
    launch_args     TEXT NOT NULL DEFAULT '',
    run_admin       INTEGER NOT NULL DEFAULT 0,
    last_played     TEXT,
    is_favorite     INTEGER NOT NULL DEFAULT 0,
    extra_json      TEXT,
    added_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(source, platform_id)
);
CREATE INDEX IF NOT EXISTS idx_games_source ON games(source);
CREATE INDEX IF NOT EXISTS idx_games_title  ON games(title);

CREATE TABLE IF NOT EXISTS play_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_game ON play_sessions(game_id);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS game_tags (
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (game_id, tag_id)
);

CREATE TABLE IF NOT EXISTS hidden_games (
    source      TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    hidden_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (source, platform_id)
);
"""


def _newer_iso(current: str | None, candidate: str) -> str:
    def parse(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    a, b = parse(current), parse(candidate)
    if a is None:
        return candidate
    if b is None:
        return current or candidate
    return candidate if b > a else current


class Database:
    def __init__(self, path: str | Path) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()

    @classmethod
    def default(cls) -> "Database":
        base = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation))
        base.mkdir(parents=True, exist_ok=True)
        return cls(base / "orbit.db")

    def _migrate(self) -> None:
        try:
            cols = self._conn.execute("PRAGMA table_info(games)").fetchall()
            names = {r["name"] for r in cols}
            additions = [
                ("is_favorite", "INTEGER NOT NULL DEFAULT 0"),
                ("launch_count", "INTEGER NOT NULL DEFAULT 0"),
                ("launch_args", "TEXT NOT NULL DEFAULT ''"),
                ("run_admin", "INTEGER NOT NULL DEFAULT 0"),
            ]
            for column, decl in additions:
                if column not in names:
                    self._conn.execute(
                        f"ALTER TABLE games ADD COLUMN {column} {decl}")
                    self._conn.commit()
                    log.info("Migrated games table: added %s", column)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_games_fav ON games(is_favorite)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_started "
                "ON play_sessions(started_at)")
            self._conn.commit()
        except sqlite3.Error:
            self._conn.rollback()
            log.exception("Migration failed")

    def upsert_game(self, entry: GameEntry) -> int:
        query = """
        INSERT INTO games (source, platform_id, title, install_path, executable_path,
                           launch_uri, size_on_disk, state_flags, is_installed,
                           cover_url, hero_url, extra_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source, platform_id) DO UPDATE SET
            title=excluded.title, install_path=excluded.install_path,
            executable_path=excluded.executable_path, launch_uri=excluded.launch_uri,
            size_on_disk=excluded.size_on_disk, state_flags=excluded.state_flags,
            is_installed=excluded.is_installed, cover_url=excluded.cover_url,
            hero_url=excluded.hero_url, extra_json=excluded.extra_json
        """
        installed = 1 if (entry.state_flags is None or entry.state_flags & 4) else 0
        params = (
            entry.source, entry.platform_id, entry.title,
            str(entry.install_path) if entry.install_path else None,
            str(entry.executable_path) if entry.executable_path else None,
            entry.launch_uri, entry.size_on_disk, entry.state_flags,
            installed,
            entry.cover_urls[0] if entry.cover_urls else None,
            entry.hero_urls[0] if entry.hero_urls else None,
            json.dumps(entry.extra, default=str),
        )
        with self._lock:
            self._conn.execute(query, params)
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM games WHERE source=? AND platform_id=?",
                (entry.source, entry.platform_id),
            ).fetchone()
            return int(row["id"])

    def get_game(self, game_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM games WHERE id=?",
                                     (game_id,)).fetchone()
        return dict(row) if row else None

    def games_by_source(self, source: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM games WHERE source=?",
                                      (source,)).fetchall()
        return [dict(r) for r in rows]

    def set_favorite(self, game_id: int, favorite: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE games SET is_favorite=? WHERE id=?",
                               (1 if favorite else 0, game_id))
            self._conn.commit()

    def set_launch_options(self, game_id: int, args: str,
                           run_admin: bool) -> None:
        clean = " ".join(str(args).split())
        with self._lock:
            self._conn.execute(
                "UPDATE games SET launch_args=?, run_admin=? WHERE id=?",
                (clean, 1 if run_admin else 0, game_id))
            self._conn.commit()

    def record_launch(self, game_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE games SET launch_count = launch_count + 1 WHERE id=?",
                (game_id,))
            self._conn.commit()

    def set_game_tags(self, game_id: int, tags: list[str]) -> None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for tag in tags or []:
            name = " ".join(str(tag).split())[:40]
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            cleaned.append(name)
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM game_tags WHERE game_id=?", (game_id,))
                for name in cleaned:
                    row = self._conn.execute(
                        "SELECT id FROM tags WHERE name=? COLLATE NOCASE",
                        (name,)).fetchone()
                    tag_id = (int(row["id"]) if row else int(
                        self._conn.execute(
                            "INSERT INTO tags(name) VALUES(?)",
                            (name,)).lastrowid))
                    self._conn.execute(
                        "INSERT OR IGNORE INTO game_tags(game_id, tag_id) "
                        "VALUES(?,?)", (game_id, tag_id))
                self._conn.execute(
                    "DELETE FROM tags WHERE id NOT IN "
                    "(SELECT DISTINCT tag_id FROM game_tags)")
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                log.exception("set_game_tags failed")

    def game_tags(self, game_id: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.name AS name FROM tags t "
                "JOIN game_tags gt ON gt.tag_id=t.id "
                "WHERE gt.game_id=? ORDER BY t.name COLLATE NOCASE",
                (game_id,)).fetchall()
        return [str(r["name"]) for r in rows]

    def all_tags(self) -> list[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.name AS name, COUNT(gt.game_id) AS n FROM tags t "
                "LEFT JOIN game_tags gt ON gt.tag_id=t.id "
                "GROUP BY t.id ORDER BY t.name COLLATE NOCASE").fetchall()
        return [(str(r["name"]), int(r["n"])) for r in rows]

    def all_games(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM games ORDER BY title COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def weekly_seconds(self, days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=days)).isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(duration_seconds), 0) AS s "
                "FROM play_sessions WHERE started_at >= ?", (cutoff,)).fetchone()
        return int(row["s"] if row else 0)

    def recently_played(self, limit: int = 4) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, source, total_playtime, last_played "
                "FROM games WHERE last_played IS NOT NULL AND total_playtime > 0 "
                "ORDER BY last_played DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def favorites(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, source FROM games WHERE is_favorite=1 "
                "ORDER BY title COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def count_by_source(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, COUNT(*) AS n FROM games GROUP BY source"
            ).fetchall()
        return {r["source"]: int(r["n"]) for r in rows}

    def purge_source(self, source: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM games WHERE source=?", (source,))
            self._conn.commit()

    def purge_stale_minecraft(self) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM games WHERE source='minecraft' "
                "AND platform_id != 'official-launcher'")
            self._conn.commit()

    def mark_uninstalled(self, game_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE games SET is_installed=0 WHERE id=?", (game_id,))
            self._conn.commit()

    def delete_game(self, game_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM play_sessions WHERE game_id=?", (game_id,))
            self._conn.execute(
                "DELETE FROM game_tags WHERE game_id=?", (game_id,))
            self._conn.execute(
                "DELETE FROM tags WHERE id NOT IN "
                "(SELECT DISTINCT tag_id FROM game_tags)")
            self._conn.execute("DELETE FROM games WHERE id=?", (game_id,))
            self._conn.commit()

    def hide_game(self, source: str, platform_id: str, title: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO hidden_games (source, platform_id, title) "
                "VALUES (?,?,?)", (str(source), str(platform_id), str(title)))
            self._conn.commit()

    def is_hidden(self, source: str, platform_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM hidden_games WHERE source=? AND platform_id=?",
                (str(source), str(platform_id))).fetchone()
        return row is not None

    def hidden_keys(self) -> set[tuple[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, platform_id FROM hidden_games").fetchall()
        return {(str(r["source"]), str(r["platform_id"])) for r in rows}

    def hidden_games(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, platform_id, title, hidden_at "
                "FROM hidden_games ORDER BY hidden_at DESC").fetchall()
        return [dict(r) for r in rows]

    def hidden_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM hidden_games").fetchone()
        return int(row["n"] if row else 0)

    def unhide_all(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM hidden_games")
            self._conn.commit()
        return int(cursor.rowcount or 0)

    def unhide_game(self, source: str, platform_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM hidden_games WHERE source=? AND platform_id=?",
                (str(source), str(platform_id)))
            self._conn.commit()

    def import_steam_stats(self, stats: dict[str, tuple[int, int]]) -> int:
        if not stats:
            return 0
        updated = 0
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT id, platform_id, total_playtime, last_played "
                    "FROM games WHERE source='steam'").fetchall()
                by_pid = {r["platform_id"]: r for r in rows}
                for appid, (minutes, last_epoch) in stats.items():
                    row = by_pid.get(appid)
                    if row is None:
                        continue
                    current_total = int(row["total_playtime"] or 0)
                    new_total = max(current_total, minutes * 60)
                    current_last = row["last_played"]
                    new_last = current_last
                    if last_epoch > 0:
                        imported_iso = datetime.fromtimestamp(
                            last_epoch, tz=timezone.utc).isoformat()
                        new_last = _newer_iso(current_last, imported_iso)
                    if new_total != current_total or new_last != current_last:
                        self._conn.execute(
                            "UPDATE games SET total_playtime=?, last_played=? WHERE id=?",
                            (new_total, new_last, row["id"]))
                        updated += 1
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                updated = 0
        return updated

    def add_manual_game(self, title: str, exe_path: str, source: str = "manual") -> int:
        p = Path(exe_path)
        if p.suffix.casefold() != ".exe" or not p.is_file():
            raise ValueError("executable must be an existing .exe file")
        try:
            if p.stat().st_size <= 0:
                raise ValueError("executable file is empty")
        except OSError as exc:
            raise ValueError(f"cannot stat executable: {exc}") from exc
        entry = GameEntry(
            source=source,
            platform_id=str(p).casefold(),
            title=title,
            install_path=p.parent,
            executable_path=p,
            state_flags=4,
        )
        return self.upsert_game(entry)

    def record_session(self, game_id: int, started: datetime,
                       ended: datetime, duration_s: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO play_sessions (game_id, started_at, ended_at, duration_seconds) "
                "VALUES (?,?,?,?)",
                (game_id, started.isoformat(), ended.isoformat(), duration_s),
            )
            self._conn.execute(
                "UPDATE games SET total_playtime = total_playtime + ?, last_played = ? WHERE id=?",
                (duration_s, ended.isoformat(), game_id),
            )
            self._conn.commit()

    def touch_last_played(self, game_id: int, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        with self._lock:
            self._conn.execute("UPDATE games SET last_played=? WHERE id=?",
                               (when.isoformat(), game_id))
            self._conn.commit()

    _EXPORT_COLS = (
        "source", "platform_id", "title", "install_path", "executable_path",
        "launch_uri", "size_on_disk", "state_flags", "is_installed",
        "cover_url", "hero_url", "total_playtime", "launch_count",
        "launch_args", "run_admin", "last_played", "is_favorite",
        "extra_json", "added_at",
    )

    def export_profile(self) -> dict:
        with self._lock:
            games = [dict(r) for r in self._conn.execute(
                "SELECT * FROM games").fetchall()]
            sessions = [dict(r) for r in self._conn.execute(
                "SELECT * FROM play_sessions").fetchall()]
            links = [dict(r) for r in self._conn.execute(
                "SELECT gt.game_id AS game_id, t.name AS name "
                "FROM game_tags gt JOIN tags t ON t.id=gt.tag_id").fetchall()]
        tags_by_game: dict[int, list[str]] = {}
        for link in links:
            tags_by_game.setdefault(int(link["game_id"]), []).append(
                str(link["name"]))
        for game in games:
            game["tags"] = tags_by_game.get(int(game["id"]), [])
        return {"games": games, "sessions": sessions}

    def import_profile(self, games: list[dict], sessions: list[dict],
                       mode: str) -> dict:
        summary = {"games_added": 0, "games_kept": 0, "sessions_added": 0}
        if mode not in ("replace", "merge"):
            return summary
        with self._lock:
            try:
                if mode == "replace":
                    self._conn.execute("DELETE FROM game_tags")
                    self._conn.execute("DELETE FROM tags")
                    self._conn.execute("DELETE FROM play_sessions")
                    self._conn.execute("DELETE FROM games")
                existing = {
                    (str(r["source"]), str(r["platform_id"])): int(r["id"])
                    for r in self._conn.execute(
                        "SELECT id, source, platform_id FROM games").fetchall()}
                hidden = self.hidden_keys()
                id_map: dict[int, int] = {}
                for game in games or []:
                    if not isinstance(game, dict):
                        continue
                    source = str(game.get("source") or "")
                    platform_id = str(game.get("platform_id") or "")
                    if not source or not platform_id:
                        continue
                    key = (source, platform_id)
                    if key in hidden:
                        continue
                    local_id = existing.get(key)
                    if local_id is not None and mode == "merge":
                        summary["games_kept"] += 1
                        game_id = local_id
                        current = self.game_tags(game_id)
                        remote = [str(t) for t in (game.get("tags") or [])
                                  if isinstance(game.get("tags"), list)]
                        if set(t.casefold() for t in remote) - set(
                                t.casefold() for t in current):
                            self.set_game_tags(
                                game_id, list(dict.fromkeys(current + remote)))
                        if not str(self._conn.execute(
                                "SELECT launch_args FROM games WHERE id=?",
                                (game_id,)).fetchone()["launch_args"] or ""):
                            args = str(game.get("launch_args") or "")
                            admin = 1 if game.get("run_admin") else 0
                            if args or admin:
                                self._conn.execute(
                                    "UPDATE games SET launch_args=?, run_admin=? "
                                    "WHERE id=?", (args, admin, game_id))
                    else:
                        cols, params = [], []
                        for column in self._EXPORT_COLS:
                            if column not in game:
                                continue
                            value = game[column]
                            if column in ("size_on_disk", "state_flags"):
                                value = int(value) if value is not None else None
                            cols.append(column)
                            params.append(value)
                        if not cols:
                            continue
                        placeholders = ",".join("?" for _ in cols)
                        cursor = self._conn.execute(
                            f"INSERT INTO games ({','.join(cols)}) "
                            f"VALUES ({placeholders})", params)
                        game_id = int(cursor.lastrowid)
                        summary["games_added"] += 1
                        self.set_game_tags(
                            game_id, [str(t) for t in (game.get("tags") or [])])
                    id_map[int(game.get("id") or 0)] = game_id
                for session in sessions or []:
                    if not isinstance(session, dict):
                        continue
                    try:
                        local_game = id_map.get(int(session.get("game_id") or 0))
                        started = str(session.get("started_at") or "")
                        duration = int(session.get("duration_seconds") or 0)
                    except (TypeError, ValueError):
                        continue
                    if local_game is None or not started:
                        continue
                    if mode == "merge":
                        dup = self._conn.execute(
                            "SELECT 1 FROM play_sessions WHERE game_id=? "
                            "AND started_at=? LIMIT 1",
                            (local_game, started)).fetchone()
                        if dup:
                            continue
                    self._conn.execute(
                        "INSERT INTO play_sessions (game_id, started_at, "
                        "ended_at, duration_seconds) VALUES (?,?,?,?)",
                        (local_game, started, session.get("ended_at"), duration))
                    summary["sessions_added"] += 1
                    row = self._conn.execute(
                        "SELECT last_played FROM games WHERE id=?",
                        (local_game,)).fetchone()
                    if row is not None:
                        newer = _newer_iso(row["last_played"], started)
                        self._conn.execute(
                            "UPDATE games SET total_playtime = total_playtime + ?, "
                            "last_played=? WHERE id=?",
                            (max(0, duration), newer, local_game))
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                log.exception("import_profile failed")
                return {"games_added": 0, "games_kept": 0,
                        "sessions_added": 0}
        return summary

    def close(self) -> None:
        with self._lock:
            self._conn.close()