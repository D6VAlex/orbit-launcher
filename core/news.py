from __future__ import annotations

import html
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QStandardPaths, QUrl, Signal
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                               QNetworkRequest)

log = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "store.steampowered.com",
    "feeds.ign.com",
    "www.pcgamer.com",
}

STEAM_NEWS_URL = "https://store.steampowered.com/feeds/news/app/{appid}/"
HEADLINE_FEEDS = (
    ("IGN", "https://feeds.ign.com/ign/games-all"),
    ("PC Gamer", "https://www.pcgamer.com/rss/"),
)

MAX_ITEMS = 60
_TRANSFER_MS = 15000
_CACHE_TTL = timedelta(hours=6)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: str = ""
    summary: str = ""
    feed: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "link": self.link, "source": self.source,
                "published": self.published, "summary": self.summary,
                "feed": self.feed}

    @staticmethod
    def from_dict(data: dict) -> "NewsItem | None":
        title = str(data.get("title") or "").strip()
        link = str(data.get("link") or "").strip()
        if not title or not link:
            return None
        return NewsItem(
            title=title[:220], link=link, source=str(data.get("source") or ""),
            published=str(data.get("published") or ""),
            summary=str(data.get("summary") or "")[:400],
            feed=str(data.get("feed") or ""))


def _url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https":
        return False
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    return parsed.hostname is not None \
        and parsed.hostname.casefold() in ALLOWED_HOSTS


def _strip_html(text: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", str(text or "")))
    return _WS_RE.sub(" ", text).strip()


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError, IndexError):
        return None


def parse_rss(text: str, source: str, feed: str = "") -> list[NewsItem]:
    try:
        root = ET.fromstring(str(text or ""))
    except ET.ParseError:
        log.warning("RSS parse failed for %s", source)
        return []
    items: list[NewsItem] = []
    for node in root.iter("item"):
        title = _strip_html(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        summary = _strip_html(node.findtext("description") or "")
        if len(summary) > 300:
            summary = summary[:297].rstrip() + "\u2026"
        items.append(NewsItem(
            title=title[:220], link=link, source=source,
            published=(node.findtext("pubDate") or "").strip(),
            summary=summary, feed=feed))
    return items


def _cache_path() -> Path:
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation))
    return base / "news_cache.json"


def load_cache(mode: str) -> list[dict]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8")[:2_000_000])
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    bucket = data.get(mode)
    if not isinstance(bucket, dict):
        return []
    fetched = bucket.get("fetched_at")
    try:
        when = datetime.fromisoformat(str(fetched))
        if datetime.now(timezone.utc) - when > _CACHE_TTL * 24:
            return []
    except ValueError:
        return []
    items = bucket.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = NewsItem.from_dict(raw)
        if item is not None:
            out.append(item.to_dict())
    return out


def save_cache(mode: str, items: list[dict]) -> None:
    try:
        path = _cache_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")[:2_000_000])
            if not isinstance(data, dict):
                data = {}
        except (OSError, json.JSONDecodeError):
            data = {}
        data[mode] = {"fetched_at": datetime.now(timezone.utc).isoformat(),
                      "items": items[:MAX_ITEMS]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data)[:2_000_000], encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        log.exception("News cache write failed")


class NewsFetcher(QObject):
    ready = Signal(list)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._nam.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._pending = 0
        self._items: list[NewsItem] = []

    def fetch(self, sources: list[tuple[str, str, str]]) -> None:
        self._items = []
        self._pending = 0
        started = False
        for source, url, feed in sources:
            if not _url_allowed(url):
                log.warning("News feed rejected: %s", url)
                continue
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(_TRANSFER_MS)
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            reply = self._nam.get(request)
            reply.finished.connect(
                lambda r=reply, s=source, f=feed: self._on_reply(r, s, f))
            self._pending += 1
            started = True
        if not started:
            self.failed.emit("no feeds")

    def _on_reply(self, reply: QNetworkReply, source: str, feed: str) -> None:
        try:
            final = reply.url().toString()
            if not _url_allowed(final):
                log.warning("News reply host rejected: %s", final)
            elif reply.error() != QNetworkReply.NetworkError.NoError:
                log.warning("News fetch failed (%s): %s",
                            source, reply.errorString())
            else:
                text = bytes(reply.readAll()).decode("utf-8", "replace")
                self._items.extend(parse_rss(text, source, feed))
        finally:
            reply.deleteLater()
            self._pending = max(0, self._pending - 1)
            if self._pending == 0:
                self._finish()

    def _finish(self) -> None:
        seen: set[str] = set()
        unique: list[NewsItem] = []
        for item in self._items:
            if item.link in seen:
                continue
            seen.add(item.link)
            unique.append(item)
        unique.sort(key=lambda i: _parse_date(i.published)
                    or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
        unique = unique[:MAX_ITEMS]
        payload = [item.to_dict() for item in unique]
        if payload:
            self.ready.emit(payload)
        else:
            self.failed.emit("no news found")
