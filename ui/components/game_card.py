from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import quote, urlparse

from PySide6.QtCore import (QStandardPaths, QEasingCurve, QRectF,
                            QPointF, QSize, Qt, QTimer, QUrl,
                            QPropertyAnimation, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect,
                               QLabel, QPushButton, QWidget)

from ui import icons
from ui.smooth_scroll import scroll_is_active
from ui.styles import SOURCE_LABELS

log = logging.getLogger(__name__)

_NETWORK: QNetworkAccessManager | None = None
_REPLIES: set[QNetworkReply] = set()

_TRANSFER_TIMEOUT_MS = 15_000
_MAX_IMAGE_BYTES = 30 * 1024 * 1024
_MAX_HTML_BYTES = 2 * 1024 * 1024

_OG_IMAGE_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']og:image(?::secure_url)?[\"'][^>]*"
    r"content=[\"']([^\"']+)[\"']", re.IGNORECASE)
_OG_IMAGE_RE_ALT = re.compile(
    r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*"
    r"(?:property|name)=[\"']og:image[\"']", re.IGNORECASE)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_WEBP_MAGIC = b"RIFF"
_GIF_MAGIC = b"GIF8"

_MAX_PIXELS = 40_000_000

_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home",
                     ".corp", ".localdomain", ".localhost")

def _image_url_ok(url: str) -> bool:
    try:
        parts = urlparse(str(url))
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    if parts.username or parts.password or parts.port not in (None, 443):
        return False
    host = parts.hostname.casefold().rstrip(".")
    if not host or host == "localhost" or host.endswith(_PRIVATE_SUFFIXES):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return not host.startswith("127.")
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)

def _looks_like_image(data: bytes, ctype: str) -> bool:
    if data[:8] == _PNG_MAGIC or data[:3] == _JPEG_MAGIC:
        return True
    if data[:4] == _WEBP_MAGIC and data[8:12] == b"WEBP":
        return True
    if data[:4] == _GIF_MAGIC:
        return True
    return ctype.casefold().strip().startswith("image/")

_STEAM_SEARCH_URL = ("https://store.steampowered.com/api/storesearch/"
                     "?term={term}&l=english&cc=US")

_ROBLOX_COVER = "https://i.postimg.cc/jjMgCYG2/3fd94f4396a61a3b603a085e17bd2262.jpg"

def _network() -> QNetworkAccessManager:
    global _NETWORK
    if _NETWORK is None:
        _NETWORK = QNetworkAccessManager()
    return _NETWORK

def _cache_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    path = Path(base) / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path

def _first_og_image(html: str) -> str | None:
    match = _OG_IMAGE_RE.search(html) or _OG_IMAGE_RE_ALT.search(html)
    if not match:
        return None
    url = match.group(1).replace("&amp;", "&")
    return url if url.startswith("https://") else None

def load_remote_image(urls: Sequence[str], on_ready: Callable[[str | None], None]) -> None:
    queue = [u for u in urls if u and _image_url_ok(str(u))]

    def attempt(index: int, hops: int = 0) -> None:
        if index >= len(queue):
            on_ready(None)
            return
        url = queue[index]
        path = _cache_dir() / f"{hashlib.sha1(url.encode()).hexdigest()[:24]}.img"

        if path.is_file():
            if path.read_bytes()[:1] == b"<":
                og = _first_og_image(path.read_text(encoding="utf-8",
                                                    errors="replace")[:_MAX_HTML_BYTES])
                if og and og != url and hops < 2 and _image_url_ok(og):
                    queue[index] = og
                    attempt(index, hops + 1)
                    return
                attempt(index + 1)
                return
            on_ready(str(path))
            return

        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = _network().get(request)

        def _on_progress(received: int, _total: int) -> None:
            if received > _MAX_IMAGE_BYTES:
                reply.abort()

        reply.downloadProgress.connect(_on_progress)

        def _done() -> None:
            _REPLIES.discard(reply)
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                attempt(index + 1)
                return
            data = bytes(reply.readAll())
            if not data or len(data) > _MAX_IMAGE_BYTES:
                attempt(index + 1)
                return
            ctype = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
            try:
                path.write_bytes(data)
            except OSError:
                pass
            if "text/html" in ctype or data[:1] == b"<":
                og = _first_og_image(data[:_MAX_HTML_BYTES].decode("utf-8",
                                                                   errors="replace"))
                if og and og != url and hops < 2 and _image_url_ok(og):
                    queue[index] = og
                    attempt(index, hops + 1)
                else:
                    attempt(index + 1)
                return
            if _looks_like_image(data, ctype):
                on_ready(str(path))
            else:
                attempt(index + 1)

        reply.finished.connect(_done)
        _REPLIES.add(reply)

    attempt(0)

