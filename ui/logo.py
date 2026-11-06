from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
_ASSET_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "assets" / "logo.png",
    Path(__file__).resolve().parent.parent / "logo.png",
)

_CACHE: dict[int, QPixmap] = {}


def _circle_fit(source: QPixmap, size: int) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    if source.isNull():
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(0.0, 0.0, float(size), float(size))
    painter.setClipPath(clip)
    scaled = source.scaled(size, size,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    dx = (scaled.width() - size) // 2
    dy = (scaled.height() - size) // 2
    painter.drawPixmap(-dx, -dy, scaled)
    painter.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    painter.end()
    return out


def draw_orbit_mark(painter: QPainter, size: float) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    cx = cy = size / 2.0
    R = size * 0.499

    disc_path = QPainterPath()
    disc_path.addEllipse(QPointF(cx, cy), R, R)

    space = QRadialGradient(cx - size * 0.12, cy - size * 0.16, R * 1.55)
    space.setColorAt(0.00, QColor("#262A33"))
    space.setColorAt(0.45, QColor("#12151D"))
    space.setColorAt(1.00, QColor("#040508"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(space))
    painter.drawPath(disc_path)

    painter.setClipPath(disc_path)
    sheen = QRadialGradient(cx - size * 0.22, cy - size * 0.30, R * 1.30)
    sheen.setColorAt(0.0, QColor(255, 255, 255, 16))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(QBrush(sheen))
    painter.drawRect(QRectF(0, 0, size, size))

    stars = ((0.285, 0.300, 0.0115, 120), (0.665, 0.215, 0.0085, 95),
             (0.760, 0.585, 0.0105, 85), (0.245, 0.640, 0.0075, 75),
             (0.585, 0.760, 0.0065, 65))
    for fx, fy, fr, fa in stars:
        painter.setBrush(QColor(255, 255, 255, fa))
        painter.drawEllipse(QPointF(size * fx, size * fy), size * fr, size * fr)

    rx, ry = size * 0.400, size * 0.155
    ring_pen_w = max(1.25, size * 0.046)
    ring_grad = QLinearGradient(cx - rx, cy - ry, cx + rx, cy + ry)
    ring_grad.setColorAt(0.00, QColor(255, 255, 255, 235))
    ring_grad.setColorAt(0.55, QColor(214, 220, 231, 120))
    ring_grad.setColorAt(1.00, QColor(255, 255, 255, 190))
    ring_pen = QPen(QBrush(ring_grad), ring_pen_w)
    ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

    painter.save()
    painter.translate(cx, cy)
    painter.rotate(-24.0)
    painter.translate(-cx, -cy)
    painter.setPen(ring_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), rx, ry)
    painter.restore()

    mr = size * 0.300
    mcx, mcy = cx - size * 0.015, cy + size * 0.012
    glow = QRadialGradient(mcx, mcy, mr * 1.95)
    glow.setColorAt(0.00, QColor(255, 255, 255, 74))
    glow.setColorAt(0.55, QColor(255, 255, 255, 20))
    glow.setColorAt(1.00, QColor(255, 255, 255, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(QPointF(mcx, mcy), mr * 1.95, mr * 1.95)

    bite = QPainterPath()
    bite.addEllipse(QPointF(mcx + mr * 0.62, mcy - mr * 0.52),
                    mr * 0.96, mr * 0.96)
    body = QPainterPath()
    body.addEllipse(QPointF(mcx, mcy), mr, mr)
    crescent = body.subtracted(bite)

    moon_grad = QLinearGradient(mcx - mr, mcy - mr, mcx + mr * 0.7, mcy + mr)
    moon_grad.setColorAt(0.00, QColor("#FFFFFF"))
    moon_grad.setColorAt(0.55, QColor("#D8DCE4"))
    moon_grad.setColorAt(1.00, QColor("#9BA1AE"))
    painter.setPen(QPen(QColor(255, 255, 255, 60), max(1.0, size * 0.004)))
    painter.setBrush(QBrush(moon_grad))
    painter.drawPath(crescent)

    painter.save()
    painter.setClipPath(crescent)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(120, 127, 142, 70))
    painter.drawEllipse(QPointF(mcx - mr * 0.42, mcy + mr * 0.18),
                        mr * 0.155, mr * 0.155)
    painter.drawEllipse(QPointF(mcx - mr * 0.05, mcy + mr * 0.55),
                        mr * 0.105, mr * 0.105)
    painter.drawEllipse(QPointF(mcx + mr * 0.34, mcy + mr * 0.02),
                        mr * 0.075, mr * 0.075)
    painter.restore()

    painter.save()
    painter.translate(cx, cy)
    painter.rotate(-24.0)
    painter.translate(-cx, -cy)
    pad = ring_pen_w
    front = QPainterPath()
    front.moveTo(cx - rx - pad, cy)
    front.lineTo(cx + rx + pad, cy)
    front.lineTo(cx + rx + pad, cy + ry + pad * 2)
    front.lineTo(cx - rx - pad, cy + ry + pad * 2)
    front.closeSubpath()
    painter.setClipPath(front)
    painter.setPen(ring_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), rx, ry)
    painter.restore()

    t = math.radians(42.0)
    ex = rx * math.cos(t)
    ey = ry * math.sin(t)
    tr = math.radians(-24.0)
    mx = ex * math.cos(tr) - ey * math.sin(tr)
    my = ex * math.sin(tr) + ey * math.cos(tr)
    sx, sy = cx + mx, cy + my
    sat_r = size * 0.052
    sat_glow = QRadialGradient(sx, sy, sat_r * 3.4)
    sat_glow.setColorAt(0.00, QColor(255, 255, 255, 120))
    sat_glow.setColorAt(1.00, QColor(255, 255, 255, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(sat_glow))
    painter.drawEllipse(QPointF(sx, sy), sat_r * 3.4, sat_r * 3.4)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(QPointF(sx, sy), sat_r, sat_r)

    painter.setClipping(False)
    rim_w = max(1.0, size * 0.0065)
    painter.setPen(QPen(QColor(255, 255, 255, 84), rim_w))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), R - rim_w * 0.5, R - rim_w * 0.5)
    arc_w = max(1.2, size * 0.011)
    arc_pen = QPen(QColor(255, 255, 255, 120), arc_w)
    arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(arc_pen)
    span_arc = QRectF(cx - (R - arc_w), cy - (R - arc_w),
                      (R - arc_w) * 2, (R - arc_w) * 2)
    painter.drawArc(span_arc, 115 * 16, 75 * 16)
    painter.restore()


