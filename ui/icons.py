from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF)

_DEFAULT = QColor("#D1D1D6")


def _empty(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _painter(pm: QPixmap) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return p


def _stroke_pen(color: QColor, s: float) -> QPen:
    pen = QPen(color, max(1.2, s * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def gear_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx = cy = s / 2.0
    r = s * 0.27
    import math
    teeth = 8
    for i in range(teeth):
        angle = math.radians(i * (360.0 / teeth))
        x1 = cx + math.cos(angle) * (r + s * 0.04)
        y1 = cy + math.sin(angle) * (r + s * 0.04)
        x2 = cx + math.cos(angle) * (r + s * 0.15)
        y2 = cy + math.sin(angle) * (r + s * 0.15)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.drawEllipse(QPointF(cx, cy), r * 0.36, r * 0.36)
    p.end()
    return QIcon(pm)


def refresh_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    margin = s * 0.18
    rect = QRectF(margin, margin, s - 2.0 * margin, s - 2.0 * margin)
    p.drawArc(rect, 40 * 16, 290 * 16)
    r = rect.width() / 2.0
    cx = cy = s / 2.0
    p.save()
    p.translate(cx + r * 0.94, cy)
    p.rotate(-60.0)
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([
        QPointF(0.0, -s * 0.02),
        QPointF(-s * 0.16, s * 0.10),
        QPointF(s * 0.02, s * 0.16),
    ]))
    p.restore()
    p.end()
    return QIcon(pm)


def plus_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.drawLine(QPointF(s * 0.5, s * 0.22), QPointF(s * 0.5, s * 0.78))
    p.drawLine(QPointF(s * 0.22, s * 0.5), QPointF(s * 0.78, s * 0.5))
    p.end()
    return QIcon(pm)


def image_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    frame = QRectF(s * 0.10, s * 0.18, s * 0.80, s * 0.64)
    p.drawRoundedRect(frame, s * 0.12, s * 0.12)
    p.drawEllipse(QPointF(s * 0.34, s * 0.38), s * 0.06, s * 0.06)
    path = QPainterPath()
    path.moveTo(s * 0.14, s * 0.76)
    path.lineTo(s * 0.38, s * 0.50)
    path.lineTo(s * 0.52, s * 0.64)
    path.lineTo(s * 0.66, s * 0.52)
    path.lineTo(s * 0.86, s * 0.76)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def play_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.32, s * 0.20),
        QPointF(s * 0.32, s * 0.80),
        QPointF(s * 0.80, s * 0.50),
    ]))
    p.end()
    return QIcon(pm)


def stop_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawRoundedRect(QRectF(s * 0.26, s * 0.26, s * 0.48, s * 0.48),
                      s * 0.10, s * 0.10)
    p.end()
    return QIcon(pm)


def search_pixmap(size: int = 15, color: QColor | None = None) -> QPixmap:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(s * 0.42, s * 0.42), s * 0.26, s * 0.26)
    p.drawLine(QPointF(s * 0.62, s * 0.62), QPointF(s * 0.82, s * 0.82))
    p.end()
    return pm


def search_icon(size: int = 15, color: QColor | None = None) -> QIcon:
    return QIcon(search_pixmap(size, color))


def x_icon(size: int = 12, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    inset = s * 0.24
    p.drawLine(QPointF(inset, inset), QPointF(s - inset, s - inset))
    p.drawLine(QPointF(s - inset, inset), QPointF(inset, s - inset))
    p.end()
    return QIcon(pm)


def trash_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.16, s * 0.26), QPointF(s * 0.84, s * 0.26))
    p.drawLine(QPointF(s * 0.40, s * 0.26), QPointF(s * 0.40, s * 0.18))
    p.drawLine(QPointF(s * 0.60, s * 0.26), QPointF(s * 0.60, s * 0.18))
    p.drawLine(QPointF(s * 0.40, s * 0.18), QPointF(s * 0.60, s * 0.18))
    p.drawRoundedRect(QRectF(s * 0.24, s * 0.26, s * 0.52, s * 0.58),
                      s * 0.08, s * 0.08)
    p.drawLine(QPointF(s * 0.41, s * 0.40), QPointF(s * 0.41, s * 0.70))
    p.drawLine(QPointF(s * 0.59, s * 0.40), QPointF(s * 0.59, s * 0.70))
    p.end()
    return QIcon(pm)