def rounded_pixmap(src: QPixmap, size: QSize, radius: int,
                   dpr: float = 1.0, anchor: float = 0.5) -> QPixmap:
    dpr = max(1.0, float(dpr or 1.0))
    pw = max(1, int(round(size.width() * dpr)))
    ph = max(1, int(round(size.height() * dpr)))
    out = QPixmap(pw, ph)
    out.fill(Qt.GlobalColor.transparent)
    if src.isNull():
        out.setDevicePixelRatio(dpr)
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(pw), float(ph),
                        float(radius * dpr), float(radius * dpr))
    painter.setClipPath(clip)
    scaled = src.scaled(QSize(pw, ph),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    dx = max(0, (scaled.width() - pw) // 2)
    overflow = max(0, scaled.height() - ph)
    dy = int(round(overflow * min(max(anchor, 0.0), 1.0)))
    painter.drawPixmap(-dx, -dy, scaled)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(ph))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, pw, ph, sheen)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out

def full_art_tile_pixmap(src: QPixmap, size_px: int, radius: int,
                         dpr: float = 1.0) -> QPixmap:
    dpr = max(1.0, float(dpr or 1.0))
    pw = max(1, int(round(size_px * dpr)))
    out = QPixmap(pw, pw)
    out.fill(Qt.GlobalColor.transparent)
    if src.isNull():
        out.setDevicePixelRatio(dpr)
        return out
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(pw), float(pw),
                        float(radius * dpr), float(radius * dpr))
    painter.setClipPath(clip)
    tiny = src.scaled(QSize(max(12, pw // 10), max(12, pw // 10)),
                      Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                      Qt.TransformationMode.FastTransformation)
    painter.drawPixmap(QRectF(0.0, 0.0, float(pw), float(pw)), tiny,
                       QRectF(0.0, 0.0, float(tiny.width()),
                              float(tiny.height())))
    painter.fillRect(0, 0, pw, pw, QColor(6, 8, 13, 148))
    fit = src.scaled(QSize(pw, pw),
                     Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap((pw - fit.width()) // 2, (pw - fit.height()) // 2, fit)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(pw))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 22))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, pw, pw, sheen)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out

def load_cover_pixmap(path: str, target_px: QSize) -> QPixmap:
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        native = reader.size()
        if (native.isValid() and native.width() > 0 and native.height() > 0
                and (native.width() > target_px.width()
                     or native.height() > target_px.height())):
            reader.setScaledSize(native.scaled(
                target_px, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
        image = reader.read()
        if image.isNull():
            return QPixmap(path)
        return QPixmap.fromImage(image)
    except Exception:
        log.debug("Cover decode failed for %s", path, exc_info=True)
        return QPixmap()

_MC_ROWS = (
    "GGGGGGGG",
    "GgGGgGGG",
    "DdDGDdDD",
    "DDdDDDdD",
    "dDDdDDDD",
    "EDDdDDdD",
    "DdEDdDDD",
    "DDDdDEDD",
)
_MC_PALETTE = {
    "G": "#8CCB5A", "g": "#6AAD3D", "D": "#8B5A2B",
    "d": "#79502A", "E": "#9C6B3A",
}

def minecraft_tile_pixmap(size: QSize, radius: int, dpr: float = 1.0) -> QPixmap:
    dpr = max(1.0, float(dpr or 1.0))
    pw = max(1, int(round(size.width() * dpr)))
    ph = max(1, int(round(size.height() * dpr)))
    out = QPixmap(pw, ph)
    out.fill(Qt.GlobalColor.transparent)
    cell = QPixmap(8, 8)
    painter = QPainter(cell)
    for y, row in enumerate(_MC_ROWS):
        for x, ch in enumerate(row):
            painter.fillRect(x, y, 1, 1, QColor(_MC_PALETTE[ch]))
    painter.end()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(pw), float(ph),
                        float(radius * dpr), float(radius * dpr))
    painter.setClipPath(clip)
    scaled = cell.scaled(QSize(pw, ph),
                         Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.FastTransformation)
    painter.drawPixmap(0, 0, scaled)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(ph))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 26))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, pw, ph, sheen)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out

def roblox_tile_pixmap(size: QSize, radius: int, dpr: float = 1.0) -> QPixmap:
    dpr = max(1.0, float(dpr or 1.0))
    pw = max(1, int(round(size.width() * dpr)))
    ph = max(1, int(round(size.height() * dpr)))
    out = QPixmap(pw, ph)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(pw), float(ph),
                        float(radius * dpr), float(radius * dpr))
    painter.setClipPath(clip)

    base = QLinearGradient(0.0, 0.0, 0.0, float(ph))
    base.setColorAt(0.0, QColor("#232326"))
    base.setColorAt(1.0, QColor("#0D0D10"))
    painter.fillRect(out.rect(), base)

    sq = min(pw, ph) * 0.44
    sx = (pw - sq) / 2.0
    sy = (ph - sq) / 2.0 - ph * 0.04
    tilt = sq * 0.24

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#F5F5F7"))

    p1 = QPolygonF([
        QPointF(sx + tilt, sy),
        QPointF(sx + sq, sy),
        QPointF(sx + sq - tilt, sy + tilt),
        QPointF(sx, sy + tilt),
    ])
    painter.drawPolygon(p1)

    p2 = QPolygonF([
        QPointF(sx, sy + tilt),
        QPointF(sx + sq - tilt, sy + tilt),
        QPointF(sx + sq - sq * 0.18, sy + sq * 0.30),
        QPointF(sx + sq * 0.18, sy + sq * 0.30),
    ])
    painter.drawPolygon(p2)

    font = QFont("Segoe UI Black", max(10, int(sq * 0.32)), 700)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#E2231A"))
    painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, "R")

    sheen = QLinearGradient(0.0, 0.0, 0.0, float(ph))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, pw, ph, sheen)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out

