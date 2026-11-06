from __future__ import annotations

import logging
import os
from pathlib import Path

from parsers.base import GameEntry, GameParser, guess_main_executable

log = logging.getLogger(__name__)

try:
    import winreg
except ImportError:
    winreg = None

_PUBLISHER_HINTS = ("cognosphere", "mihoyo", "hoyoverse")
_TITLE_HINTS = ("genshin", "honkai", "zenless", "star rail")

def _uninstall_roots():
    if winreg is None:
        return []
    return (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )

class HoyoParser(GameParser):

    source = "hoyo"

    def _uninstall_entries(self) -> list[tuple[str, dict[str, str]]]:
        out: list[tuple[str, dict[str, str]]] = []
        if os.name != "nt":
            return out
        for hive, path in _uninstall_roots():
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                    index = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                values: dict[str, str] = {}
                                v = 0
                                while True:
                                    try:
                                        name, val, _ = winreg.EnumValue(subkey, v)
                                    except OSError:
                                        break
                                    v += 1
                                    values[str(name)] = str(val)
                                out.append((subkey_name, values))
                        except OSError:
                            continue
            except OSError:
                continue
        return out

    @staticmethod
    def _matches(values: dict[str, str]) -> bool:
        publisher = values.get("Publisher", "").casefold()
        display = values.get("DisplayName", "").casefold()
        if any(h in publisher for h in _PUBLISHER_HINTS):
            return True
        return any(h in display for h in _TITLE_HINTS)

    @staticmethod
    def _install_dir(values: dict[str, str]) -> Path | None:
        location = values.get("InstallLocation", "").strip().strip('"')
        if not location:
            icon = values.get("DisplayIcon", "").strip()
            icon = icon.split(",")[0].strip().strip('"')
            if icon.casefold().endswith(".exe"):
                location = str(Path(icon).parent)
        if not location:
            return None
        return Path(location)

    def is_available(self) -> bool:
        for _name, values in self._uninstall_entries():
            if self._matches(values) and self._install_dir(values):
                return True
        return False

    def scan(self) -> list[GameEntry]:
        self.errors.clear()
        out: list[GameEntry] = []
        seen: set[str] = set()
        for subkey_name, values in self._uninstall_entries():
            if not self._matches(values):
                continue
            title = values.get("DisplayName", "").strip()
            if not title:
                continue
            install = self._install_dir(values)
            if install is None or not install.is_dir():
                self.errors.append(
                    f"hoyo: '{title}' skipped - install folder missing")
                continue
            exe = guess_main_executable(install)
            if exe is None or not exe.exists():
                self.errors.append(
                    f"hoyo: '{title}' skipped - no executable found")
                continue
            key = str(exe).casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(GameEntry(
                source=self.source,
                platform_id=subkey_name.casefold(),
                title=title,
                install_path=install,
                executable_path=exe,
                extra={"registry": "uninstall database"},
            ))
        return out
