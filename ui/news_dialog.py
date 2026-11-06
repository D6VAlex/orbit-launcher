from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from core.news import (HEADLINE_FEEDS, NewsFetcher, STEAM_NEWS_URL,
                       load_cache, save_cache)

log = logging.getLogger(__name__)

MODE_GAMES = "games"
MODE_HEADLINES = "headlines"
_MAX_GAME_FEEDS = 6


class _NewsCard(QFrame):
    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NewsCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link = str(item.get("link") or "")

        title = QLabel(str(item.get("title") or ""))
        title.setObjectName("NewsTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)

        meta_parts = [str(item.get("source") or "News")]
        published = str(item.get("published") or "")
        if published:
            meta_parts.append(published[:22])
        meta = QLabel("  \u00b7  ".join(meta_parts))
        meta.setObjectName("NewsMeta")
        meta.setTextFormat(Qt.TextFormat.PlainText)

        summary = QLabel(str(item.get("summary") or ""))
        summary.setObjectName("NewsBody")
        summary.setWordWrap(True)
        summary.setVisible(bool(summary.text()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(title)
        layout.addWidget(meta)
        layout.addWidget(summary)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._link:
            url = QUrl(self._link)
            if url.scheme().casefold() == "https":
                QDesktopServices.openUrl(url)
        super().mouseReleaseEvent(event)


class NewsDialog(QDialog):
    _QSS = """
        QDialog { background: #0C0F16; }
        #NewsHeading { color: #F5F6F8; font-size: 12.5pt; font-weight: 700;
            letter-spacing: 2px; }
        #NewsStatus { color: #8A8D98; font-size: 8.5pt; }
        #NewsCard { background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.09); border-radius: 14px; }
        #NewsCard:hover { border-color: rgba(255,255,255,0.30); }
        #NewsTitle { color: #F5F6F8; font-size: 10pt; font-weight: 600; }
        #NewsMeta { color: #8A8D98; font-size: 8pt; }
        #NewsBody { color: #B9BCC8; font-size: 8.5pt; }
        QScrollArea { background: transparent; border: none; }
        QWidget#qt_scrollarea_viewport { background: transparent; }
        QScrollArea > QWidget > QWidget { background: transparent; }
        QPushButton { border-radius: 10px; padding: 7px 16px;
            font-size: 9pt; font-weight: 600; border: none; }
        #NewsRefresh { background: #F2F4F8; color: #0A0D14; font-weight: 700; }
        #NewsRefresh:hover { background: #FFFFFF; }
        #NewsRefresh:disabled { background: rgba(255,255,255,0.08);
            color: #8A8D98; }
    """

    def __init__(self, db, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self.setWindowTitle("Gaming news")
        self.setModal(True)
        self.setFixedWidth(660)
        self.setStyleSheet(self._QSS)

        self._fetcher = NewsFetcher(self)
        self._fetcher.ready.connect(self._on_ready)
        self._fetcher.failed.connect(self._on_failed)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("NEWS")
        heading.setObjectName("NewsHeading")
        self._mode = QComboBox()
        self._mode.addItem("My games", MODE_GAMES)
        self._mode.addItem("Gaming headlines", MODE_HEADLINES)
        self._mode.currentIndexChanged.connect(self._reload)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("NewsRefresh")
        refresh_btn.clicked.connect(self._reload)
        header.addWidget(heading)
        header.addStretch(1)
        header.addWidget(self._mode)
        header.addSpacing(8)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        self._status = QLabel("")
        self._status.setObjectName("NewsStatus")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._body = QWidget()
        self._body_l = QVBoxLayout(self._body)
        self._body_l.setContentsMargins(0, 0, 6, 0)
        self._body_l.setSpacing(10)
        self._body_l.addStretch(1)
        self._scroll.setWidget(self._body)
        root.addWidget(self._scroll, 1)

        self._reload()

    def _game_feeds(self) -> list[tuple[str, str, str]]:
        sources: list[tuple[str, str, str]] = []
        try:
            rows = sorted(self._db.games_by_source("steam"),
                          key=lambda r: int(r.get("total_playtime") or 0),
                          reverse=True)
        except Exception:
            rows = []
        for row in rows:
            appid = str(row.get("platform_id") or "")
            if not appid.isdigit():
                continue
            title = str(row.get("title") or "Steam")
            sources.append((title, STEAM_NEWS_URL.format(appid=appid),
                            "steam"))
            if len(sources) >= _MAX_GAME_FEEDS:
                break
        return sources

    def _reload(self) -> None:
        mode = self._mode.currentData() or MODE_GAMES
        cached = load_cache(mode)
        if cached:
            self._render(cached, from_cache=True)
        else:
            self._clear_cards()
            self._status.setText("Loading news\u2026")
        feeds = self._game_feeds() if mode == MODE_GAMES else []
        if mode == MODE_HEADLINES:
            feeds = [(name, url, "web") for name, url in HEADLINE_FEEDS]
        if not feeds:
            if mode == MODE_GAMES:
                feeds = [(name, url, "web") for name, url in HEADLINE_FEEDS]
                if not cached:
                    self._status.setText(
                        "No Steam games found \u2014 showing gaming headlines.")
        self._fetcher.fetch(feeds)

    def _clear_cards(self) -> None:
        while self._body_l.count():
            item = self._body_l.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self, items: list[dict], from_cache: bool = False) -> None:
        self._clear_cards()
        if not items:
            self._status.setText("No news available right now.")
            return
        suffix = "  \u00b7  cached" if from_cache else ""
        self._status.setText(f"{len(items)} updates{suffix}")
        for item in items[:40]:
            self._body_l.addWidget(_NewsCard(item, self._body))
        self._body_l.addStretch(1)

    def _on_ready(self, items: list) -> None:
        mode = self._mode.currentData() or MODE_GAMES
        payload = [item for item in items if isinstance(item, dict)]
        save_cache(mode, payload)
        self._render(payload, from_cache=False)

    def _on_failed(self, reason: str) -> None:
        mode = self._mode.currentData() or MODE_GAMES
        cached = load_cache(mode)
        if cached:
            self._render(cached, from_cache=True)
            self._status.setText(self._status.text()
                                 + "  \u00b7  offline \u2014 showing cache")
        else:
            self._status.setText("Could not load news "
                                 f"({reason}). Check your connection.")
