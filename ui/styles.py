from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QAction, QBrush, QColor, QFont,
                           QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QWidget)

from ui import icons
from ui.logo import logo_pixmap

ACCENT = "#F2F4F8"
ACCENT_HOVER = "#FFFFFF"
ACCENT_PRESSED = "#C9CEDA"
ON_ACCENT = "#0A0D14"
TEXT_PRIMARY = "#F5F6F8"
TEXT_SECONDARY = "#A8ABB8"
TEXT_MUTED = "#6C6F7C"
SURFACE = "#0D1220"
SURFACE_RAISED = "#111830"
HAIRLINE = "rgba(255,255,255,0.09)"

SOURCE_LABELS = {
    "steam": "Steam", "epic": "Epic Games", "ea": "EA App",
    "ubisoft": "Ubisoft Connect", "gog": "GOG Galaxy", "generic": "Other",
    "riot": "Riot Games", "rockstar": "Rockstar Games",
    "battlenet": "Battle.net", "minecraft": "Minecraft",
    "bethesda": "Bethesda", "manual": "Manual Add",
    "roblox": "Roblox", "itch": "itch.io",
    "amazon": "Amazon Games", "hoyo": "HoYoPlay",
}

class GlassBackdrop(QWidget):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._custom: QPixmap | None = None
        self._cache: QPixmap | None = None
        self._load_custom()

    def _load_custom(self) -> None:
        from ui.background_manager import background_path
        path = background_path()
        pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
        self._custom = None if pixmap.isNull() else pixmap
        self._cache = None
        self.update()

    def reload_custom(self) -> None:
        self._load_custom()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._cache = None

    def _blob(self, painter: QPainter, rect: QRectF, cx: float, cy: float,
              radius: float, color: QColor) -> None:
        grad = QRadialGradient(cx, cy, radius)
        grad.setColorAt(0.0, color)
        grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
        painter.fillRect(rect, grad)

    def _render_cache(self) -> None:
        dpr = max(1.0, self.devicePixelRatioF() or 1.0)
        pw = max(1, int(self.width() * dpr))
        ph = max(1, int(self.height() * dpr))
        pixmap = QPixmap(pw, ph)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        span = max(pw, ph)
        target = QRectF(0.0, 0.0, float(pw), float(ph))
        art = self._custom
        if art is not None:
            scaled = art.scaled(
                QSize(pw, ph), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            dx = max(0, (scaled.width() - pw) // 2)
            dy = max(0, (scaled.height() - ph) // 2)
            painter.drawPixmap(-dx, -dy, scaled)
            painter.fillRect(pixmap.rect(), QColor(7, 11, 22, 182))
            self._blob(painter, target, pw * 0.12, ph * -0.05, span * 0.62,
                       QColor(34, 211, 238, 52))
            self._blob(painter, target, pw * 0.98, ph * 0.36, span * 0.58,
                       QColor(139, 92, 246, 50))
            self._blob(painter, target, pw * 0.10, ph * 1.05, span * 0.60,
                       QColor(236, 72, 153, 38))
            self._blob(painter, target, pw * 0.72, ph * -0.10, span * 0.48,
                       QColor(99, 102, 241, 34))
            self._blob(painter, target, pw * 0.50, ph * 1.12, span * 0.42,
                       QColor(34, 211, 238, 22))
            sheen = QRadialGradient(pw * 0.50, ph * -0.14, pw * 0.72)
            sheen.setColorAt(0.0, QColor(255, 255, 255, 10))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(pixmap.rect(), sheen)
        else:
            painter.fillRect(pixmap.rect(), QColor(0, 0, 0))
        painter.end()
        pixmap.setDevicePixelRatio(dpr)
        self._cache = pixmap

    def paintEvent(self, event) -> None:
        dpr = max(1.0, self.devicePixelRatioF() or 1.0)
        pw = max(1, int(self.width() * dpr))
        ph = max(1, int(self.height() * dpr))
        if (self._cache is None or self._cache.width() != pw
                or self._cache.height() != ph
                or abs(self._cache.devicePixelRatio() - dpr) > 0.01):
            self._render_cache()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)
        painter.end()

class _CaptionButton(QPushButton):

    def __init__(self, kind: str, on_click, danger: bool,
                 parent: QWidget) -> None:
        super().__init__(parent)
        self._kind = kind
        self._danger = danger
        self.setFixedSize(42, 30)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(on_click)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        hovered = self.underMouse()
        pressed = self.isDown()

        if hovered or pressed:
            if self._danger:
                fill = QColor("#E81123") if hovered else QColor(232, 17, 35, 190)
            else:
                fill = QColor(255, 255, 255, 44 if pressed else 30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 9, 9)

        color = QColor("#FFFFFF") if hovered else QColor("#C4C7D1")
        pen = QPen(color, 1.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = w / 2.0, h / 2.0
        if self._kind == "min":
            painter.drawLine(QPointF(cx - 4.5, cy), QPointF(cx + 4.5, cy))
        elif self._kind == "max":
            painter.drawRoundedRect(QRectF(cx - 4.0, cy - 4.0, 8.0, 8.0),
                                    2.0, 2.0)
        else:
            painter.drawLine(QPointF(cx - 3.7, cy - 3.7),
                             QPointF(cx + 3.7, cy + 3.7))
            painter.drawLine(QPointF(cx + 3.7, cy - 3.7),
                             QPointF(cx - 3.7, cy + 3.7))

class SearchField(QFrame):

    def __init__(self, placeholder: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SearchField")
        self.setFixedSize(320, 40)
        self._focused = False

        self.edit = QLineEdit(self)
        self.edit.setObjectName("SearchInput")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrame(False)
        self.edit.setTextMargins(0, 0, 22, 0)
        self.edit.installEventFilter(self)
        self.edit.textChanged.connect(self._sync)

        self._clear_btn = QLabel(self.edit)
        self._clear_btn.setPixmap(icons.x_icon(12).pixmap(12, 12))
        self._clear_btn.setFixedSize(18, 18)
        self._clear_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setToolTip("Clear search")
        self._clear_btn.setVisible(False)
        self._clear_btn.installEventFilter(self)

        row = QHBoxLayout(self)
        row.setContentsMargins(15, 0, 12, 0)
        row.setSpacing(8)
        glass = QLabel()
        glass.setPixmap(icons.search_icon(15).pixmap(15, 15))
        glass.setFixedSize(15, 15)
        row.addWidget(glass)
        row.addWidget(self.edit, 1)
        self._hint_ctrl = QLabel("Ctrl", objectName="KbdChip")
        self._hint_key = QLabel("F", objectName="KbdChip")
        self._hint_ctrl.setFixedHeight(18)
        self._hint_key.setFixedHeight(18)
        row.addWidget(self._hint_ctrl)
        row.addWidget(self._hint_key)
        self._sync()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.edit:
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self._focused = event.type() == QEvent.Type.FocusIn
                self._sync()
            elif event.type() == QEvent.Type.Resize:
                self._place_clear()
        elif obj is self._clear_btn and event.type() == QEvent.Type.MouseButtonPress:
            self.edit.clear()
            return True
        return super().eventFilter(obj, event)

    def _place_clear(self) -> None:
        y = (self.height() - 18) // 2 - self.edit.y()
        self._clear_btn.move(self.edit.width() - 22, y)

    def _sync(self) -> None:
        has_text = bool(self.edit.text())
        if has_text:
            self._place_clear()
        self._clear_btn.setVisible(has_text)
        quiet = not (self._focused or has_text)
        self._hint_ctrl.setVisible(quiet)
        self._hint_key.setVisible(quiet)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        if self._focused:
            glow = QPen(QColor(255, 255, 255, 30), 3.0)
            painter.setPen(glow)
            painter.drawPath(path)
            painter.fillPath(path, QColor(255, 255, 255, 24))
            painter.setPen(QPen(QColor(255, 255, 255, 138), 1.2))
        else:
            painter.fillPath(path, QColor(255, 255, 255, 13))
            painter.setPen(QPen(QColor(255, 255, 255, 32), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

class GlassTitleBar(QWidget):
    def __init__(self, on_min, on_max, on_close, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(8)

        mark = QLabel()
        mark.setPixmap(logo_pixmap(24))
        mark.setFixedSize(24, 24)
        layout.addWidget(mark)

        name = QLabel("ORBIT")
        name.setObjectName("BrandMark")
        layout.addWidget(name)

        layout.addStretch(1)

        layout.addWidget(_CaptionButton("min", on_min, False, self))
        layout.addWidget(_CaptionButton("max", on_max, False, self))
        layout.addWidget(_CaptionButton("close", on_close, True, self))

APP_QSS = """
* { outline: none; font-family: "Segoe UI Variable Display", "Segoe UI",
    "Helvetica Neue", Arial; }
QMainWindow { background: #000000; }

#TitleBar { background: transparent;
            border-bottom: 1px solid rgba(255,255,255,0.06); }
#BrandMark { color: #F5F6F8; font-size: 10.5pt; font-weight: 700;
             letter-spacing: 4px; }

#SectionLabel { color: #6C6F7C; font-size: 8.5pt; font-weight: 600;
                letter-spacing: 2.5px; }
#StatsChip    { color: #C9CBD4; background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.10); border-radius: 14px;
                padding: 6px 14px; font-size: 8.5pt; font-weight: 600;
                letter-spacing: 1px; }

#Toast        { background: rgba(18,20,27,0.96);
                border: 1px solid rgba(255,255,255,0.16); border-radius: 19px; }
#ToastText    { color: #E8EAF0; font-size: 9pt; font-weight: 600; }

#EmptyState   { background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; }
#EmptyTitle   { color: #F5F6F8; font-size: 12pt; font-weight: 700; }
#EmptySub     { color: #8A8D98; font-size: 9pt; }
#EmptyPrimary { background: #F2F4F8; color: #0A0D14; border: none;
                border-radius: 15px; padding: 8px 20px;
                font-size: 9.5pt; font-weight: 700; }
#EmptyPrimary:hover { background: #FFFFFF; }
#EmptyGhost   { background: rgba(255,255,255,0.07); color: #D8DAE2;
                border: 1px solid rgba(255,255,255,0.13); border-radius: 15px;
                padding: 8px 20px; font-size: 9.5pt; font-weight: 600; }
#EmptyGhost:hover { background: rgba(255,255,255,0.13);
                border-color: rgba(255,255,255,0.32); }
#MiniTile     { background: transparent; border: none; }

QComboBox { background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.11); border-radius: 14px;
            padding: 7px 14px; color: #F5F6F8; font-size: 9pt;
            min-width: 150px; }
QComboBox:hover { border-color: rgba(255,255,255,0.42); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; border-left: 4px solid transparent;
                        border-right: 4px solid transparent;
                        border-top: 5px solid #C4C7D1; margin-right: 8px; }
QComboBox QAbstractItemView { background: #15171E;
    border: 1px solid rgba(255,255,255,0.14); border-radius: 12px;
    selection-background-color: rgba(255,255,255,0.16);
    selection-color: #F5F6F8; color: #D8DAE2; outline: none; padding: 4px; }
QComboBox QAbstractItemView::item { min-height: 26px; border-radius: 8px;
                                    padding: 2px 8px; }

#NavButton { text-align: center; color: #A8ABB8; background: transparent;
             border: 1px solid rgba(255,255,255,0.10); border-radius: 14px;
             padding: 7px 22px; font-size: 9.5pt; font-weight: 500; }
#NavButton:hover   { background: rgba(255,255,255,0.08); color: #F5F6F8; }
#NavButton:checked { background: #F2F4F8; border: 1px solid #F2F4F8;
                     color: #0A0D14; font-weight: 600; }

#SearchField { background: transparent; border: none; }
#SearchInput { background: transparent; border: none; color: #F5F6F8;
               font-size: 9.5pt;
               selection-background-color: rgba(255,255,255,0.35); }
#KbdChip  { color: #9A9DA9; background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.15); border-radius: 5px;
            padding: 1px 6px; font-size: 7.5pt; font-weight: 600; }
#CountLabel { color: #6C6F7C; font-size: 9pt; }

#WinButton { background: rgba(255,255,255,0.05); color: #D9DBE3;
             border: 1px solid rgba(255,255,255,0.11); border-radius: 19px; }
#WinButton:hover  { background: rgba(255,255,255,0.13);
                    border-color: rgba(255,255,255,0.40); color: #FFFFFF; }
#WinButton:pressed { background: rgba(255,255,255,0.07);
                     border-color: rgba(255,255,255,0.16); }

QScrollArea { background: transparent; border: none; }
#GridCanvas { background: transparent; }

#GameCard { background: transparent; border: none; }
#CardTitle { color: #F5F6F8; font-size: 9.5pt; font-weight: 600;
             font-family: "Segoe UI Semibold", "Segoe UI"; }
#CardMeta  { color: #9A9DA9; font-size: 8pt; }

#CardPlayBtn { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
               stop:0 #FFFFFF, stop:1 #D9DDE6); color: #0A0D14; border: none;
               border-radius: 15px; padding: 4px 12px;
               font-size: 8.5pt; font-weight: 800; letter-spacing: 1.5px; }
#CardPlayBtn:hover  { background: #FFFFFF; }
#CardPlayBtn:pressed{ background: #BFC4CF; }
#CardStopBtn { background: rgba(255,255,255,0.10); color: #F2F4F8;
               border: 1px solid rgba(255,255,255,0.42); border-radius: 15px;
               padding: 3px 12px; font-size: 8.5pt; font-weight: 700;
               letter-spacing: 1.5px; }
#CardStopBtn:hover  { background: rgba(255,255,255,0.20);
                      border-color: rgba(255,255,255,0.72); }
#CardStopBtn:pressed{ background: rgba(255,255,255,0.30); }
#CardRemoveBtn { background: rgba(255,255,255,0.07); color: #A8ABB8;
                 border: 1px solid rgba(255,255,255,0.13); border-radius: 15px; }
#CardRemoveBtn:hover  { background: rgba(255,255,255,0.16);
                        border-color: rgba(255,255,255,0.34); }
#CardRemoveBtn:pressed{ background: rgba(255,255,255,0.26); }

QScrollBar:vertical { background: transparent; width: 9px; margin: 6px 3px 6px 0; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.11);
                              border-radius: 4px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.45);
                                    border-radius: 4px; }
QScrollBar::handle:vertical:pressed { background: rgba(255,255,255,0.70); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

#LoadingBrand { color: #F5F6F8; font-size: 14pt; font-weight: 700;
                letter-spacing: 8px; }
#LoadingStatus { color: #A8ABB8; font-size: 9pt; }
#LoadingCredit { color: #454854; font-size: 7.5pt; letter-spacing: 2px; }

QToolTip { background: #14161D; color: #F5F6F8;
           border: 1px solid rgba(255,255,255,0.28); padding: 6px 10px;
           border-radius: 10px; }

#QuickPanel { background: rgba(14,16,23,0.97);
              border: 1px solid rgba(255,255,255,0.14); border-radius: 18px; }
#QuickInput { background: transparent; border: none; color: #F5F6F8;
              font-size: 12pt;
              selection-background-color: rgba(255,255,255,0.35); }
#QuickInput::placeholder { color: #6C6F7C; }
#QuickRow   { background: transparent; border: none; border-radius: 12px; }
#QuickRow:hover { background: rgba(255,255,255,0.06); }
#QuickRowSel { background: rgba(255,255,255,0.10);
               border: 1px solid rgba(255,255,255,0.22); border-radius: 12px; }
#QuickTitle { color: #F5F6F8; font-size: 10.5pt; font-weight: 600; }
#QuickMeta  { color: #8A8D98; font-size: 8.5pt; }
#QuickEmpty { color: #6C6F7C; font-size: 9.5pt; }
"""

def apply_app_style(app: QApplication) -> None:
    app.setStyle("Fusion")
    if sys.platform == "win32":
        font = QFont()
        font.setFamilies(["Segoe UI Variable Display", "Segoe UI",
                          "Helvetica Neue", "Arial"])
        font.setPointSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        app.setFont(font)
    app.setStyleSheet(APP_QSS)