_GRADIENTS = [("#3B2228", "#1C1418"), ("#312028", "#180F15"), ("#28202C", "#130F16"),
              ("#332430", "#191218"), ("#2A2230", "#141019"), ("#26222E", "#121018")]

def placeholder_pixmap(title: str, size: QSize, radius: int,
                       dpr: float = 1.0) -> QPixmap:
    dpr = max(1.0, float(dpr or 1.0))
    pw = max(1, int(round(size.width() * dpr)))
    ph = max(1, int(round(size.height() * dpr)))
    out = QPixmap(pw, ph)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0.0, 0.0, float(pw), float(ph),
                        float(radius * dpr), float(radius * dpr))
    painter.setClipPath(clip)
    seed = int(hashlib.sha1(title.encode()).hexdigest(), 16) % len(_GRADIENTS)
    top, bottom = _GRADIENTS[seed]
    grad = QLinearGradient(0.0, 0.0, 0.0, float(ph))
    grad.setColorAt(0.0, QColor(top))
    grad.setColorAt(1.0, QColor(bottom))
    painter.fillRect(out.rect(), grad)
    initials = "".join(w[0] for w in title.split()[:2]).upper() or (title[:1] or "?")
    painter.setPen(QColor(245, 245, 247, 200))
    font = QFont("Segoe UI Semibold", max(20, int(28 * dpr)))
    painter.setFont(font)
    painter.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, initials)
    sheen = QLinearGradient(0.0, 0.0, 0.0, float(ph))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
    sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
    painter.fillRect(0, 0, pw, ph, sheen)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out

