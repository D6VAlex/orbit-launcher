from __future__ import annotations

import gzip
import json
import logging
import os
from pathlib import Path

from parsers.base import GameEntry, GameParser, guess_main_executable

log = logging.getLogger(__name__)

class ItchIoParser(GameParser):

    source = "itch"

    def __init__(self) -> None:
        super().__init__()
        if os.name != "nt" or not os.environ.get("APPDATA"):
            self._apps_root: Path | None = None
        else:
            self._apps_root = Path(os.environ["APPDATA"]) / "itch" / "apps"

    def is_available(self) -> bool:
        if self._apps_root is None or not self._apps_root.is_dir():
            return False
        return next(self._game_dirs(), None) is not None

    def _game_dirs(self):
        if self._apps_root is None:
            return
        try:
            children = sorted(self._apps_root.iterdir())
        except OSError:
            return
        for child in children:
            if child.is_dir() and not child.name.startswith((".", "_")):
                yield child

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        for gdir in self._game_dirs():
            title, cover = self._receipt(gdir)
            exe = guess_main_executable(gdir)
            if exe is None or not exe.exists():
                self.errors.append(
                    f"itch: '{gdir.name}' skipped - no executable found")
                continue
            out.append(GameEntry(
                source=self.source,
                platform_id=gdir.name.casefold(),
                title=title or gdir.name.replace("-", " ")
                      .replace("_", " ").strip(),
                install_path=gdir,
                executable_path=exe,
                cover_urls=[cover] if cover else [],
                extra={"registry": "itch desktop app"},
            ))
        return out

    @staticmethod
    def _receipt(gdir: Path) -> tuple[str | None, str | None]:
        receipt = gdir / ".itch" / "receipt.json.gz"
        if not receipt.is_file():
            return None, None
        try:
            with gzip.open(receipt, "rt", encoding="utf-8",
                           errors="replace") as fh:
                data = json.load(fh)
        except (OSError, ValueError, EOFError):
            log.debug("itch receipt unreadable for %s", gdir.name,
                      exc_info=True)
            return None, None
        game = data.get("game") if isinstance(data, dict) else None
        if not isinstance(game, dict):
            return None, None
        title = str(game.get("title") or "").strip() or None
        cover = str(game.get("cover_url") or "").strip() or None
        return title, cover
