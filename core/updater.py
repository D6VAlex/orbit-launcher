from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                               QNetworkRequest)

log = logging.getLogger(__name__)

APP_VERSION = "1.1.1"
UPDATE_URL = ("https://raw.githubusercontent.com/D6VAlex/orbit-launcher/"
              "main/latest.json")

_MANIFEST_HOSTS = {"github.com", "raw.githubusercontent.com"}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

_TIMEOUT_MS = 10_000

def _manifest_url_ok(url: str) -> bool:
    try:
        parts = urlparse(str(url))
    except ValueError:
        return False
    return (parts.scheme == "https"
            and parts.hostname in _MANIFEST_HOSTS
            and not parts.username
            and not parts.password)

def _parse_version(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in str(value).strip().lstrip("vV").split("."))
    except (ValueError, AttributeError):
        return ()

class UpdateChecker:
    def __init__(self) -> None:
        self._nam = QNetworkAccessManager()
        self.last_sha = ""

    def check(self, on_result) -> None:
        request = QNetworkRequest(QUrl(UPDATE_URL))
        request.setTransferTimeout(_TIMEOUT_MS)
        reply = self._nam.get(request)

        def _done() -> None:
            reply.deleteLater()
            if reply.error() != reply.error().NoError:
                log.info("Update check skipped (offline): %s", reply.error())
                on_result(False, "", "")
                return
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                log.warning("Update manifest unreadable: %s", exc)
                on_result(False, "", "")
                return
            remote = _parse_version(data.get("version", ""))
            local = _parse_version(APP_VERSION)
            latest_url = str(data.get("url", ""))
            notes = str(data.get("notes", ""))
            sha256 = str(data.get("sha256") or "").strip().lower()
            if not _SHA_RE.match(sha256):
                sha256 = ""
            self.last_sha = sha256
            if remote <= local:
                on_result(False, "", "")
                return
            if not _manifest_url_ok(latest_url):
                log.warning("Update manifest url rejected: %r", latest_url)
                on_result(False, "", "")
                return
            on_result(True, latest_url, notes)

        reply.finished.connect(_done)

def _verify_sha256(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected.strip().lower()

class InstallerDownloader(QObject):

    finished = Signal(bool, str)
    progress = Signal(int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._target: Path | None = None
        self._sha = ""

    def abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def start(self, url: str, sha256: str, target: Path) -> None:
        if not _manifest_url_ok(url):
            self.finished.emit(False, "update url rejected")
            return
        self._sha = sha256.strip().lower()
        self._target = target
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(target, "wb")
        except OSError as exc:
            self.finished.emit(False, f"cannot write file: {exc}")
            return
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(300_000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        self._reply = self._nam.get(request)
        self._reply.downloadProgress.connect(self._on_progress)
        self._reply.readyRead.connect(self._on_chunk)
        self._reply.finished.connect(self._on_done)

    def _on_progress(self, received: int, total: int) -> None:
        self.progress.emit(int(received), max(0, int(total)))

    def _on_chunk(self) -> None:
        if self._reply is None:
            return
        self._fh.write(bytes(self._reply.readAll()))

    def _on_done(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        self._fh.close()
        error = reply.error()
        reply.deleteLater()
        if error != reply.error().NoError:
            self._cleanup()
            self.finished.emit(False, "download failed")
            return
        target = self._target
        if target is None or not target.is_file() or target.stat().st_size <= 0:
            self._cleanup()
            self.finished.emit(False, "downloaded file is empty")
            return
        if self._sha and not _verify_sha256(target, self._sha):
            self._cleanup()
            log.warning("Update checksum mismatch - file deleted")
            self.finished.emit(False, "checksum mismatch")
            return
        self.finished.emit(True, "")

    def _cleanup(self) -> None:
        try:
            if self._target is not None and self._target.is_file():
                self._target.unlink()
        except OSError:
            pass
