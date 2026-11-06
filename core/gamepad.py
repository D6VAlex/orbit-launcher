from __future__ import annotations

import ctypes
import logging
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

_DPAD_UP = 0x0001
_DPAD_DOWN = 0x0002
_DPAD_LEFT = 0x0004
_DPAD_RIGHT = 0x0008
_BTN_A = 0x1000
_BTN_B = 0x2000

_THUMB_DEADZONE = 12_000
_REPEAT_FIRST_MS = 320
_REPEAT_MS = 140
_POLL_MS = 40

_MOVE_ACTIONS = ("up", "down", "left", "right")

class _Gamepad:

    def __init__(self) -> None:
        self._dll = None
        if not IS_WINDOWS:
            return
        for name in ("xinput1_4.dll", "xinput9_1_0.dll"):
            try:
                self._dll = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        if self._dll is None:
            log.info("XInput not available - gamepad navigation disabled")

    @property
    def available(self) -> bool:
        return self._dll is not None

    def buttons(self) -> set[str]:
        if self._dll is None:
            return set()
        state = XINPUT_STATE()
        try:
            result = self._dll.XInputGetState(0, ctypes.byref(state))
        except OSError:
            return set()
        if result != 0:
            return set()
        pad = state.gamepad
        held: set[str] = set()
        if pad.wButtons & _DPAD_UP:
            held.add("up")
        if pad.wButtons & _DPAD_DOWN:
            held.add("down")
        if pad.wButtons & _DPAD_LEFT:
            held.add("left")
        if pad.wButtons & _DPAD_RIGHT:
            held.add("right")
        if pad.sThumbLY > _THUMB_DEADZONE:
            held.add("up")
        elif pad.sThumbLY < -_THUMB_DEADZONE:
            held.add("down")
        if pad.sThumbLX > _THUMB_DEADZONE:
            held.add("right")
        elif pad.sThumbLX < -_THUMB_DEADZONE:
            held.add("left")
        if pad.wButtons & _BTN_A:
            held.add("confirm")
        if pad.wButtons & _BTN_B:
            held.add("cancel")
        return held

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("gamepad", XINPUT_GAMEPAD),
    ]

class GamepadNavigator(QObject):

    navigated = Signal(str)
    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pad = _Gamepad()
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._held: set[str] = set()
        self._repeat: dict[str, int] = {}
        self._last_poll: float | None = None

    @property
    def available(self) -> bool:
        return self._pad.available

    def start(self) -> None:
        if self._pad.available:
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _poll(self) -> None:
        held = self._pad.buttons()
        now = time.monotonic()
        if self._last_poll is None:
            self._last_poll = now
            self._held = held
            return
        delta_ms = int((now - self._last_poll) * 1000)
        self._last_poll = now

        for action in held - self._held:
            self._dispatch(action)
            self._repeat[action] = _REPEAT_FIRST_MS
        for action in self._held - held:
            self._repeat.pop(action, None)
        for action in held & self._held:
            self._repeat[action] = self._repeat.get(action, 0) - delta_ms
            if self._repeat[action] <= 0:
                self._dispatch(action)
                self._repeat[action] = _REPEAT_MS
        self._held = held

    def _dispatch(self, action: str) -> None:
        if action in _MOVE_ACTIONS:
            self.navigated.emit(action)
        elif action == "confirm":
            self.confirmed.emit()
        elif action == "cancel":
            self.cancelled.emit()