def _vector_logo(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_orbit_mark(painter, float(size))
    painter.end()
    return pixmap


def logo_pixmap(size: int = 22) -> QPixmap:
    size = max(8, int(size))
    if size in _CACHE:
        return _CACHE[size]

    for candidate in _ASSET_CANDIDATES:
        if candidate.is_file():
            art = QPixmap(str(candidate))
            if not art.isNull():
                scaled = _circle_fit(art, size)
                _CACHE[size] = scaled
                return scaled

    pixmap = _vector_logo(size)
    _CACHE[size] = pixmap
    return pixmap


def logo_splash_pixmap(size: int = 96) -> QPixmap:
    out = QPixmap(size, int(size * 1.34))
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    logo = logo_pixmap(size)
    lx = (size - logo.width()) // 2
    painter.drawPixmap(lx, 0, logo)

    font_title = QFont("Segoe UI Semibold", max(9, int(size * 0.11)))
    font_title.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.030)
    painter.setFont(font_title)
    painter.setPen(QColor("#F5F6F8"))
    title_rect = QRectF(0, float(size) + 8, float(size), size * 0.20)
    painter.drawText(title_rect,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                     "ORBIT")

    font_sub = QFont("Segoe UI", max(7, int(size * 0.08)))
    font_sub.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.050)
    painter.setFont(font_sub)
    painter.setPen(QColor("#A8ABB8"))
    sub_rect = QRectF(0, float(size) + 8 + size * 0.22, float(size), size * 0.18)
    painter.drawText(sub_rect,
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                     "LAUNCHER")

    painter.end()
    return out


def app_icon() -> QIcon:
    return QIcon(logo_pixmap(64))
