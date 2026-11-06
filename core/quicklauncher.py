from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from utils import win32_helpers as win32

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

HOTKEY_ID_OVERLAY = 1
HOTKEY_ID_CAPTURE = 2

HOTKEY_COMBOS = {
    "ctrl+alt+space": (MOD_CONTROL | MOD_ALT, 0x20),
    "ctrl+alt+g": (MOD_CONTROL | MOD_ALT, 0x47),
    "ctrl+alt+o": (MOD_CONTROL | MOD_ALT, 0x4F),
}
HOTKEY_LABELS = {
    "ctrl+alt+space": "Ctrl + Alt + Space",
    "ctrl+alt+g": "Ctrl + Alt + G",
    "ctrl+alt+o": "Ctrl + Alt + O",
    "off": "Disabled",
}
CAPTURE_COMBO = (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x53)

class GlobalHotkeys(QObject, QAbstractNativeEventFilter):

    activated = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._hwnd = 0
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def apply(self, hwnd: int, combo_key: str) -> None:
        self.unregister()
        if combo_key == "off" or not IS_WINDOWS or not hwnd:
            return
        combo = HOTKEY_COMBOS.get(
            str(combo_key), HOTKEY_COMBOS["ctrl+alt+space"])
        self._hwnd = int(hwnd)
        user32 = win32._user32
        ok_overlay = bool(user32.RegisterHotKey(
            self._hwnd, HOTKEY_ID_OVERLAY,
            combo[0] | MOD_NOREPEAT, combo[1]))
        ok_capture = bool(user32.RegisterHotKey(
            self._hwnd, HOTKEY_ID_CAPTURE, CAPTURE_COMBO[0], CAPTURE_COMBO[1]))
        self._registered = ok_overlay or ok_capture
        log.info("Global hotkeys: overlay=%s capture=%s", ok_overlay, ok_capture)

    def unregister(self) -> None:
        if IS_WINDOWS and self._registered and self._hwnd:
            try:
                win32._user32.UnregisterHotKey(self._hwnd, HOTKEY_ID_OVERLAY)
                win32._user32.UnregisterHotKey(self._hwnd, HOTKEY_ID_CAPTURE)
            except OSError:
                log.warning("UnregisterHotKey failed")
        self._registered = False
        self._hwnd = 0

    def nativeEventFilter(self, eventType, message):
        if (IS_WINDOWS and self._registered
                and eventType in (b"windows_generic_MSG", "windows_generic_MSG")):
            msg_id, wparam = _peek_message(int(message))
            if msg_id == WM_HOTKEY and wparam in (HOTKEY_ID_OVERLAY,
                                                  HOTKEY_ID_CAPTURE):
                self.activated.emit(int(wparam))
                return True, 0
        return False, 0

def _peek_message(address: int) -> tuple[int, int]:
    if not address:
        return 0, 0
    try:
        _, msg_id, wparam, _lparam = win32.parse_message(address)
        return msg_id, wparam
    except Exception:
        return 0, 0