def sliders_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.18, s * 0.30), QPointF(s * 0.82, s * 0.30))
    p.drawLine(QPointF(s * 0.18, s * 0.50), QPointF(s * 0.82, s * 0.50))
    p.drawLine(QPointF(s * 0.18, s * 0.70), QPointF(s * 0.82, s * 0.70))
    for cx, cy in ((0.62, 0.30), (0.34, 0.50), (0.72, 0.70)):
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(s * cx, s * cy), s * 0.085, s * 0.085)
        p.setBrush(Qt.BrushStyle.NoBrush)
    p.end()
    return QIcon(pm)


def info_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72))
    dot = QPen(color, max(1.0, s * 0.10))
    dot.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(dot)
    p.drawPoint(QPointF(s * 0.5, s * 0.34))
    p.drawLine(QPointF(s * 0.5, s * 0.48), QPointF(s * 0.5, s * 0.68))
    p.end()
    return QIcon(pm)


def news_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(s * 0.14, s * 0.20, s * 0.72, s * 0.60),
                      s * 0.08, s * 0.08)
    p.drawLine(QPointF(s * 0.28, s * 0.36), QPointF(s * 0.50, s * 0.36))
    p.drawLine(QPointF(s * 0.28, s * 0.50), QPointF(s * 0.72, s * 0.50))
    p.drawLine(QPointF(s * 0.28, s * 0.64), QPointF(s * 0.72, s * 0.64))
    p.setBrush(QColor(color))
    p.drawRect(QRectF(s * 0.56, s * 0.32, s * 0.16, s * 0.10))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.end()
    return QIcon(pm)


def camera_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.28, s * 0.76, s * 0.50),
                      s * 0.10, s * 0.10)
    p.drawRoundedRect(QRectF(s * 0.34, s * 0.18, s * 0.24, s * 0.12),
                      s * 0.04, s * 0.04)
    p.drawEllipse(QPointF(s * 0.50, s * 0.53), s * 0.15, s * 0.15)
    p.end()
    return QIcon(pm)


def tag_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(s * 0.82, s * 0.44)
    path.lineTo(s * 0.82, s * 0.16)
    path.lineTo(s * 0.54, s * 0.16)
    path.lineTo(s * 0.16, s * 0.54)
    path.lineTo(s * 0.46, s * 0.84)
    path.lineTo(s * 0.82, s * 0.44)
    p.drawPath(path)
    p.drawEllipse(QPointF(s * 0.68, s * 0.30), s * 0.055, s * 0.055)
    p.end()
    return QIcon(pm)


def bolt_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.58, s * 0.12),
        QPointF(s * 0.28, s * 0.56),
        QPointF(s * 0.48, s * 0.56),
        QPointF(s * 0.40, s * 0.88),
        QPointF(s * 0.72, s * 0.42),
        QPointF(s * 0.52, s * 0.42),
    ]))
    p.end()
    return QIcon(pm)


def cloud_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(s * 0.24, s * 0.66)
    path.cubicTo(s * 0.06, s * 0.66, s * 0.10, s * 0.38, s * 0.30, s * 0.40)
    path.cubicTo(s * 0.32, s * 0.18, s * 0.62, s * 0.16, s * 0.68, s * 0.34)
    path.cubicTo(s * 0.92, s * 0.30, s * 0.98, s * 0.62, s * 0.76, s * 0.66)
    path.lineTo(s * 0.24, s * 0.66)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def flag_icon(size: int = 18, color: QColor | None = None) -> QIcon:
    color = color or QColor(_DEFAULT)
    s = float(size)
    pm = _empty(size)
    p = _painter(pm)
    p.setPen(_stroke_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(s * 0.30, s * 0.14), QPointF(s * 0.30, s * 0.88))
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([
        QPointF(s * 0.34, s * 0.20),
        QPointF(s * 0.80, s * 0.34),
        QPointF(s * 0.34, s * 0.50),
    ]))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.end()
    return QIcon(pm)