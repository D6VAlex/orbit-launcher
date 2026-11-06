from __future__ import annotations

from PySide6.QtCore import (QObject, QAbstractAnimation, QEasingCurve,
                            QEvent, QTimer, QVariantAnimation)
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QScrollBar

_WHEEL_STEP_PX = 112
_DURATION_MS = 340
_ACTIVE_WINDOW_MS = 160

_ACTIVE = False

def scroll_is_active() -> bool:
    return _ACTIVE

class SmoothScroller(QObject):

    def __init__(self, area: QAbstractScrollArea, parent: QObject | None = None) -> None:
        super().__init__(parent or area)
        self._area = area
        self._target = 0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_frame)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(_ACTIVE_WINDOW_MS)
        self._idle.timeout.connect(self._sleep)
        area.viewport().installEventFilter(self)

    def _bar(self) -> QScrollBar:
        return self._area.verticalScrollBar()

    def _running(self) -> bool:
        return self._anim.state() == QAbstractAnimation.State.Running

    def _wake(self) -> None:
        global _ACTIVE
        _ACTIVE = True
        self._idle.start()

    def _sleep(self) -> None:
        global _ACTIVE
        if not self._running():
            _ACTIVE = False

    def _on_frame(self, value: float) -> None:
        bar = self._bar()
        bar.setValue(int(round(value)))
        if not self._running():
            return
        self._wake()

    def _begin(self, delta_px: int) -> None:
        bar = self._bar()
        if bar.maximum() <= 0 or delta_px == 0:
            return
        base = self._target if self._running() else bar.value()
        self._target = max(bar.minimum(), min(bar.maximum(), base + delta_px))
        if self._target == bar.value():
            return
        self._anim.stop()
        self._anim.setDuration(_DURATION_MS)
        self._anim.setStartValue(float(bar.value()))
        self._anim.setEndValue(float(self._target))
        self._wake()
        self._anim.start()

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return super().eventFilter(obj, event)
        bar = self._bar()
        if bar.maximum() <= 0:
            return super().eventFilter(obj, event)
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta == 0:
            return super().eventFilter(obj, event)
        notches = delta / 120.0
        step = int(round(notches * _WHEEL_STEP_PX))
        if step == 0:
            step = 1 if delta > 0 else -1
        self._begin(-step)
        return True