class _TileOverlay(QWidget):

    def __init__(self, card: "GameCard") -> None:
        super().__init__(card)
        self._card = card
        self._reveal = 0.0
        self._running = False
        self._buttons_shown = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._play_btn = QPushButton("PLAY", self)
        self._play_btn.setObjectName("CardPlayBtn")
        self._play_btn.setIcon(icons.play_icon(11, QColor("#0A0D14")))
        self._play_btn.setIconSize(QSize(11, 11))
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setFixedHeight(30)
        self._play_btn.clicked.connect(
            lambda: card.play_clicked.emit(card.game_id))

        self._stop_btn = QPushButton("STOP", self)
        self._stop_btn.setObjectName("CardStopBtn")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setFixedHeight(30)
        self._stop_btn.setToolTip("Force-close this game")
        self._stop_btn.clicked.connect(
            lambda: card.stop_clicked.emit(card.game_id))
        self._stop_btn.hide()

        self._remove_btn = QPushButton(self)
        self._remove_btn.setObjectName("CardRemoveBtn")
        self._remove_btn.setIcon(icons.trash_icon(13))
        self._remove_btn.setIconSize(QSize(13, 13))
        self._remove_btn.setFixedSize(30, 30)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setToolTip("Remove from library")
        self._remove_btn.clicked.connect(
            lambda: card.remove_clicked.emit(card.game_id))

        self.setVisible(False)

    def set_running(self, running: bool) -> None:
        self._running = bool(running)
        self._refresh_buttons()

    def set_reveal(self, value: float) -> None:
        self._reveal = max(0.0, min(1.0, float(value)))
        self._refresh_buttons()
        self.update()

    def _refresh_buttons(self) -> None:
        show = self._reveal > 0.35
        self._buttons_shown = show
        self._play_btn.setVisible(show and not self._running)
        self._stop_btn.setVisible(show and self._running)
        self._remove_btn.setVisible(show)

    def _place(self) -> None:
        w, h = self.width(), self.height()
        y = h - 40
        self._play_btn.setGeometry(10, y, 92, 30)
        self._stop_btn.setGeometry(10, y, 92, 30)
        self._remove_btn.setGeometry(w - 40, y, 30, 30)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._card.notify_tile_press()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._card.notify_tile_release()
        event.accept()

    def paintEvent(self, event) -> None:
        if self._reveal <= 0.01:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        radius = self._card.RADIUS * self._card.current_scale()
        clip = QPainterPath()
        clip.addRoundedRect(0.0, 0.0, w, h, radius, radius)
        painter.setClipPath(clip)
        scrim = QLinearGradient(0.0, h * 0.42, 0.0, h)
        scrim.setColorAt(0.0, QColor(3, 7, 14, 0))
        scrim.setColorAt(1.0, QColor(3, 7, 14, int(198 * self._reveal)))
        painter.fillRect(self.rect(), scrim)

