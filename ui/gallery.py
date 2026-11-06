from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from core import screenshots

log = logging.getLogger(__name__)


class GalleryDialog(QDialog):
    _QSS = """
        QDialog { background: #0C0F16; }
        #GalleryTitle { color: #F5F6F8; font-size: 12.5pt; font-weight: 700; }
        #GalleryCount { color: #8A8D98; font-size: 8.5pt; }
        #GalleryHint { color: #6C6F7C; font-size: 8pt; }
        QListWidget { background: transparent; border: none; }
        QListWidget::item { border-radius: 8px; }
        QListWidget::item:selected { border: 1px solid rgba(255,255,255,0.55);
            background: rgba(255,255,255,0.10); }
        QPushButton { border-radius: 10px; padding: 8px 18px;
            font-size: 9.5pt; font-weight: 600; border: none; }
        #GalleryPrimary { background: #F2F4F8; color: #0A0D14;
            font-weight: 700; }
        #GalleryPrimary:hover { background: #FFFFFF; }
        #GalleryGhost { background: rgba(255,255,255,0.07); color: #D8DAE2;
            border: 1px solid rgba(255,255,255,0.11); }
        #GalleryGhost:hover { background: rgba(255,255,255,0.13);
            border-color: rgba(255,255,255,0.30); }
    """

    THUMB = QSize(176, 100)

    def __init__(self, game: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_id = int(game.get("id") or 0)
        self._title = str(game.get("title") or "Game")
        self.setWindowTitle("Screenshots")
        self.setModal(True)
        self.setFixedWidth(620)
        self.setStyleSheet(self._QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(10)

        title = QLabel(f"{self._title}  \u00b7  Screenshots")
        title.setObjectName("GalleryTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(title)

        self._count = QLabel("")
        self._count.setObjectName("GalleryCount")
        root.addWidget(self._count)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(self.THUMB)
        self._list.setGridSize(QSize(self.THUMB.width() + 18,
                                     self.THUMB.height() + 30))
        self._list.setSpacing(8)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setWordWrap(True)
        self._list.setMinimumHeight(360)
        self._list.itemDoubleClicked.connect(self._open_item)
        root.addWidget(self._list, 1)

        self._hint = QLabel("Press Ctrl + Alt + S while a game is running "
                            "to capture the screen into this gallery.")
        self._hint.setObjectName("GalleryHint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        buttons = QHBoxLayout()
        capture_btn = QPushButton("Capture now")
        capture_btn.setObjectName("GalleryPrimary")
        capture_btn.clicked.connect(self._capture)
        folder_btn = QPushButton("Open folder")
        folder_btn.setObjectName("GalleryGhost")
        folder_btn.clicked.connect(self._open_folder)
        delete_btn = QPushButton("Delete selected")
        delete_btn.setObjectName("GalleryGhost")
        delete_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("GalleryGhost")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(capture_btn)
        buttons.addWidget(folder_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        items = screenshots.list_screenshots(self._game_id)
        for path in items:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            icon = QIcon(pixmap.scaled(
                self.THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation))
            item = QListWidgetItem(icon, path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(path.name)
            self._list.addItem(item)
        self._count.setText(f"{len(items)} screenshot(s) saved")

    def _capture(self) -> None:
        path = screenshots.capture_screen(self._game_id)
        if path is None:
            self._count.setText("Capture failed \u2014 no screen available")
            return
        self.refresh()

    def _open_folder(self) -> None:
        folder = screenshots.game_folder(self._game_id)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_item(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path or not os.path.isfile(path):
            return
        if os.name == "nt":
            try:
                os.startfile(path)
            except OSError:
                log.warning("Could not open screenshot %s", path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _delete_selected(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        removed = 0
        for item in selected:
            path = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if path and screenshots.delete_screenshot(Path(path)):
                removed += 1
        self.refresh()
        if not removed:
            QMessageBox.warning(self, "Screenshots",
                                "The selected screenshot could not be deleted.")
