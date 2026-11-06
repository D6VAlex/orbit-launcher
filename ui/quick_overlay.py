from __future__ import annotations

import logging
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QVBoxLayout, QWidget)

from ui import icons
from ui.components.game_card import rounded_pixmap
from ui.logo import logo_pixmap

log = logging.getLogger(__name__)
_ICON_SIZE = QSize(40, 40)

def rank_entries(entries: list[dict], query: str) -> list[dict]:
    q = str(query or "").strip().casefold()
    if not q:
        ranked = sorted(entries,
                        key=lambda e: (-int(e.get("playtime") or 0),
                                       str(e.get("title", "")).casefold()))
        return ranked
    scored: list[tuple[int, int, str, dict]] = []
    for entry in entries:
        title = str(entry.get("title", ""))
        t = title.casefold()
        if q not in t:
            continue
        if t.startswith(q):
            score = 5
        elif re.search(r"\b" + re.escape(q), t):
            score = 3
        else:
            score = 1
        scored.append((score, int(entry.get("playtime") or 0), t, entry))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
    return [entry for _s, _p, _t, entry in scored]

class _ResultRow(QFrame):
    HEIGHT = 56

    def __init__(self, entry: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entry = entry
        self.setObjectName("QuickRow")
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        art = entry.get("pixmap")
        if isinstance(art, QPixmap) and not art.isNull():
            scaled = rounded_pixmap(art, _ICON_SIZE, 20, 1.0, 0.35)
        else:
            scaled = logo_pixmap(40)
        icon = QLabel()
        icon.setPixmap(scaled)
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(str(entry.get("title", "")))
        title.setObjectName("QuickTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        playtime = str(entry.get("playtime_text") or "")
        meta = QLabel(playtime)
        meta.setObjectName("QuickMeta")

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 16, 8)
        row.setSpacing(12)
        row.addWidget(icon)
        row.addWidget(title, 1)
        row.addWidget(meta)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setProperty("pressed", True)
            self.setStyleSheet(self.styleSheet())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton \
                and self.rect().contains(event.position().toPoint()):
            window = self.window()
            handler = getattr(window, "_launch_entry", None)
            if handler is not None:
                handler(self._entry)
        super().mouseReleaseEvent(event)

class QuickOverlay(QDialog):

    launch_requested = Signal(int)

    WIDTH = 620
    SEARCH_H = 64
    ROW_H = 56
    MAX_ROWS = 6
    PAD_BOTTOM = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._provider = lambda: []
        self._entries: list[dict] = []
        self._results: list[dict] = []
        self._sel = 0

        self._panel = QFrame(self)
        self._panel.setObjectName("QuickPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)
        panel_l = QVBoxLayout(self._panel)
        panel_l.setContentsMargins(6, 6, 6, self.PAD_BOTTOM)
        panel_l.setSpacing(2)

        search_row = QWidget(self._panel)
        search_l = QHBoxLayout(search_row)
        search_l.setContentsMargins(14, 0, 16, 0)
        search_l.setSpacing(12)
        glass = QLabel()
        glass.setPixmap(icons.search_icon(18).pixmap(18, 18))
        glass.setFixedSize(18, 18)
        self._edit = QLineEdit()
        self._edit.setObjectName("QuickInput")
        self._edit.setPlaceholderText("Type a game name and press Enter\u2026")
        self._edit.setFrame(False)
        self._edit.setFixedHeight(self.SEARCH_H)
        self._edit.textChanged.connect(self._apply_filter)
        self._edit.installEventFilter(self)
        search_l.addWidget(glass)
        search_l.addWidget(self._edit, 1)
        panel_l.addWidget(search_row)

        self._rows_host = QWidget(self._panel)
        self._rows_l = QVBoxLayout(self._rows_host)
        self._rows_l.setContentsMargins(0, 0, 0, 0)
        self._rows_l.setSpacing(0)
        panel_l.addWidget(self._rows_host)

        self.setFixedWidth(self.WIDTH)
        self._rebuild_rows([])

    def set_provider(self, provider) -> None:
        self._provider = provider

    def open_overlay(self) -> None:
        self._entries = list(self._provider() or [])
        self._edit.clear()
        self._apply_filter("")
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen is not None \
            else self.screen().availableGeometry() if self.screen() else None
        if geo is not None:
            self.move(geo.center().x() - self.WIDTH // 2,
                      geo.top() + int(geo.height() * 0.22))
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()

    def _entry_payload(self, entry: dict) -> dict:
        payload = dict(entry)
        seconds = int(entry.get("playtime") or 0)
        hours, rem = divmod(seconds, 3600)
        payload["playtime_text"] = f"{hours}h {rem // 60:02d}m" if hours \
            else (f"{rem // 60}m" if seconds else "")
        return payload

    def _apply_filter(self, query: str) -> None:
        ranked = rank_entries(self._entries, query)[:self.MAX_ROWS]
        self._results = ranked
        self._sel = 0
        self._rebuild_rows([self._entry_payload(e) for e in ranked])

    def _rebuild_rows(self, payloads: list[dict]) -> None:
        while self._rows_l.count():
            item = self._rows_l.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not payloads:
            note = QLabel("No game matches \u2014 check the main library")
            note.setObjectName("QuickEmpty")
            note.setFixedHeight(self.ROW_H)
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._rows_l.addWidget(note)
        for index, payload in enumerate(payloads):
            row = _ResultRow(payload, self._rows_host)
            row.setObjectName("QuickRowSel" if index == self._sel
                              else "QuickRow")
            self._rows_l.addWidget(row)
        height = self.SEARCH_H + 12 + len(payloads) * self.ROW_H \
            + self.PAD_BOTTOM
        self.setFixedHeight(max(self.SEARCH_H + self.PAD_BOTTOM + 12, height))

    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                if self._results:
                    step = 1 if key == Qt.Key.Key_Down else -1
                    self._sel = (self._sel + step) % len(self._results)
                    self._sync_selection()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._launch_current()
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def _sync_selection(self) -> None:
        rows = self._rows_host.findChildren(_ResultRow)
        rows = [r for r in rows if r.parent() is self._rows_host]
        for index, row in enumerate(rows):
            row.setObjectName("QuickRowSel" if index == self._sel
                              else "QuickRow")
            row.setStyleSheet(row.styleSheet())
            row.style().unpolish(row)
            row.style().polish(row)

    def _launch_current(self) -> None:
        if not self._results:
            self.close()
            return
        entry = self._results[min(self._sel, len(self._results) - 1)]
        game_id = int(entry.get("id") or 0)
        self.close()
        if game_id:
            self.launch_requested.emit(game_id)

    def _launch_entry(self, entry: dict) -> None:
        game_id = int(entry.get("id") or 0)
        self.close()
        if game_id:
            self.launch_requested.emit(game_id)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