class GameCard(QFrame):
    clicked = Signal(int)
    play_clicked = Signal(int)
    stop_clicked = Signal(int)
    remove_clicked = Signal(int)
    menu_requested = Signal(int)
    hover_started = Signal(int, object)
    hover_ended = Signal(int)
    art_ready = Signal(int)

    CARD_W = 252
    TILE = 252
    CARD_H = 308
    RADIUS = 14
    POP = 0.085
    TITLE_DY = 10
    META_DY = 31
    ART_SCALE = 1.14

    def __init__(self, game_id: int, title: str, source: str,
                 verified: bool = True, playtime_seconds: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_id = game_id
        self._title = title
        self._source = source
        self._verified = bool(verified)
        self._playtime = int(playtime_seconds)
        self._pop = 0.0
        self._pressed = False
        self._base = (0, 0)
        self._running = False
        self._selected = False
        self._steam_tried = False
        self._exe_path = None
        self._search_title = title
        self._dpr = max(1.0, self.devicePixelRatioF() or 1.0)
        self._art = QPixmap()
        self._display = QPixmap()

        self.setObjectName("GameCard")
        self.resize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        start = int(round(self.TILE * self.ART_SCALE))
        start_radius = int(round(self.RADIUS * self.ART_SCALE))
        if source == "minecraft":
            self._set_art(minecraft_tile_pixmap(
                QSize(start, start), start_radius, self._dpr))
        elif source == "roblox":
            self._set_art(roblox_tile_pixmap(
                QSize(start, start), start_radius, self._dpr))
        else:
            self._set_art(placeholder_pixmap(
                title, QSize(start, start), start_radius, self._dpr))

        metrics = self.fontMetrics()
        self._title_label = QLabel(metrics.elidedText(
            title, Qt.TextElideMode.ElideRight, self.CARD_W - 24), self)
        self._title_label.setObjectName("CardTitle")
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft
                                       | Qt.AlignmentFlag.AlignVCenter)

        self._meta_label = QLabel("", self)
        self._meta_label.setObjectName("CardMeta")
        self._meta_label.setTextFormat(Qt.TextFormat.RichText)
        self._meta_label.setAlignment(Qt.AlignmentFlag.AlignLeft
                                      | Qt.AlignmentFlag.AlignVCenter)
        self._update_meta()

        self._overlay = _TileOverlay(self)
        self._overlay.setGeometry(0, 0, self.TILE, self.TILE)
        self._overlay.raise_()

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._entrance = QPropertyAnimation(self._fx, b"opacity", self)
        self._entrance.setDuration(300)
        self._entrance.setStartValue(0.0)
        self._entrance.setEndValue(1.0)
        self._entrance.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrance.finished.connect(self._drop_entrance_effect)

        self._pop_anim = QVariantAnimation(self)
        self._pop_anim.valueChanged.connect(self._apply_pop)

        self.customContextMenuRequested.connect(
            lambda _pos: self.menu_requested.emit(self._game_id))

        self._relayout(1.0)
        self._overlay.setVisible(False)

    @property
    def game_id(self) -> int:
        return self._game_id

    def current_scale(self) -> float:
        s = 1.0 + self.POP * self._pop
        return s * 0.965 if self._pressed else s

    def art_pixmap(self) -> QPixmap:
        return self._art

    def _drop_entrance_effect(self) -> None:
        try:
            self._fx = None
            self.setGraphicsEffect(None)
        except RuntimeError:
            pass

    def play_entrance(self, delay_ms: int) -> None:
        if self._fx is None:
            return
        delay = max(0, int(delay_ms))
        if delay == 0:
            self._entrance.start()
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._entrance.start)
        timer.timeout.connect(timer.deleteLater)
        self._entrance_timer = timer
        timer.start(delay)

    def set_base_pos(self, x: int, y: int) -> None:
        self._base = (int(x), int(y))
        if self._pop <= 0.001:
            self.move(int(x), int(y))
        else:
            self._apply_pop(self._pop)

    def snap_back(self) -> None:
        self._pop_anim.stop()
        self._pressed = False
        if self._pop <= 0.001:
            self.move(self._base[0], self._base[1])
            return
        self._pop = 0.0
        self.resize(self.CARD_W, self.CARD_H)
        self.move(self._base[0], self._base[1])
        self._overlay.set_reveal(0.0)
        self._overlay.setVisible(False)
        self._relayout(1.0)
        self.update()

    def _start_pop(self, target: float, duration_ms: int) -> None:
        self._pop_anim.stop()
        self._pop_anim.setDuration(int(duration_ms))
        self._pop_anim.setStartValue(float(self._pop))
        self._pop_anim.setEndValue(float(target))
        self._pop_anim.start()

    def _apply_pop(self, value: float) -> None:
        self._pop = max(0.0, min(1.0, float(value)))
        s = self.current_scale()
        w = int(round(self.CARD_W * s))
        h = int(round(self.CARD_H * s))
        self.resize(w, h)
        self.move(int(self._base[0] - (w - self.CARD_W) / 2.0),
                  int(self._base[1] - (h - self.CARD_H) / 2.0))
        self._overlay.setVisible(self._pop > 0.001)
        self._overlay.set_reveal(self._pop)
        self._relayout(s)
        self.update()

    def _relayout(self, s: float) -> None:
        tile = int(round(self.TILE * s))
        self._overlay.setGeometry(0, 0, tile, tile)
        self._overlay.raise_()
        width = int(round((self.CARD_W - 24) * s))
        self._title_label.setGeometry(int(round(12 * s)),
                                      int(round((self.TILE + self.TITLE_DY) * s)),
                                      width, int(round(20 * s)))
        self._meta_label.setGeometry(int(round(12 * s)),
                                     int(round((self.TILE + self.META_DY) * s)),
                                     width, int(round(17 * s)))

    def demo_hover(self) -> None:
        self.raise_()
        self._pressed = False
        self._start_pop(1.0, 200)
        self.hover_started.emit(self._game_id, self._art)

    def set_running(self, running: bool) -> None:
        try:
            self._running = bool(running)
            self._overlay.set_running(self._running)
            self.update()
        except (RuntimeError, AttributeError):
            pass

    def set_selected(self, selected: bool) -> None:
        try:
            if self._selected == bool(selected):
                return
            self._selected = bool(selected)
            self.update()
        except RuntimeError:
            pass

    @staticmethod
    def _chip_text(seconds: int) -> str | None:
        s = int(seconds)
        if s >= 3600:
            return f"{s // 3600}h"
        if s >= 60:
            return f"{s // 60}m"
        return None

    def _update_meta(self) -> None:
        label = SOURCE_LABELS.get(self._source, self._source.title())
        ready = '<span style="color:#30D158">\u2713</span>'
        missing = '<span style="color:#FF453A">\u2717</span>'
        status = ready if self._verified else missing
        played = self._chip_text(self._playtime)
        bits = [f"<span style='color:#9A9DA9'>{label}</span>"]
        if played:
            bits.append(f"<span style='color:#9A9DA9'>{played}</span>")
        bits.append(status)
        self._meta_label.setText(" \u00b7 ".join(bits))

    def set_playtime(self, seconds: int) -> None:
        try:
            self._playtime = int(seconds)
            self._update_meta()
        except RuntimeError:
            log.debug("Playtime update on deleted card ignored")

    def load_cover(self, urls: Sequence[str],
                   exe_path: str | None = None,
                   title: str | None = None) -> None:
        self._exe_path = exe_path
        self._search_title = title or self._title

        custom = Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation)) / "covers" / "custom" / f"{self._game_id}.img"
        if custom.is_file():
            target_px = QSize(int(self.TILE * self.ART_SCALE * self._dpr),
                              int(self.TILE * self.ART_SCALE * self._dpr))
            pixmap = load_cover_pixmap(str(custom), target_px)
            if not pixmap.isNull():
                self._set_art(pixmap)
                return

        if self._source == "roblox":
            load_remote_image([_ROBLOX_COVER], self._roblox_done)
            return

        if self._source == "minecraft":
            return

        famous = self._famous_art_for(self._search_title)
        if famous:
            self._famous_chain = famous
            load_remote_image(famous, self._famous_done)
            return

        if urls:
            load_remote_image(urls, self._cover_chain_done)
        else:
            self._cover_chain_done(None)

    def _roblox_done(self, path: str | None) -> None:
        try:
            if path:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._apply_cover_pixmap(pixmap)
                    return
            start = int(round(self.TILE * self.ART_SCALE))
            start_radius = int(round(self.RADIUS * self.ART_SCALE))
            self._set_art(roblox_tile_pixmap(
                QSize(start, start), start_radius, self._dpr))
        except RuntimeError:
            log.debug("Roblox cover on deleted card ignored")

    def _famous_art_for(self, title: str) -> list[str]:
        slug = title.casefold().replace(" ", "_").replace(":", "").replace("-", "_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        table = {
            "valorant": ["https://playvalorant.com/"],
            "league_of_legends": [
                "https://www.leagueoflegends.com/",
                "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/Jinx_0.jpg",
            ],
            "counter_strike_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/730/library_600x900.jpg"],
            "counter_strike": ["https://cdn.cloudflare.steamstatic.com/steam/apps/730/library_600x900.jpg"],
            "fortnite": ["https://cdn2.unrealengine.com/fortnite-keyart-1920x1080-8b0f6cf34f7b.jpg"],
            "gta_v": ["https://cdn.cloudflare.steamstatic.com/steam/apps/271590/library_600x900.jpg"],
            "grand_theft_auto_v": ["https://cdn.cloudflare.steamstatic.com/steam/apps/271590/library_600x900.jpg"],
            "red_dead_redemption_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1174180/library_600x900.jpg"],
            "apex_legends": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1172470/library_600x900.jpg"],
            "dota_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/570/library_600x900.jpg"],
            "pubg": ["https://cdn.cloudflare.steamstatic.com/steam/apps/578080/library_600x900.jpg"],
            "rust": ["https://cdn.cloudflare.steamstatic.com/steam/apps/252490/library_600x900.jpg"],
            "elden_ring": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1245620/library_600x900.jpg"],
            "cyberpunk_2077": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1091500/library_600x900.jpg"],
            "resident_evil_2": ["https://cdn.cloudflare.steamstatic.com/steam/apps/883710/library_600x900.jpg"],
            "ultrakill": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1229490/library_600x900.jpg"],
            "god_of_war": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1593500/library_600x900.jpg"],
            "hogwarts_legacy": ["https://cdn.cloudflare.steamstatic.com/steam/apps/990080/library_600x900.jpg"],
            "rocket_league": ["https://cdn.cloudflare.steamstatic.com/steam/apps/252950/library_600x900.jpg"],
            "among_us": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1030300/library_600x900.jpg"],
            "fall_guys": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1097150/library_600x900.jpg"],
            "terraria": ["https://cdn.cloudflare.steamstatic.com/steam/apps/105600/library_600x900.jpg"],
            "stardew_valley": ["https://cdn.cloudflare.steamstatic.com/steam/apps/413150/library_600x900.jpg"],
            "it_takes_two": ["https://cdn.cloudflare.steamstatic.com/steam/apps/1426210/library_600x900.jpg"],
            "hollow_knight": ["https://cdn.cloudflare.steamstatic.com/steam/apps/367520/library_600x900.jpg"],
        }
        if slug in table:
            return table[slug]
        for key, urls in table.items():
            if key in slug or slug in key:
                return urls
        return []

    def _famous_done(self, path: str | None) -> None:
        if path:
            self._apply_cover_file(path)
            return
        self._exe_chain()

    def _exe_chain(self) -> None:
        if self._exe_path:
            pixmap = self._exe_icon_pixmap()
            if pixmap is not None and not pixmap.isNull():
                self._apply_cover_pixmap(pixmap)
                return
        if not self._steam_tried and self._search_title:
            self._steam_tried = True
            self._try_steam_search()
            return

    def _cover_chain_done(self, path: str | None) -> None:
        try:
            if path:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    self._apply_cover_pixmap(pixmap)
                    return
            self._exe_chain()
        except RuntimeError:
            log.debug("Cover chain on deleted card ignored")

    def _exe_icon_pixmap(self):
        try:
            from utils.exe_icon import extract_exe_icon
            return extract_exe_icon(self._exe_path, 256)
        except Exception:
            log.debug("exe icon extraction failed", exc_info=True)
            return None

    def _try_steam_search(self) -> None:
        term = quote(self._search_title.strip())
        if not term:
            return
        url = QUrl(_STEAM_SEARCH_URL.format(term=term))
        request = QNetworkRequest(url)
        request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = _network().get(request)

        def _on_search() -> None:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            items = data.get("items") or []
            if not items:
                return
            appid = items[0].get("id")
            if not appid:
                return
            header = (f"https://cdn.cloudflare.steamstatic.com/"
                      f"steam/apps/{appid}/header.jpg")
            load_remote_image([header], self._cover_chain_done)

        reply.finished.connect(_on_search)

    def _apply_cover_file(self, path: str) -> None:
        try:
            target_px = QSize(int(self.TILE * self.ART_SCALE * self._dpr),
                              int(self.TILE * self.ART_SCALE * self._dpr))
            pixmap = load_cover_pixmap(path, target_px)
            if pixmap.isNull():
                return
            self._apply_cover_pixmap(pixmap)
        except RuntimeError:
            log.debug("Cover callback on deleted card ignored")

    def _apply_cover_pixmap(self, pixmap: QPixmap) -> None:
        try:
            if (pixmap.width() * pixmap.height() > _MAX_PIXELS
                    or pixmap.width() > 16384 or pixmap.height() > 16384):
                log.warning("Cover rejected for %s: %dx%d pixels",
                            self._title, pixmap.width(), pixmap.height())
                return
            self._set_art(pixmap)
        except RuntimeError:
            log.debug("Cover update on deleted card ignored")

    def _set_art(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._art = pixmap
        target = int(round(self.TILE * self.ART_SCALE))
        target_radius = int(round(self.RADIUS * self.ART_SCALE))
        self._display = full_art_tile_pixmap(
            pixmap, target, target_radius, self._dpr)
        self.update()
        if self._pop > 0.01:
            self.hover_started.emit(self._game_id, self._art)
        try:
            self.art_ready.emit(self._game_id)
        except RuntimeError:
            pass

    def set_custom_image(self, source_path: str) -> None:
        try:
            custom_dir = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation)) / "covers" / "custom"
            custom_dir.mkdir(parents=True, exist_ok=True)
            target = custom_dir / f"{self._game_id}.img"
            target.write_bytes(Path(source_path).read_bytes())
            pixmap = QPixmap(str(target))
            if not pixmap.isNull():
                self._apply_cover_pixmap(pixmap)
        except (OSError, RuntimeError):
            log.exception("Custom image failed")

    def notify_tile_press(self) -> None:
        if self._running:
            return
        self._pressed = True
        self._apply_pop(self._pop)
        self.clicked.emit(self._game_id)

    def notify_tile_release(self) -> None:
        if self._pressed:
            self._pressed = False
            self._apply_pop(self._pop)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            side = self.TILE * self.current_scale()
            tile = QRectF(0.0, 0.0, side, side)
            if tile.contains(event.position()):
                self.notify_tile_press()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.notify_tile_release()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        if scroll_is_active():
            super().enterEvent(event)
            return
        self.raise_()
        self._pressed = False
        self._start_pop(1.0, 200)
        self.hover_started.emit(self._game_id, self._art)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._pressed = False
        self._start_pop(0.0, 170)
        self.hover_ended.emit(self._game_id)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = self.current_scale()
        tw = self.TILE * s
        rect = QRectF(0.5, 0.5, tw - 1.0, tw - 1.0)
        radius = self.RADIUS * s
        if self._pop > 0.02:
            painter.setPen(Qt.PenStyle.NoPen)
            for grow, alpha in ((5, 30), (11, 18), (19, 9), (28, 4)):
                painter.setBrush(QColor(0, 0, 0, int(alpha * self._pop)))
                painter.drawRoundedRect(
                    rect.adjusted(-grow, -grow, grow, grow + 2),
                    radius + grow, radius + grow)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        if not self._display.isNull():
            painter.drawPixmap(
                rect, self._display,
                QRectF(0.0, 0.0, float(self._display.width()),
                       float(self._display.height())))
        else:
            painter.fillRect(rect, QColor("#131824"))
        painter.setClipping(False)
        if self._running:
            ring = QColor(255, 255, 255, int(205 + 50 * self._pop))
        else:
            ring = QColor(255, 255, 255, int(34 + 176 * self._pop))
        width = 1.2 + 0.8 * self._pop + (1.1 if self._running else 0.0)
        if self._selected:
            ring = QColor(255, 255, 255, max(ring.alpha(), 165))
            width = max(width, 1.8)
        painter.setPen(QPen(ring, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
