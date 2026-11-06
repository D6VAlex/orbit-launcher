from __future__ import annotations

import logging
import os
from pathlib import Path

from parsers.base import GameEntry, GameParser, guess_main_executable

log = logging.getLogger(__name__)

class AmazonGamesParser(GameParser):

    source = "amazon"

    def __init__(self) -> None:
        super().__init__()
        if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
            self._library: Path | None = None
        else:
            self._library = (Path(os.environ["LOCALAPPDATA"])
                             / "Amazon Games" / "Library")

    def is_available(self) -> bool:
        if self._library is None or not self._library.is_dir():
            return False
        try:
            for child in self._library.iterdir():
                if child.is_dir() and not child.name.startswith((".", "_")):
                    return True
        except OSError:
            return False
        return False

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        if self._library is None:
            return out
        try:
            children = sorted(self._library.iterdir())
        except OSError:
            return out
        for gdir in children:
            if not gdir.is_dir() or gdir.name.startswith((".", "_")):
                continue
            exe = guess_main_executable(gdir)
            if exe is None or not exe.exists():
                self.errors.append(
                    f"amazon: '{gdir.name}' skipped - no executable found")
                continue
            out.append(GameEntry(
                source=self.source,
                platform_id=gdir.name.casefold(),
                title=gdir.name.replace("_", " ").strip(),
                install_path=gdir,
                executable_path=exe,
                extra={"registry": "amazon games library"},
            ))
        return out
