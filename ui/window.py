from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QObject, QPoint, QRect, QRectF, QPropertyAnimation,
                            QByteArray, QEasingCurve, QSize, Qt, QThread,
                            QTimer, QUrl, QVariantAnimation, Signal, Slot)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor,
                           QDesktopServices, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QProgressDialog, QPushButton, QFrame,
                               QScrollArea, QVBoxLayout, QWidget)

from core import cloudsync, screenshots
from core.client_guard import ClientGuard
from core.database import Database
from core.discord_rpc import DiscordRPC
from core.gamepad import GamepadNavigator
from core.playtime_import import import_steam_playtime
from core.quicklauncher import (GlobalHotkeys, HOTKEY_ID_CAPTURE,
                                HOTKEY_ID_OVERLAY)
from core.riot_clicker import RiotAutoClicker
from core.process_tracker import ProcessTracker
from core.settings import Settings
from core.tray import TrayIcon
from core.updater import APP_VERSION, InstallerDownloader, UpdateChecker
from parsers.base import GameEntry, create_parsers
from ui import icons, styles
from ui.background_manager import CustomBackgroundManager
from ui.components.game_card import GameCard, rounded_pixmap
from ui.gallery import GalleryDialog
from ui.logo import logo_pixmap
from ui.news_dialog import NewsDialog
from ui.quick_overlay import QuickOverlay
from ui.settings_dialog import SettingsDialog
from ui.smooth_scroll import SmoothScroller
from utils import win32_helpers as win32

log = logging.getLogger(__name__)

_ALLOWED_URI_SCHEMES = {"steam", "com.epicgames.launcher", "uplay"}
_CLIENT_BACKED_SOURCES = {"ea", "battlenet", "rockstar"}

_MENU_QSS = (
    "QMenu { background:#12141B; color:#F5F5F7;"
    " border:1px solid rgba(255,255,255,0.13); border-radius:12px;"
    " padding:6px; }"
    "QMenu::item { padding:6px 22px; border-radius:8px; }"
    "QMenu::item:selected { background:rgba(255,255,255,0.16); }"
    "QMenu::separator { height:1px; background:rgba(255,255,255,0.08);"
    " margin:4px 8px; }"
    "QMenu::indicator { width:14px; height:14px; border-radius:4px;"
    " border:1px solid rgba(255,255,255,0.28); background:rgba(255,255,255,0.05);"
    " margin-left:6px; }"
    "QMenu::indicator:checked { background:#F2F4F8;"
    " border:1px solid #F2F4F8; }")

def _fmt_playtime(seconds: int) -> str:
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"

def _split_user_args(text: str) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    cleaned = []
    for token in tokens:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
            token = token[1:-1]
        if token:
            cleaned.append(token)
    return cleaned

def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone() \
            .strftime("%d %b %Y · %H:%M")
    except ValueError:
        return iso

def _open_external_https(url: str) -> bool:
    q = QUrl(str(url))
    if q.scheme().casefold() != "https":
        log.warning("BLOCKED non-https external url: %s", url)
        return False
    return QDesktopServices.openUrl(q)

class _NullRPC:

    def set_activity(self, details: str, state: str) -> None:
        pass

    def clear_to_idle(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

class _GridCanvas(QWidget):
    resized = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("GridCanvas")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()

class _Spinner(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self._angle = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setDuration(1000)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_frame)
        self._anim.start()

    def _on_frame(self, value) -> None:
        self._angle = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#F2F4F8"), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = self.rect().adjusted(6, 6, -6, -6)
        painter.drawArc(rect, int(-self._angle * 16), 90 * 16)

class IconButton(QPushButton):

    def __init__(self, icon_fn, tooltip: str) -> None:
        super().__init__()
        self.setObjectName("WinButton")
        self.setFixedSize(38, 38)
        self._idle = icon_fn(18, QColor("#A9ADB8"))
        self._hot = icon_fn(18, QColor("#FFFFFF"))
        self.setIcon(self._idle)
        self.setIconSize(QSize(18, 18))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)

    def enterEvent(self, event) -> None:
        self.setIcon(self._hot)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(self._idle)
        super().leaveEvent(event)

class _SplashScreen(QFrame):
    splash_done = Signal()

    def __init__(self) -> None:
        super().__init__(None,
                         Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(440, 300)

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._fade_in = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade_in.setDuration(240)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_out = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self._done)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(76))
        logo.setFixedSize(76, 76)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        brand = QLabel("ORBIT")
        brand.setObjectName("LoadingBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._spinner = _Spinner()

        self._status = QLabel("Scanning platforms\u2026")
        self._status.setObjectName("LoadingStatus")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)
        layout.addSpacing(12)
        layout.addWidget(self._spinner, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fade_in.start()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def finish(self) -> None:
        self._fade_out.start()

    def _done(self) -> None:
        self.close()
        self.splash_done.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()),
                            22.0, 22.0)
        painter.fillPath(path, QColor("#000000"))
        painter.setPen(QPen(QColor(255, 255, 255, 46), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

class _FooterBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FooterBar")
        self.setFixedHeight(44)
        self.setStyleSheet("""
#FooterBar { background: transparent;
             border-top: 1px solid rgba(255,255,255,0.05); }
#FooterCredit { color: #5B5E69; font-size: 7pt; letter-spacing: 1.2px; }
""")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)

        layout.addStretch(1)
        credit = QLabel("By D6VAlex")
        credit.setObjectName("FooterCredit")
        layout.addWidget(credit)

class _Toast(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        label = QLabel(self)
        label.setObjectName("ToastText")
        label.setTextFormat(Qt.TextFormat.PlainText)
        self._label = label
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 9, 16, 9)
        row.addWidget(label)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(200)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self.hide()

    def popup(self, text: str, anchor_y: int) -> None:
        self._label.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            x = max(8, (parent.width() - self.width()) // 2)
            self.move(x, max(8, int(anchor_y) - self.height()))
        self._hide_timer.stop()
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(1.0)
        self.show()
        self.raise_()
        self._anim.start()
        self._hide_timer.start(3600)

class _EmptyState(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        self.setFixedWidth(430)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(58))
        logo.setFixedSize(58, 58)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel("Your library is empty")
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("EmptySub")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        row = QHBoxLayout()
        row.setSpacing(10)
        self._rescan_btn = QPushButton("Rescan platforms")
        self._rescan_btn.setObjectName("EmptyPrimary")
        self._add_btn = QPushButton("Add a game manually")
        self._add_btn.setObjectName("EmptyGhost")
        row.addWidget(self._rescan_btn)
        row.addWidget(self._add_btn)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 26, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addSpacing(6)
        layout.addLayout(row)
        self.set_mode("empty")
        self.hide()

    def set_mode(self, mode: str, query: str = "") -> None:
        if mode == "empty":
            self._title.setText("Your library is empty")
            self._subtitle.setText("Orbit scans Steam, Epic, Riot, Battle.net, "
                                    "Ubisoft and more automatically. You can "
                                    "also add any game by hand.")
        else:
            self._title.setText("No games match your search")
            shown = query if len(query) <= 40 else query[:37] + "\u2026"
            self._subtitle.setText(f'Nothing in your library is called "'
                                    f"{shown}.")
        for btn in (self._rescan_btn, self._add_btn):
            btn.setVisible(mode == "empty")
        self.adjustSize()

class _MiniTile(QFrame):
    clicked = Signal(int)

    TILE_W = 214
    TILE_H = 120

    def __init__(self, game_id: int, title: str, playtime: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_id = int(game_id)
        self._title = str(title)
        self._playtime = int(playtime)
        self._art = QPixmap()
        self._hover = False
        self.setObjectName("MiniTile")
        self.setFixedSize(self.TILE_W, self.TILE_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def game_id(self) -> int:
        return self._game_id

    def set_art(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        dpr = max(1.0, self.devicePixelRatioF() or 1.0)
        self._art = rounded_pixmap(
            pixmap, QSize(self.TILE_W - 2, self.TILE_H - 2), 12, dpr, 0.35)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._game_id)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0.5, 0.5, self.TILE_W - 1.0, self.TILE_H - 1.0)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        if not self._art.isNull():
            painter.drawPixmap(self.rect(), self._art)
        else:
            painter.fillRect(self.rect(), QColor("#131824"))
        scrim = QLinearGradient(0.0, self.TILE_H * 0.35, 0.0, self.TILE_H)
        scrim.setColorAt(0.0, QColor(0, 0, 0, 0))
        scrim.setColorAt(1.0, QColor(0, 0, 0, 175))
        painter.fillRect(self.rect(), scrim)
        painter.setClipping(False)
        metrics = painter.fontMetrics()
        title = metrics.elidedText(self._title,
                                   Qt.TextElideMode.ElideRight,
                                   self.TILE_W - 46)
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(QRect(12, self.TILE_H - 30, self.TILE_W - 22, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         title)
        chip = GameCard._chip_text(self._playtime)
        if chip:
            painter.setPen(QColor(255, 255, 255, 140))
            painter.drawText(QRect(self.TILE_W - 52, 8, 42, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             chip)
        ring = QColor(255, 255, 255, 96 if self._hover else 34)
        painter.setPen(QPen(ring, 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 12, 12)

class _ContinueBar(QWidget):
    launch_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        header = QLabel("CONTINUE PLAYING")
        header.setObjectName("SectionLabel")
        self._row = QHBoxLayout()
        self._row.setSpacing(12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(header)
        layout.addLayout(self._row)
        self._tiles: list[_MiniTile] = []
        self.hide()

    def set_items(self, items: list[tuple[int, str, int, QPixmap]]) -> None:
        for tile in self._tiles:
            tile.hide()
            tile.setParent(None)
            tile.deleteLater()
        self._tiles.clear()
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        for game_id, title, playtime, art in items[:4]:
            tile = _MiniTile(game_id, title, playtime, self)
            tile.set_art(art)
            tile.clicked.connect(self.launch_requested.emit)
            self._row.addWidget(tile)
            self._row.addSpacing(0)
            self._tiles.append(tile)
        self._row.addStretch(1)
        self.setVisible(bool(self._tiles))

    def update_art(self, game_id: int, art: QPixmap) -> None:
        for tile in self._tiles:
            if tile.game_id == game_id:
                tile.set_art(art)
                return

class _GamePropsDialog(QDialog):
    _QSS = """
        QDialog { background: #0C0F16; }
        QLabel { color: #F5F6F8; font-size: 9.5pt; }
        #PropsTitle { font-size: 12.5pt; font-weight: 700; }
        #PropsKey { color: #8A8D98; font-size: 8.5pt; }
        #PropsVal { color: #D8DAE2; font-size: 9pt; }
        #PropsBox { background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.09); border-radius: 14px; }
        QLineEdit { background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.11); border-radius: 10px;
            padding: 7px 10px; color: #F5F6F8; font-size: 9.5pt;
            selection-background-color: rgba(255,255,255,0.35); }
        QLineEdit:focus { border-color: rgba(255,255,255,0.40); }
        QCheckBox { color: #D8DAE2; font-size: 10pt; }
        QCheckBox::indicator { width: 17px; height: 17px; border-radius: 5px;
            border: 1px solid rgba(255,255,255,0.25);
            background: rgba(255,255,255,0.06); }
        QCheckBox::indicator:hover { border-color: rgba(255,255,255,0.55); }
        QCheckBox::indicator:checked { background: #F2F4F8;
            border: 1px solid #F2F4F8; }
        QPushButton { border-radius: 10px; padding: 8px 18px;
            font-size: 9.5pt; font-weight: 600; border: none; }
    """

    def __init__(self, data: dict, db: Database,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self._db = db
        self.setWindowTitle("Game properties")
        self.setModal(True)
        self.setFixedWidth(520)
        self.setStyleSheet(self._QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        title = QLabel(str(data.get("title", "")))
        title.setObjectName("PropsTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        source = str(data.get("source", ""))
        label = styles.SOURCE_LABELS.get(source, source.title())
        subtitle = QLabel(f"{label}  \u00b7  game properties")
        subtitle.setObjectName("PropsKey")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(4)

        stats = QFrame()
        stats.setObjectName("PropsBox")
        grid = QGridLayout(stats)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        pairs = [
            ("Total playtime", _fmt_playtime(int(data.get("playtime") or 0))),
            ("Times launched", str(int(data.get("launch_count") or 0))),
            ("Last played", _fmt_date(data.get("last"))),
        ]
        for col, (key, value) in enumerate(pairs):
            k = QLabel(key)
            k.setObjectName("PropsKey")
            v = QLabel(value)
            v.setObjectName("PropsVal")
            grid.addWidget(k, 0, col)
            grid.addWidget(v, 1, col)
        root.addWidget(stats)

        install = str(data.get("install_path") or "\u2014")
        exe = str(data.get("executable_path") or "\u2014 (uses a store link)")
        for name, value in (("Install folder", install), ("Executable", exe)):
            k = QLabel(name)
            k.setObjectName("PropsKey")
            v = QLabel(value)
            v.setObjectName("PropsVal")
            v.setTextFormat(Qt.TextFormat.PlainText)
            metrics = v.fontMetrics()
            v.setText(metrics.elidedText(value, Qt.TextElideMode.ElideMiddle, 470))
            v.setToolTip(value)
            root.addWidget(k)
            root.addWidget(v)

        args_label = QLabel("Launch arguments")
        args_label.setObjectName("PropsKey")
        self._args_edit = QLineEdit(str(data.get("user_args") or ""))
        self._args_edit.setPlaceholderText(
            "Optional flags, e.g.  -novid -fullscreen -w 1920")
        root.addSpacing(4)
        root.addWidget(args_label)
        root.addWidget(self._args_edit)
        args_note = QLabel("Applied when Orbit starts the game executable.")
        args_note.setObjectName("PropsKey")
        root.addWidget(args_note)

        self._admin_check = QCheckBox("Run as administrator")
        self._admin_check.setChecked(bool(data.get("run_admin")))
        root.addWidget(self._admin_check)

        tags_label = QLabel("Tags")
        tags_label.setObjectName("PropsKey")
        self._tags_edit = QLineEdit(
            ", ".join(str(t) for t in (data.get("tags") or [])))
        self._tags_edit.setPlaceholderText(
            "Comma separated, e.g.  FPS, Co-op, Story")
        root.addSpacing(4)
        root.addWidget(tags_label)
        root.addWidget(self._tags_edit)
        tags_note = QLabel("Tags power the filter in the sort menu and the "
                           "quick launcher.")
        tags_note.setObjectName("PropsKey")
        root.addWidget(tags_note)

        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.07); color:#D8DAE2;"
            " border:1px solid rgba(255,255,255,0.11); }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setStyleSheet(
            "QPushButton { background:#F2F4F8; color:#0A0D14;"
            " font-weight:700; }"
            "QPushButton:hover { background:#FFFFFF; }")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _save(self) -> None:
        self._db.set_launch_options(int(self._data["id"]),
                                    self._args_edit.text(),
                                    self._admin_check.isChecked())
        raw_tags = [part.strip() for part in self._tags_edit.text().split(",")]
        self._db.set_game_tags(int(self._data["id"]),
                               [t for t in raw_tags if t])
        self.accept()

    @staticmethod
    def open_dialog(data: dict, db: Database,
                    parent: QWidget | None = None) -> bool:
        dialog = _GamePropsDialog(data, db, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted

class _ScanWorker(QObject):
    game_found = Signal(object)
    scan_finished = Signal(int, list)

    def __init__(self) -> None:
        super().__init__()
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        collected: list[GameEntry] = []
        errors: list[str] = []
        for parser in create_parsers():
            if self._stop:
                return
            try:
                entries = parser.scan()
            except Exception as exc:
                log.exception("Parser %s crashed", parser.source)
                errors.append(f"{parser.source}: {exc}")
                continue
            errors.extend(f"{parser.source}: {e}" for e in parser.errors)
            collected.extend(entries)

        seen: set[tuple[str, str]] = set()
        total = 0
        for entry in collected:
            if self._stop:
                return
            key = (str(entry.install_path).casefold() if entry.install_path else "",
                   str(entry.executable_path).casefold()
                   if entry.executable_path else "")
            if key != ("", ""):
                if key in seen:
                    continue
                seen.add(key)
            self.game_found.emit(entry)
            total += 1
        self.scan_finished.emit(total, errors)

def drive_online(path: str) -> bool:
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    return os.path.exists(drive if drive else os.sep)

class OrbitWindow(QMainWindow):
    TITLE_H = 48

    def __init__(self, db: Database, settings: Settings) -> None:
        super().__init__()
        self._db = db
        self._settings = settings
        self._library: dict[int, dict] = {}
        self._cards: list[list] = []
        self._known: set[tuple[str, str]] = set()
        self._active_sessions: set[int] = set()
        self._query = ""
        self._hwnd = 0
        self._native_chrome_done = False
        self._scan_started = 0.0
        self._scan_done = False
        self._shutting_down = False
        self._playtime_imported = False
        self._force_quit = False
        self._scan_removed = 0
        self._revealed = False
        self._sel_id: int | None = None
        self._positions: dict[int, tuple[int, int]] = {}
        self._scan_new = 0
        self._pending_url = ""
        self._dl_progress: QProgressDialog | None = None
        self._tag_filter: set[str] = set(self._settings.tag_filter)
        self._hotkeys_applied = False

        self.setObjectName("Root")
        self.setWindowTitle("Orbit")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1080, 700)
        self.resize(1300, 820)

        self._tracker = ProcessTracker(db, self)
        self._tracker.game_started.connect(self._on_session_start)
        self._tracker.game_stopped.connect(self._on_session_stop)
        self._tracker.start()
        if self._settings.discord_rpc_enabled:
            self._rpc = DiscordRPC()
        else:
            self._rpc = _NullRPC()
        self._riot_clicker = RiotAutoClicker(self)
        self._client_guard = ClientGuard(self)
        self._updater = UpdateChecker()

        self._tray = TrayIcon(self)
        self._tray.show_main.connect(self._show_from_tray)
        self._tray.launch_favorite.connect(self._launch)
        self._tray.quit_requested.connect(self._quit_from_tray)
        self._tray.show()

        self._gamepad = GamepadNavigator(self)
        self._gamepad.navigated.connect(self._on_gamepad_nav)
        self._gamepad.confirmed.connect(self._on_gamepad_confirm)
        self._gamepad.cancelled.connect(lambda: self._select(None))
        self._gamepad.start()

        self._hotkeys = GlobalHotkeys(self)
        self._hotkeys.activated.connect(self._on_hotkey)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._hotkeys)
        self._quick = QuickOverlay()
        self._quick.set_provider(self._quick_entries)
        self._quick.launch_requested.connect(self._launch)
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(4000)
        self._sync_timer.timeout.connect(lambda: self._run_sync(auto=True))

        self._build_ui()
        self._restore_geometry()

    def _on_gamepad_nav(self, action: str) -> None:
        if not self._nav_allowed():
            return
        moves = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if action in moves:
            self._move_selection(*moves[action])

    def _on_gamepad_confirm(self) -> None:
        if not self._nav_allowed():
            return
        if self._sel_id is None:
            visible = self._visible_cards()
            if visible:
                self._select(visible[0][3])
            return
        self._launch(self._sel_id)

    def _nav_allowed(self) -> bool:
        return (self._revealed and not self._shutting_down
                and self.isActiveWindow())

    def _launch_splash(self) -> None:
        self._splash = _SplashScreen()
        self._splash.splash_done.connect(self._activate_after_splash)
        self._splash.show()
        self._start_scan()
        self._updater.check(self._on_update_result)
        QTimer.singleShot(3000, self._reveal_app)

    def _activate_after_splash(self) -> None:
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _toolbar_button(icon_fn, tooltip: str) -> QPushButton:
        return IconButton(icon_fn, tooltip)

    def _build_ui(self) -> None:
        body = styles.GlassBackdrop()
        self._backdrop = body
        self.setCentralWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        titlebar = styles.GlassTitleBar(self.showMinimized, self._toggle_max, self.close)
        root.addWidget(titlebar)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(20, 14, 20, 12)
        ml.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        sort_btn = IconButton(icons.sliders_icon, "Sort and filter")
        sort_btn.clicked.connect(self._show_sort_menu)
        self._search_field = styles.SearchField("Search games\u2026")
        self._search = self._search_field.edit
        self._search.textChanged.connect(self._on_search_changed)
        top.addWidget(sort_btn)
        top.addStretch(1)
        top.addWidget(self._search_field)
        top.addStretch(1)
        top.addSpacing(38)
        ml.addLayout(top)

        self._continue = _ContinueBar(main)
        self._continue.launch_requested.connect(self._launch)
        ml.addWidget(self._continue)

        self._grid = QScrollArea()
        self._grid.setObjectName("GridArea")
        self._grid.setWidgetResizable(True)
        self._grid.setFrameShape(QFrame.Shape.NoFrame)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._grid.viewport().setStyleSheet(
            "QWidget#qt_scrollarea_viewport { background: transparent; }")
        self._canvas = _GridCanvas()
        self._grid.setWidget(self._canvas)
        self._canvas.resized.connect(self._relayout)
        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._canvas.installEventFilter(self)
        self._empty = _EmptyState(self._grid.viewport())
        self._empty._rescan_btn.clicked.connect(self._rescan)
        self._empty._add_btn.clicked.connect(self._add_manual_game)
        self._grid.verticalScrollBar().setSingleStep(40)
        self._scroller = SmoothScroller(self._grid)
        ml.addWidget(self._grid, 1)

        self._total_chip = QLabel("0 games", objectName="StatsChip")

        dock = QWidget()
        dock_l = QVBoxLayout(dock)
        dock_l.setContentsMargins(0, 2, 0, 0)
        dock_l.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)
        rescan = self._toolbar_button(icons.refresh_icon, "Rescan platforms")
        rescan.clicked.connect(self._rescan)
        add_btn = self._toolbar_button(icons.plus_icon, "Add a game manually")
        add_btn.clicked.connect(self._add_manual_game)
        bg_btn = self._toolbar_button(icons.image_icon, "Custom background")
        bg_btn.clicked.connect(self._show_background_menu)
        news_btn = self._toolbar_button(icons.news_icon, "Gaming news")
        news_btn.clicked.connect(self._open_news)
        gear = self._toolbar_button(icons.gear_icon, "Settings")
        gear.clicked.connect(self._open_settings)
        for btn in (rescan, add_btn, bg_btn, news_btn, gear):
            btn_row.addWidget(btn)
        btn_row.addStretch(1)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        stats_row.addStretch(1)
        stats_row.addWidget(self._total_chip)
        stats_row.addStretch(1)

        dock_l.addLayout(btn_row)
        dock_l.addLayout(stats_row)
        ml.addWidget(dock)
        self._dock = dock

        self._toast = _Toast(body)
        root.addWidget(main, 1)

        self._footer = _FooterBar()
        root.addWidget(self._footer)

        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._search.setFocus)
        QShortcut(QKeySequence("Ctrl+Space"), self).activated.connect(
            self._open_quick_overlay)

    def _start_scan(self) -> None:
        self._db.purge_source("pc")
        self._db.purge_stale_minecraft()
        self._scan_started = time.monotonic()
        self._scan_new = 0
        self._scan_thread = QThread(self)
        self._worker = _ScanWorker()
        self._worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._worker.run)
        self._worker.game_found.connect(self._add_game)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_finished.connect(self._scan_thread.quit)
        self._scan_thread.start()

    def _card_for(self, game_id: int) -> GameCard | None:
        for entry in self._cards:
            if entry[3] == game_id:
                return entry[0]
        return None

    def _relayout(self) -> None:
        if not hasattr(self, "_canvas"):
            return
        pad_l, pad_r, pad_t, pad_b = 8, 12, 24, 28
        gap = 18
        cw = self._canvas.width()
        avail = max(GameCard.CARD_W, cw - pad_l - pad_r)
        cols = max(1, (avail + gap) // (GameCard.CARD_W + gap))
        used = cols * GameCard.CARD_W + (cols - 1) * gap
        x0 = pad_l + max(0, (avail - used) // 2)
        col, y = 0, pad_t
        shown = 0
        self._positions = {}
        for entry in self._cards:
            card = entry[0]
            if card.isHidden():
                card.snap_back()
                continue
            pos = (x0 + col * (GameCard.CARD_W + gap), y)
            card.set_base_pos(*pos)
            self._positions[entry[3]] = pos
            shown += 1
            col += 1
            if col >= cols:
                col = 0
                y += GameCard.CARD_H + gap
        rows = (shown + cols - 1) // cols
        height = pad_t + rows * (GameCard.CARD_H + gap) - gap + pad_b \
            if shown else pad_t + pad_b
        self._canvas.setMinimumHeight(max(0, int(height)))
        self._update_empty_state()

    def _card_tooltip(self, data: dict) -> str:
        source = str(data.get("source", ""))
        label = styles.SOURCE_LABELS.get(source, source.title())
        fav = "Favorite\n" if data.get("is_favorite") else ""
        return (f"{data.get('title', '')}\n{fav}"
                f"via {label}\n"
                f"Playtime: {_fmt_playtime(int(data.get('total_playtime') or 0))}\n"
                f"Last played: {_fmt_date(data.get('last_played'))}")

    def _append_log(self, message: str) -> None:
        log.info(message)

    def _on_search_changed(self, text: str) -> None:
        if not hasattr(self, "_search_timer"):
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.setInterval(130)
            self._search_timer.timeout.connect(self._apply_search)
        self._pending_query = text
        self._search_timer.start()

    def _apply_search(self) -> None:
        self._query = (self._pending_query if hasattr(self, "_pending_query") else "").casefold()
        self._apply_view()

    def _filter_ok(self, game_id: int) -> bool:
        if self._settings.lib_filter == "favorites" \
                and not bool(self._library.get(game_id, {}).get("fav")):
            return False
        if self._tag_filter:
            tags = {str(t).casefold() for t in
                    (self._library.get(game_id, {}).get("tags") or [])}
            wanted = {str(t).casefold() for t in self._tag_filter}
            if not tags.intersection(wanted):
                return False
        return True

    def _apply_view(self) -> None:
        for entry in self._cards:
            entry[0].setVisible(self._matches(entry[1])
                                and self._filter_ok(entry[3]))
        if self._sel_id is not None and self._sel_id not in {
                e[3] for e in self._cards if not e[0].isHidden()}:
            self._select(None)
        self._relayout()
        self._update_count()

    def _matches(self, title_cf: str) -> bool:
        return not self._query or self._query in title_cf

    @Slot(object)
    def _add_game(self, entry: GameEntry) -> None:
        key = (entry.source, entry.platform_id)
        if key in self._known or self._db.is_hidden(entry.source,
                                                    entry.platform_id):
            return
        self._known.add(key)
        self._scan_new += 1
        game_id = self._db.upsert_game(entry)
        row = self._db.get_game(game_id) or {}
        playtime = int(row.get("total_playtime") or 0)
        last = row.get("last_played") or ""
        fav = bool(row.get("is_favorite"))

        self._library[game_id] = {
            "id": game_id, "source": entry.source, "title": entry.title,
            "platform_id": entry.platform_id,
            "install_path": str(entry.install_path) if entry.install_path else "",
            "executable_path": str(entry.executable_path) if entry.executable_path else "",
            "launch_uri": entry.launch_uri or "",
            "launch_args": list(entry.launch_args),
            "user_args": str(row.get("launch_args") or ""),
            "run_admin": bool(row.get("run_admin")),
            "watch_mode": entry.extra.get("watch_mode", ""),
            "mc_dir": entry.extra.get("mc_dir", ""),
            "mc_versions": list(entry.extra.get("mc_versions", [])),
            "hero_urls": entry.hero_urls,
            "playtime": playtime,
            "last": last,
            "fav": fav,
            "watch_name": (entry.extra.get("game_exe_name")
                           or (entry.executable_path.name if entry.executable_path else None)),
            "tags": self._db.game_tags(game_id),
        }

        if hasattr(self, "_splash") and self._splash.isVisible():
            self._splash.set_status(f"Found {len(self._library)} games\u2026")

        verified = bool(entry.launch_uri) or (
            entry.executable_path is not None and entry.executable_path.exists())

        card = GameCard(game_id, entry.title, entry.source,
                        verified=verified, playtime_seconds=playtime,
                        parent=self._canvas)
        card.setToolTip(self._card_tooltip(row))
        card.play_clicked.connect(self._launch)
        card.stop_clicked.connect(self._force_stop)
        card.remove_clicked.connect(self._remove_game)
        card.clicked.connect(self._launch)
        card.menu_requested.connect(self._show_card_menu)
        card.art_ready.connect(self._on_card_art)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.load_cover(entry.cover_urls,
                        exe_path=str(entry.executable_path) if entry.executable_path else None,
                        title=entry.title)
        card.set_running(game_id in self._active_sessions)
        card.setVisible(self._matches(entry.title.casefold())
                        and self._filter_ok(game_id))
        self._cards.append([card, entry.title.casefold(), entry.source, game_id])
        card.play_entrance(min(60 * (len(self._cards) - 1), 480))
        self._relayout()
        self._update_count()

    def _purge_games(self, game_ids: list[int]) -> list[str]:
        removed: list[str] = []
        for game_id in game_ids:
            row = self._db.get_game(game_id)
            if not row:
                continue
            self._db.delete_game(game_id)
            screenshots.delete_game_screenshots(game_id)
            removed.append(str(row.get("title") or ""))
            for entry in list(self._cards):
                if entry[3] != game_id:
                    continue
                self._cards.remove(entry)
                entry[0].deleteLater()
                break
            self._library.pop(game_id, None)
            if row.get("source") and row.get("platform_id"):
                self._known.discard(
                    (str(row["source"]), str(row["platform_id"])))
            self._active_sessions.discard(game_id)
            if self._sel_id == game_id:
                self._sel_id = None
        if removed:
            self._refresh_tray_favorites()
            self._relayout()
            self._update_count()
            self._refresh_continue()
            self._schedule_sync()
        return removed

    def _reconcile_vanished_games(self) -> list[str]:
        doomed: list[int] = []
        for row in self._db.all_games():
            if str(row.get("source") or "") == "manual":
                continue
            paths = [str(row.get(key) or "")
                     for key in ("executable_path", "install_path")]
            paths = [p for p in paths if p]
            if not paths or any(os.path.exists(p) for p in paths):
                continue
            if not all(drive_online(p) for p in paths):
                continue
            if (int(row.get("total_playtime") or 0) == 0
                    and int(row.get("launch_count") or 0) == 0
                    and not int(row.get("is_favorite") or 0)):
                doomed.append(int(row["id"]))
            else:
                self._db.mark_uninstalled(int(row["id"]))
        return self._purge_games(doomed)

    def _rescue_db_games(self) -> None:
        for row in self._db.all_games():
            key = (str(row["source"]), str(row["platform_id"]))
            if key in self._known or self._db.is_hidden(*key):
                continue
            extra: dict = {}
            raw_extra = row.get("extra_json")
            if raw_extra:
                try:
                    parsed = json.loads(str(raw_extra))
                    if isinstance(parsed, dict):
                        extra = parsed
                except json.JSONDecodeError:
                    extra = {}
            exe = Path(str(row["executable_path"])) \
                if row.get("executable_path") else None
            extra.setdefault("game_exe_name",
                             exe.name if exe is not None else None)
            self._add_game(GameEntry(
                source=str(row["source"]),
                platform_id=str(row["platform_id"]),
                title=str(row["title"]),
                install_path=(Path(str(row["install_path"]))
                              if row.get("install_path") else None),
                executable_path=exe,
                launch_uri=row.get("launch_uri") or "",
                cover_urls=[str(row["cover_url"])]
                if row.get("cover_url") else [],
                hero_urls=[str(row["hero_url"])]
                if row.get("hero_url") else [],
                state_flags=row.get("state_flags"),
                extra=extra,
            ))
        self._scan_new = 0

    @Slot(int, list)
    def _on_scan_finished(self, total: int, errors: list[str]) -> None:
        try:
            if errors:
                for message in errors:
                    log.warning("scan: %s", message)
        finally:
            self._scan_done = True
            elapsed = time.monotonic() - self._scan_started
            splash_min = self._settings.splash_min_seconds
            delay_ms = max(0, int((splash_min - elapsed) * 1000))
            QTimer.singleShot(delay_ms, self._reveal_app)
            QTimer.singleShot(0, self._post_scan)
            QTimer.singleShot(delay_ms + 1100,
                              lambda: self._scan_toast(int(total)))

    def _post_scan(self) -> None:
        if self._shutting_down:
            return
        try:
            if not self._playtime_imported:
                self._playtime_imported = True
                try:
                    import_steam_playtime(self._db)
                except Exception:
                    log.exception("Steam playtime import failed")
            self._scan_removed = len(self._reconcile_vanished_games())
            if self._scan_removed:
                log.info("scan: removed %d vanished game(s)",
                         self._scan_removed)
            self._rescue_db_games()
            self._refresh_cards_from_db()
            self._refresh_tray_favorites()
            self._update_count()
            self._apply_sort()
            self._refresh_continue()
            self._schedule_sync()
        except Exception:
            log.exception("Post-scan handling failed - library still usable")

    def _refresh_cards_from_db(self) -> None:
        for entry in self._cards:
            gid = entry[3]
            row = self._db.get_game(gid)
            if not row:
                continue
            lib = self._library.get(gid)
            playtime = int(row.get("total_playtime") or 0)
            last = row.get("last_played") or ""
            fav = bool(row.get("is_favorite"))
            if lib is not None:
                lib["playtime"] = playtime
                lib["last"] = last
                lib["fav"] = fav
                lib["tags"] = self._db.game_tags(gid)
            entry[0].set_playtime(playtime)

    def _update_count(self) -> None:
        if not hasattr(self, "_total_chip"):
            return
        total = len(self._cards)
        shown = sum(1 for entry in self._cards if not entry[0].isHidden())
        hours = sum(int(lib.get("playtime") or 0) for lib in self._library.values())
        text = f"{shown}/{total} games  \u00b7  {_fmt_playtime(hours)}"
        try:
            week = self._db.weekly_seconds(7)
        except Exception:
            week = 0
        if week > 0:
            text += f"  \u00b7  {_fmt_playtime(week)} this week"
        goal_h = self._settings.weekly_goal_hours
        if goal_h > 0:
            goal_seconds = goal_h * 3600
            pct = int(week * 100 / goal_seconds)
            text += f"  \u00b7  {pct}% of goal"
            if week >= goal_seconds:
                self._celebrate_goal()
        self._total_chip.setText(text)

    def _apply_sort(self) -> None:
        if not hasattr(self, "_cards"):
            return
        mode = self._settings.sort_mode
        lib = self._library
        self._cards.sort(key=lambda e: e[1])
        if mode in ("favorites", "last"):
            self._cards.sort(key=lambda e: str(lib.get(e[3], {}).get("last") or ""),
                             reverse=True)
            self._cards.sort(key=lambda e: 0 if lib.get(e[3], {}).get("last") else 1)
        if mode == "playtime":
            self._cards.sort(key=lambda e: int(lib.get(e[3], {}).get("playtime") or 0),
                             reverse=True)
        if mode == "favorites":
            self._cards.sort(key=lambda e: 0 if lib.get(e[3], {}).get("fav") else 1)
        self._relayout()
        self._refresh_continue()

    def _reveal_app(self) -> None:
        if self._shutting_down or self._revealed:
            return
        self._revealed = True
        if hasattr(self, "_splash") and self._splash.isVisible():
            self.show()
            self._splash.finish()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
        self.setFocus()
        self._search.clearFocus()
        self._refresh_continue()
        self._maybe_startup_notice()
        QTimer.singleShot(900, self._check_sync_on_boot)

    def _maybe_startup_notice(self) -> None:
        if self._settings.get("startup_notice_shown"):
            return
        self._settings.set("startup_notice_shown", True)
        if os.name != "nt" or not self._settings.auto_startup:
            return
        if not win32.startup_command() or win32.is_in_startup():
            return
        if win32.add_to_startup():
            QTimer.singleShot(1200, lambda: self._show_toast(
                "Orbit will now start with Windows \u2014 turn it off in Settings"))

    def _apply_hotkeys(self) -> None:
        try:
            self._hotkeys.apply(int(self.winId()), self._settings.quick_hotkey)
        except Exception:
            log.warning("Global hotkey setup failed", exc_info=True)

    def _on_hotkey(self, hotkey_id: int) -> None:
        if self._shutting_down:
            return
        if hotkey_id == HOTKEY_ID_OVERLAY:
            self._open_quick_overlay()
        elif hotkey_id == HOTKEY_ID_CAPTURE:
            self._capture_screenshot()

    def _open_quick_overlay(self) -> None:
        if self._shutting_down:
            return
        self._quick.open_overlay()

    def _quick_entries(self) -> list[dict]:
        entries = []
        for entry in self._cards:
            game_id = entry[3]
            lib = self._library.get(game_id) or {}
            card = entry[0]
            try:
                art = card.art_pixmap()
            except RuntimeError:
                art = QPixmap()
            entries.append({
                "id": game_id,
                "title": str(lib.get("title") or entry[1]),
                "playtime": int(lib.get("playtime") or 0),
                "pixmap": art,
            })
        return entries

    def _capture_screenshot(self) -> None:
        running = self._tracker.running_games()
        if not running:
            self._show_toast("No game is running \u2014 nothing to capture")
            return
        game_id = running[0]
        title = str((self._library.get(game_id) or {}).get("title") or "game")
        path = screenshots.capture_screen(game_id)
        if path is not None:
            self._show_toast(f"Screenshot saved \u2014 {title}")
        else:
            self._show_toast("Screenshot capture failed")

    def _open_gallery(self, game_id: int) -> None:
        row = self._db.get_game(game_id)
        if not row:
            return
        GalleryDialog({"id": game_id,
                       "title": str(row.get("title") or "")}, self).exec()

    def _open_news(self) -> None:
        if self._shutting_down:
            return
        NewsDialog(self._db, self._settings, self).exec()

    def _schedule_sync(self) -> None:
        if not self._settings.sync_auto or not self._settings.sync_dir:
            return
        self._sync_timer.start()

    def _run_sync(self, auto: bool = True) -> None:
        if self._shutting_down:
            return
        directory = self._settings.sync_dir
        if not directory:
            return
        try:
            profile = cloudsync.build_profile(self._db, self._settings)
        except Exception:
            log.exception("Sync profile build failed")
            return
        path = cloudsync.write_profile(directory, profile)
        if path is None:
            if not auto:
                self._show_toast("Backup failed \u2014 folder not writable?")
            return
        self._settings.set("last_sync_seen",
                           str(profile.get("saved_at") or ""))
        if not auto:
            self._show_toast("Backup saved to sync folder")

    def _check_sync_on_boot(self) -> None:
        if self._shutting_down:
            return
        directory = self._settings.sync_dir
        if not directory:
            return
        profile = cloudsync.read_profile(directory)
        if profile is None:
            return
        saved_at = str(profile.get("saved_at") or "")
        if not saved_at or saved_at == self._settings.last_sync_seen:
            return
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#0F1218; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:rgba(255,255,255,0.07); color:#E8EAF0;"
            " border:1px solid rgba(255,255,255,0.13); border-radius:10px;"
            " padding:6px 18px; min-width:76px; font-weight:600; }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }"
            "QPushButton:default { background:#F2F4F8; color:#0A0D14;"
            " border-color:#F2F4F8; font-weight:700; }")
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Cloud sync")
        box.setText("A newer Orbit backup was found in your sync folder."
                    "\n\nRestore (replace) loads it over this library. Merge "
                    "keeps this library and adds anything missing.")
        replace_btn = box.addButton("Restore (replace)",
                                    QMessageBox.ButtonRole.AcceptRole)
        merge_btn = box.addButton("Merge",
                                  QMessageBox.ButtonRole.ActionRole)
        box.addButton("Keep local", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace_btn:
            mode = "replace"
        elif clicked is merge_btn:
            mode = "merge"
        else:
            self._settings.set("last_sync_seen", saved_at)
            return
        summary = cloudsync.apply_profile(self._db, profile, mode)
        self._settings.set("last_sync_seen", saved_at)
        if mode == "replace":
            for key, value in cloudsync.settings_from_profile(profile).items():
                self._settings.set(key, value)
        self._reload_library_from_db()
        self._show_toast("Library synced \u2014 "
                         + cloudsync.describe_summary(summary))

    def _reload_library_from_db(self) -> None:
        for entry in list(self._cards):
            entry[0].deleteLater()
        self._cards.clear()
        self._library.clear()
        self._known.clear()
        self._sel_id = None
        self._positions = {}
        try:
            self._apply_view()
        except Exception:
            pass
        for row in self._db.all_games():
            extra: dict = {}
            raw_extra = row.get("extra_json")
            if raw_extra:
                try:
                    parsed = json.loads(str(raw_extra))
                    if isinstance(parsed, dict):
                        extra = parsed
                except json.JSONDecodeError:
                    extra = {}
            exe = Path(str(row["executable_path"])) \
                if row.get("executable_path") else None
            extra.setdefault("game_exe_name",
                             exe.name if exe is not None else None)
            entry = GameEntry(
                source=str(row["source"]),
                platform_id=str(row["platform_id"]),
                title=str(row["title"]),
                install_path=Path(str(row["install_path"]))
                if row.get("install_path") else None,
                executable_path=exe,
                launch_uri=row.get("launch_uri") or "",
                cover_urls=[str(row["cover_url"])]
                if row.get("cover_url") else [],
                hero_urls=[str(row["hero_url"])]
                if row.get("hero_url") else [],
                state_flags=row.get("state_flags"),
                extra=extra,
            )
            self._add_game(entry)
        self._scan_new = 0
        self._refresh_cards_from_db()
        self._refresh_tray_favorites()
        self._apply_sort()
        self._apply_view()
        self._update_count()
        self._refresh_continue()

    def _celebrate_goal(self) -> None:
        try:
            week_key = datetime.now().strftime("%G-W%V")
        except ValueError:
            week_key = datetime.now().strftime("%Y-%m")
        if self._settings.goal_celebrated_week == week_key:
            return
        self._settings.set("goal_celebrated_week", week_key)
        if self._revealed and not self._shutting_down:
            QTimer.singleShot(800, lambda: self._show_toast(
                "Weekly goal reached \u2014 well played!"))

    def _restore_geometry(self) -> None:
        raw = self._settings.win_geometry
        if not raw:
            return
        try:
            self.restoreGeometry(QByteArray.fromHex(raw.encode("ascii")))
        except Exception:
            log.debug("Window geometry could not be restored")

    def _save_geometry(self) -> None:
        try:
            hex_data = bytes(self.saveGeometry().toHex()).decode("ascii")
            self._settings.set("win_geometry", hex_data)
        except Exception:
            log.debug("Window geometry could not be saved")

    def _show_toast(self, text: str) -> None:
        if self._shutting_down:
            return
        dock_h = self._dock.height() if hasattr(self, "_dock") else 0
        footer_h = self._footer.height() if hasattr(self, "_footer") else 0
        self._toast.popup(text, self._backdrop.height() - dock_h - footer_h - 20)

    def _scan_toast(self, total: int) -> None:
        if self._shutting_down or not self._revealed:
            return
        new = self._scan_new
        removed = getattr(self, "_scan_removed", 0)
        message = f"Scan finished \u2014 {total} games"
        if new > 0:
            message += f" \u00b7 {new} new"
        if removed > 0:
            message += f" \u00b7 {removed} removed"
        self._show_toast(message)

    def _update_empty_state(self) -> None:
        if not hasattr(self, "_empty"):
            return
        total = len(self._cards)
        shown = sum(1 for entry in self._cards if not entry[0].isHidden())
        if total == 0:
            self._empty.set_mode("empty")
            self._empty.show()
        elif shown == 0:
            self._empty.set_mode("noresults", self._query)
            self._empty.show()
        else:
            self._empty.hide()
            return
        vw = max(0, self._canvas.width())
        vh = max(0, self._grid.viewport().height())
        self._empty.adjustSize()
        self._empty.move(max(0, (vw - self._empty.width()) // 2),
                         max(28, (vh - self._empty.height()) // 2 - 24))

    def _refresh_continue(self) -> None:
        if not hasattr(self, "_continue"):
            return
        try:
            rows = self._db.recently_played(4)
        except Exception:
            rows = []
        items = []
        for row in rows:
            game_id = int(row["id"])
            card = self._card_for(game_id)
            art = card.art_pixmap() if card is not None else QPixmap()
            items.append((game_id, str(row["title"]),
                          int(row["total_playtime"] or 0), art))
        self._continue.set_items(items)

    def _on_card_art(self, game_id: int) -> None:
        card = self._card_for(game_id)
        if card is not None:
            self._continue.update_art(game_id, card.art_pixmap())

    def _show_sort_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_QSS)
        header = QAction("Sort by", menu)
        header.setEnabled(False)
        menu.addAction(header)
        sort_group = QActionGroup(menu)
        sort_group.setExclusive(True)
        sort_items = (
            ("favorites", "Favorites first"),
            ("last", "Last played"),
            ("playtime", "Most played"),
            ("name", "Name"),
        )
        current_sort = self._settings.sort_mode
        for mode, label in sort_items:
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(mode == current_sort)
            act.triggered.connect(
                lambda _checked, m=mode: self._set_sort_mode(m))
            sort_group.addAction(act)
            menu.addAction(act)
        menu.addSeparator()
        filter_header = QAction("Show", menu)
        filter_header.setEnabled(False)
        menu.addAction(filter_header)
        filter_group = QActionGroup(menu)
        filter_group.setExclusive(True)
        current_filter = self._settings.lib_filter
        for mode, label in (("all", "All games"), ("favorites", "Favorites only")):
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(mode == current_filter)
            act.triggered.connect(
                lambda _checked, m=mode: self._set_lib_filter(m))
            filter_group.addAction(act)
            menu.addAction(act)
        tags = []
        try:
            tags = self._db.all_tags()[:12]
        except Exception:
            tags = []
        if tags:
            menu.addSeparator()
            tags_header = QAction("Tags", menu)
            tags_header.setEnabled(False)
            menu.addAction(tags_header)
            for name, count in tags:
                act = QAction(f"{name}  ({count})", menu)
                act.setCheckable(True)
                act.setChecked(name in self._tag_filter)
                act.triggered.connect(
                    lambda checked, n=name: self._toggle_tag_filter(n, checked))
                menu.addAction(act)
        menu.exec(QCursor.pos())

    def _toggle_tag_filter(self, name: str, enabled: bool) -> None:
        if enabled:
            self._tag_filter.add(str(name))
        else:
            self._tag_filter.discard(str(name))
        self._settings.set("tag_filter", sorted(self._tag_filter))
        self._apply_view()

    def _set_sort_mode(self, mode: str) -> None:
        self._settings.set("sort_mode", mode)
        self._apply_sort()

    def _set_lib_filter(self, mode: str) -> None:
        self._settings.set("lib_filter", mode)
        self._apply_view()

    def _visible_cards(self) -> list[list]:
        return [entry for entry in self._cards if not entry[0].isHidden()]

    def _select(self, game_id: int | None) -> None:
        old = self._card_for(self._sel_id) if self._sel_id is not None else None
        if old is not None:
            old.set_selected(False)
        self._sel_id = game_id
        if game_id is None:
            return
        card = self._card_for(game_id)
        if card is not None:
            card.set_selected(True)
            self._grid.ensureWidgetVisible(card, 24, 24)

    def _move_selection(self, dx: int, dy: int) -> None:
        visible = self._visible_cards()
        if not visible:
            return
        if self._sel_id is None or self._sel_id not in self._positions:
            self._select(visible[0][3])
            return
        x, y = self._positions[self._sel_id]
        best, best_score = None, None
        for entry in visible:
            game_id = entry[3]
            if game_id == self._sel_id:
                continue
            px, py = self._positions.get(game_id, (0, 0))
            if dx and (px - x) * dx <= 0:
                continue
            if dy and (py - y) * dy <= 0:
                continue
            distance = abs(px - x) + abs(py - y)
            if dx and abs(py - y) >= GameCard.CARD_H:
                distance += 400
            if dy and abs(px - x) >= GameCard.CARD_W:
                distance += 400
            if best_score is None or distance < best_score:
                best, best_score = game_id, distance
        if best is not None:
            self._select(best)

    def _nav_key(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._sel_id is not None:
                self._launch(self._sel_id)
                return True
            return False
        if key == Qt.Key.Key_Escape:
            if self._sel_id is not None:
                self._select(None)
                return True
            return False
        moves = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if key in moves:
            if self._nav_allowed():
                self._move_selection(*moves[key])
            return True
        text = event.text()
        if text and text.isprintable() and text.strip():
            self._search.setFocus()
            self._search.setText(text)
            return True
        return False

    def keyPressEvent(self, event) -> None:
        if self._nav_key(event):
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "_canvas", None) \
                and event.type() == event.Type.KeyPress \
                and self._nav_key(event):
            return True
        return super().eventFilter(obj, event)

    def _on_update_result(self, has_update: bool, url: str, notes: str) -> None:
        if not has_update or self._shutting_down:
            return
        self._pending_url = str(url or "")
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#0F1218; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:rgba(255,255,255,0.07); color:#E8EAF0;"
            " border:1px solid rgba(255,255,255,0.13); border-radius:10px;"
            " padding:6px 18px; min-width:76px; font-weight:600; }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }"
            "QPushButton:default { background:#F2F4F8; color:#0A0D14;"
            " border-color:#F2F4F8; font-weight:700; }"
            "QPushButton:default:hover { background:#FFFFFF; }")
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Update available")
        text = "A new version of Orbit is available."
        if notes:
            text += f"\n\n{notes}"
        text += "\n\nDownload and install it now?"
        box.setText(text)
        download_btn = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        page_btn = box.addButton("Open page", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is page_btn and self._pending_url:
            _open_external_https(self._pending_url)
            return
        if clicked is download_btn and self._pending_url:
            self._download_update(self._pending_url)

    def _download_update(self, url: str) -> None:
        if getattr(self, "_downloader", None) is not None:
            return
        sha = getattr(self._updater, "last_sha", "")
        if not sha:
            log.warning("Update manifest has no SHA-256 - installing unverified")
        import tempfile
        dest = Path(tempfile.gettempdir()) / "Orbit-Setup-update.exe"
        progress = QProgressDialog("Downloading the Orbit update\u2026",
                                   "Cancel", 0, 1, self)
        progress.setWindowTitle("Updating Orbit")
        progress.setStyleSheet(
            "QProgressDialog { background:#0F1218; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:rgba(255,255,255,0.07); color:#E8EAF0;"
            " border:1px solid rgba(255,255,255,0.13); border-radius:10px;"
            " padding:6px 18px; font-weight:600; }"
            "QProgressBar { background:rgba(255,255,255,0.06); border:none;"
            " border-radius:5px; height:10px; }"
            "QProgressBar::chunk { background:#F2F4F8; border-radius:5px; }")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        self._dl_progress = progress
        self._downloader = InstallerDownloader(self)
        self._downloader.progress.connect(self._on_dl_progress)
        self._downloader.finished.connect(
            lambda ok, message: self._on_dl_done(ok, message, dest))
        progress.canceled.connect(self._downloader.abort)
        self._downloader.start(url, sha, dest)

    def _on_dl_progress(self, received: int, total: int) -> None:
        progress = self._dl_progress
        if progress is None:
            return
        if total > 0:
            progress.setRange(0, total)
            progress.setValue(received)
        else:
            progress.setRange(0, 0)

    def _on_dl_done(self, ok: bool, message: str, dest: Path) -> None:
        if self._dl_progress is not None:
            self._dl_progress.reset()
            self._dl_progress.deleteLater()
            self._dl_progress = None
        if not ok:
            if message == "checksum mismatch":
                self._show_toast("Update rejected \u2014 checksum mismatch")
            else:
                self._show_toast("Update download failed")
            log.warning("Update download failed: %s", message)
            return
        self._install_update(dest)

    def _install_update(self, dest: Path) -> None:
        if os.name != "nt":
            _open_external_https(dest.as_uri())
            return
        import ctypes
        try:
            code = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(dest), "", None, 1)
        except OSError as exc:
            log.warning("Could not start the update installer: %s", exc)
            return
        if code <= 32:
            log.warning("Update installer declined or failed (%s)", code)
            return
        self._force_quit = True
        self.close()

    def _open_settings(self) -> None:
        accepted, restored = SettingsDialog.open_dialog(
            self._settings, self, db=self._db)
        if not accepted:
            return
        self._apply_hotkeys()
        self._update_count()
        self._schedule_sync()
        if restored:
            self._reload_library_from_db()
            self._show_toast("Library restored from backup")

    def _rescan(self) -> None:
        if getattr(self, "_scan_thread", None) and self._scan_thread.isRunning():
            return
        self._start_scan()

    def _add_manual_game(self) -> None:
        exe, _selected = QFileDialog.getOpenFileName(
            self, "Choose the game executable", "",
            "Executables (*.exe);;All files (*)")
        if not exe:
            return
        p = Path(exe)
        if ("manual", str(p).casefold()) in self._known:
            return
        if p.suffix.casefold() != ".exe":
            return
        try:
            if not p.is_file() or p.stat().st_size <= 0:
                return
        except OSError:
            return
        title = p.stem.replace("_", " ").strip() or "My Game"
        try:
            game_id = self._db.add_manual_game(title, str(p))
        except Exception:
            log.exception("Manual add failed")
            return
        entry = GameEntry(
            source="manual", platform_id=str(p).casefold(), title=title,
            install_path=p.parent, executable_path=p, state_flags=4)
        self._add_game(entry)
        self._apply_sort()

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()

    def _show_background_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_QSS)
        act_set = QAction("Set custom background\u2026", menu)
        act_set.triggered.connect(self._set_custom_background)
        menu.addAction(act_set)
        act_reset = QAction("Reset to default", menu)
        act_reset.setEnabled(CustomBackgroundManager.exists())
        act_reset.triggered.connect(self._reset_background)
        menu.addAction(act_reset)
        menu.exec(QCursor.pos())

    def _set_custom_background(self) -> None:
        source, _selected = QFileDialog.getOpenFileName(
            self, "Choose a background image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not source:
            return
        ok, message = CustomBackgroundManager.validate_and_store(source)
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#0F1218; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:#F2F4F8; color:#0A0D14; border:none;"
            " border-radius:10px; padding:6px 18px; min-width:70px;"
            " font-weight:700; }"
            "QPushButton:hover { background:#FFFFFF; }"
            "QPushButton:pressed { background:#C9CEDA; }")
        if ok:
            self._backdrop.reload_custom()
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Background")
            box.setText(message)
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Rejected")
            box.setText(f"The file was rejected:\n\n{message}")
        box.exec()

    def _reset_background(self) -> None:
        if CustomBackgroundManager.clear():
            self._backdrop.reload_custom()

    def _toggle_favorite(self, game_id: int) -> None:
        row = self._db.get_game(game_id) or {}
        new_val = not bool(row.get("is_favorite"))
        self._db.set_favorite(game_id, new_val)
        lib = self._library.get(game_id)
        if lib is not None:
            lib["fav"] = new_val
        for entry in self._cards:
            if entry[3] == game_id:
                updated = dict(row, is_favorite=1 if new_val else 0)
                entry[0].setToolTip(self._card_tooltip(updated))
                break
        self._refresh_tray_favorites()
        self._apply_sort()
        self._schedule_sync()

    def _refresh_tray_favorites(self) -> None:
        favs = self._db.favorites()
        self._tray.set_favorites([(f["id"], f["title"]) for f in favs])

    def _set_custom_image(self, game_id: int) -> None:
        card = self._card_for(game_id)
        if card is None:
            return
        source, _selected = QFileDialog.getOpenFileName(
            self, "Choose a cover image", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if source:
            card.set_custom_image(source)

    def _show_card_menu(self, game_id: int) -> None:
        row = self._db.get_game(game_id) or {}
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_QSS)
        act_launch = QAction("Launch", menu)
        act_launch.setIcon(icons.play_icon(14))
        act_launch.triggered.connect(lambda: self._launch(game_id))
        menu.addAction(act_launch)
        menu.addSeparator()
        fav_label = ("Unpin from favorites" if row.get("is_favorite")
                     else "Pin to favorites")
        act_fav = QAction(fav_label, menu)
        act_fav.triggered.connect(lambda: self._toggle_favorite(game_id))
        menu.addAction(act_fav)
        act_image = QAction("Set custom cover\u2026", menu)
        act_image.triggered.connect(lambda: self._set_custom_image(game_id))
        menu.addAction(act_image)
        act_gallery = QAction("Screenshots\u2026", menu)
        act_gallery.triggered.connect(lambda: self._open_gallery(game_id))
        menu.addAction(act_gallery)
        act_props = QAction("Properties\u2026", menu)
        act_props.setIcon(icons.info_icon(14))
        act_props.triggered.connect(lambda: self._open_game_properties(game_id))
        menu.addAction(act_props)
        install_path = str(row.get("install_path") or "")
        if install_path and Path(install_path).is_dir():
            act_folder = QAction("Open install folder", menu)
            act_folder.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(install_path)))
            menu.addAction(act_folder)
        menu.addSeparator()
        act_remove = QAction("Remove from library", menu)
        act_remove.setIcon(icons.trash_icon(14, QColor("#A8ABB8")))
        act_remove.triggered.connect(lambda: self._remove_game(game_id))
        menu.addAction(act_remove)
        menu.exec(QCursor.pos())

    def _open_game_properties(self, game_id: int) -> None:
        row = self._db.get_game(game_id)
        lib = self._library.get(game_id)
        if not row or lib is None:
            return
        data = {
            "id": game_id,
            "title": row.get("title") or lib.get("title", ""),
            "source": row.get("source") or lib.get("source", ""),
            "playtime": row.get("total_playtime") or 0,
            "launch_count": row.get("launch_count") or 0,
            "last": row.get("last_played"),
            "install_path": row.get("install_path") or "",
            "executable_path": row.get("executable_path") or "",
            "user_args": str(row.get("launch_args") or ""),
            "run_admin": bool(row.get("run_admin")),
            "tags": self._db.game_tags(game_id),
        }
        if _GamePropsDialog.open_dialog(data, self._db, self):
            fresh = self._db.get_game(game_id) or {}
            lib["user_args"] = str(fresh.get("launch_args") or "")
            lib["run_admin"] = bool(fresh.get("run_admin"))
            lib["tags"] = self._db.game_tags(game_id)
            self._show_toast("Properties saved")
            self._schedule_sync()

    def _remove_game(self, game_id: int) -> None:
        row = self._db.get_game(game_id) or {}
        title = str(row.get("title") or "this game")
        if self._tracker.is_running(game_id):
            box = QMessageBox(self)
            box.setStyleSheet(
                "QMessageBox { background:#0F1218; }"
                "QLabel { color:#F5F5F7; font-size:10pt; }"
                "QPushButton { background:#F2F4F8; color:#0A0D14; border:none;"
                " border-radius:10px; padding:6px 18px; min-width:70px;"
                " font-weight:700; }"
                "QPushButton:hover { background:#FFFFFF; }"
                "QPushButton:pressed { background:#C9CEDA; }")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Cannot remove")
            box.setText(f"'{title}' is currently running.\n"
                        "Stop it first, then remove it.")
            box.exec()
            return
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#0F1218; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:rgba(255,255,255,0.07); color:#E8EAF0;"
            " border:1px solid rgba(255,255,255,0.13); border-radius:10px;"
            " padding:6px 18px; min-width:70px; font-weight:600; }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }"
            "QPushButton:default { background:#F2F4F8; color:#0A0D14;"
            " border-color:#F2F4F8; font-weight:700; }"
            "QPushButton:default:hover { background:#FFFFFF; }")
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Remove game")
        box.setText(f"Remove '{title}' from your library?\n\n"
                    "Its playtime history will be deleted too.\n"
                    "The game files on disk are NOT touched.")
        yes = box.addButton("Remove", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return

        source = str(row.get("source") or "")
        platform_id = str(row.get("platform_id") or "")
        if source and platform_id:
            self._db.hide_game(source, platform_id, title)
        self._purge_games([game_id])
        self._show_toast(f"'{title}' removed \u2014 it won't be re-detected")

    @Slot(int)
    def _launch(self, game_id: int) -> None:
        data = self._library.get(game_id)
        if not data:
            return
        title = data["title"]
        try:
            self._db.record_launch(game_id)
            if data["launch_uri"]:
                scheme = QUrl(data["launch_uri"]).scheme().casefold()
                if scheme not in _ALLOWED_URI_SCHEMES:
                    log.warning("BLOCKED non-whitelisted scheme for %s", title)
                    return
                QDesktopServices.openUrl(QUrl(data["launch_uri"]))
                self._db.touch_last_played(game_id)
                watch_name = data.get("watch_name")
                if watch_name:
                    self._tracker.watch(game_id, title, process_name=watch_name)
                return

            if data["executable_path"]:
                if data.get("source") in _CLIENT_BACKED_SOURCES:
                    self._db.touch_last_played(game_id)
                    self._client_guard.launch_with_client(
                        data["source"],
                        lambda: self._spawn_game_exe(data, game_id),
                        self._append_log)
                    return
                self._spawn_game_exe(data, game_id)
        except Exception as exc:
            log.exception("Launch failed for %s", title)
        finally:
            QTimer.singleShot(0, self._refresh_continue)

    def _missing_exe_dialog(self, data: dict, game_id: int) -> None:
        title = str(data.get("title") or "This game")
        if self._shutting_down:
            return
        log.info("Launch refused for %s: files are missing on disk", title)
        box = QMessageBox(self)
        box.setStyleSheet(
            "QMessageBox { background:#0F1218; }"
            "QLabel { color:#F5F5F7; font-size:10pt; }"
            "QPushButton { background:rgba(255,255,255,0.07); color:#E8EAF0;"
            " border:1px solid rgba(255,255,255,0.13); border-radius:10px;"
            " padding:6px 18px; min-width:70px; font-weight:600; }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }"
            "QPushButton:default { background:#F2F4F8; color:#0A0D14;"
            " border-color:#F2F4F8; font-weight:700; }")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Game files missing")
        box.setText(f"The files for '{title}' are no longer on disk.\n\n"
                    "It was probably uninstalled or moved. You can remove it "
                    "from the library now \u2014 it won't come back on the next "
                    "scan.")
        remove = box.addButton("Remove from library",
                               QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep it", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is remove:
            row = self._db.get_game(game_id) or {}
            source = str(row.get("source") or "")
            platform_id = str(row.get("platform_id") or "")
            if source and platform_id:
                self._db.hide_game(source, platform_id, title)
            self._purge_games([game_id])
            self._show_toast(f"'{title}' removed \u2014 it won't be re-detected")

    def _spawn_game_exe(self, data: dict, game_id: int) -> None:
        title = data["title"]
        watch_name: str | None = None
        watch_pid: int | None = None
        try:
            exe = data["executable_path"]
            exe_path = Path(exe) if exe else None
            if exe_path is None or exe_path.suffix.casefold() != ".exe":
                log.warning("Launch blocked for %s: invalid executable (%s)",
                            title, exe)
                return
            try:
                missing = False
                if not exe_path.is_file() or exe_path.stat().st_size <= 0:
                    missing = True
            except OSError:
                missing = True
            if missing:
                self._missing_exe_dialog(data, game_id)
                return
            install = str(data.get("install_path") or "")
            if install:
                try:
                    root = Path(install).resolve()
                    target = exe_path.resolve()
                    if root != target and root not in target.parents:
                        log.warning("Launch blocked for %s: executable lives "
                                    "outside its install folder", title)
                        return
                except OSError:
                    pass
            args = list(data.get("launch_args", []))
            args += _split_user_args(data.get("user_args"))
            mc_versions = list(data.get("mc_versions", []))
            if data.get("mc_dir"):
                args += ["--workDir", str(data["mc_dir"])]
            run_admin = bool(data.get("run_admin")) and os.name == "nt"
            proc = None
            watch_pid: int | None = None
            watch_name = data.get("watch_name")
            if run_admin:
                import ctypes
                params = subprocess.list2cmdline(args)
                code = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", exe, params, os.path.dirname(exe) or None, 1)
                if code <= 32:
                    log.warning("Elevated launch for %s declined or failed (%s)",
                                title, code)
                    return
                self._append_log(f"Launched {title} (elevated)")
            else:
                flags = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
                proc = subprocess.Popen([exe, *args],
                                        cwd=os.path.dirname(exe) or None,
                                        creationflags=flags)
                self._append_log(f"Launched {title} (pid {proc.pid})")
            if data.get("mc_dir"):
                self._append_log(
                    f"Minecraft Launcher \u2014 {len(mc_versions)} installed "
                    f"version(s): {', '.join(mc_versions[:6])}"
                    f"{' \u2026' if len(mc_versions) > 6 else ''}")
            if run_admin:
                watch_pid = None
            elif data.get("launch_args") or data.get("user_args"):
                if data.get("watch_mode") == "pid":
                    watch_pid = proc.pid if proc is not None else None
            else:
                watch_pid = proc.pid if proc is not None else None
            self._db.touch_last_played(game_id)
        except Exception as exc:
            log.exception("Launch failed for %s", title)
            return
        if watch_name or watch_pid:
            self._tracker.watch(game_id, title, process_name=watch_name, pid=watch_pid)
        if data.get("source") == "riot" and self._settings.riot_clicker_enabled:
            self._riot_clicker.arm(data.get("watch_name"))

    @Slot(int)
    def _force_stop(self, game_id: int) -> None:
        data = self._library.get(game_id)
        if not data:
            return
        title = data["title"]
        if not self._tracker.is_running(game_id):
            return
        if self._tracker.force_stop(game_id, title):
            self._append_log(f"Force-closed \u2014 {title}")

    @Slot(int, str)
    def _on_session_start(self, game_id: int, title: str) -> None:
        source = self._library.get(game_id, {}).get("source", "")
        self._append_log(f"Session started \u2014 {title}")
        self._rpc.set_activity(
            f"Playing {title}",
            f"via Orbit \u00b7 {styles.SOURCE_LABELS.get(source, '')}".strip())
        self._active_sessions.add(game_id)
        card = self._card_for(game_id)
        if card is not None:
            card.set_running(True)

    @Slot(int, str, int)
    def _on_session_stop(self, game_id: int, title: str, duration_s: int) -> None:
        self._append_log(f"Session ended \u2014 {title} ({_fmt_playtime(duration_s)})")
        self._rpc.clear_to_idle()
        self._active_sessions.discard(game_id)
        card = self._card_for(game_id)
        if card is not None:
            card.set_running(False)
        row = self._db.get_game(game_id)
        if row:
            lib = self._library.get(game_id)
            playtime = int(row.get("total_playtime") or 0)
            last = row.get("last_played") or ""
            if lib is not None:
                lib["playtime"] = playtime
                lib["last"] = last
            for entry in self._cards:
                if entry[3] == game_id:
                    entry[0].set_playtime(playtime)
                    entry[0].setToolTip(self._card_tooltip(row))
                    break
            self._update_count()
            self._apply_sort()
        else:
            self._refresh_continue()
        self._schedule_sync()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._native_chrome_done and sys.platform == "win32":
            self._hwnd = int(self.winId())
            win32.enable_native_chrome(self._hwnd)
            win32.apply_dwm_preferences(self._hwnd)
            self._native_chrome_done = True
        if not self._hotkeys_applied:
            self._hotkeys_applied = True
            self._apply_hotkeys()

    def nativeEvent(self, eventType, message):
        if eventType in ("windows_generic_MSG", b"windows_generic_MSG") and self._hwnd:
            hwnd, msg_id, wparam, lparam = win32.parse_message(int(message))
            if hwnd == self._hwnd:
                if msg_id == win32.WM_NCCALCSIZE and wparam:
                    if win32.is_zoomed(self._hwnd):
                        win32.deflate_client_rect(lparam,
                                                  win32.resize_border_thickness())
                    return True, 0
                if msg_id == win32.WM_NCHITTEST:
                    return True, self._hit_test(lparam)
                if msg_id == win32.WM_NCACTIVATE:
                    win32.def_window_proc(self._hwnd, msg_id, wparam, -1)
                    return True, 1
        return super().nativeEvent(eventType, message)

    def _hit_test(self, lparam: int) -> int:
        x, y = win32.lparam_to_point(lparam)
        dpr = self.devicePixelRatioF() or 1.0
        local = self.mapFromGlobal(QPoint(round(x / dpr), round(y / dpr)))
        w, h = self.width(), self.height()
        if not (0 <= local.x() <= w and 0 <= local.y() <= h):
            return win32.HTCLIENT

        if not win32.is_zoomed(self._hwnd):
            margin = 8
            left, right = local.x() <= margin, local.x() >= w - margin
            top, bottom = local.y() <= margin, local.y() >= h - margin
            if top and left:    return win32.HTTOPLEFT
            if top and right:   return win32.HTTOPRIGHT
            if bottom and left: return win32.HTBOTTOMLEFT
            if bottom and right:return win32.HTBOTTOMRIGHT
            if left:  return win32.HTLEFT
            if right: return win32.HTRIGHT
            if top:   return win32.HTTOP
            if bottom:return win32.HTBOTTOM

        if local.y() <= self.TITLE_H:
            child = self.childAt(local)
            if child is None or not isinstance(child, (QPushButton, QLineEdit)):
                return win32.HTCAPTION
        return win32.HTCLIENT

    def _toggle_max(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def closeEvent(self, event) -> None:
        if os.environ.get("ORBIT_QA") != "1":
            self._exit_bomb = threading.Timer(
                3.0, os._exit, (0,))
            self._exit_bomb.daemon = True
            self._exit_bomb.start()
        self._shutting_down = True
        self._gamepad.stop()
        self._hotkeys.unregister()
        app = QApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self._hotkeys)
        self._sync_timer.stop()
        if self._quick.isVisible():
            self._quick.close()
        self._tray.hide()
        self._save_geometry()
        try:
            if self._settings.sync_auto and self._settings.sync_dir:
                self._run_sync(auto=True)
        except Exception:
            log.exception("Final sync failed")
        self._tracker.stop()
        self._riot_clicker.stop()
        self._client_guard.stop()
        self._rpc.shutdown()
        if hasattr(self, "_splash") and self._splash.isVisible():
            self._splash.close()
        if hasattr(self, "_worker") and hasattr(self, "_scan_thread"):
            self._worker.request_stop()
            if self._scan_thread.isRunning():
                self._scan_thread.quit()
                if not self._scan_thread.wait(3000):
                    log.warning("Scan thread did not stop within 3 s")
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            for widget in list(app.topLevelWidgets()):
                if widget is not self and widget.isVisible():
                    widget.close()
            QTimer.singleShot(0, app.quit)
