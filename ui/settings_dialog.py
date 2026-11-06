from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from core import cloudsync
from core.quicklauncher import HOTKEY_LABELS
from core.settings import HOTKEY_CHOICES, Settings
from utils import win32_helpers as win32


def _cache_dir() -> Path:
    base = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation))
    return base / "covers"


class _Row(QFrame):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("SettingsRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("SettingsTitle")
        t.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("SettingsSub")
            s.setWordWrap(True)
            layout.addWidget(s)


class SettingsDialog(QDialog):
    _QSS = """
        QDialog { background: #0C0F16; }
        #SettingsRow { background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.09); border-radius: 14px; }
        #SettingsTitle { color: #F5F6F8; font-size: 10.5pt; font-weight: 600; }
        #SettingsSub { color: #A8ABB8; font-size: 8.5pt; }
        #SettingsNote { color: #6C6F7C; font-size: 8pt; }
        QScrollArea { background: transparent; border: none; }
        QWidget#qt_scrollarea_viewport { background: transparent; }
        #SettingsHost { background: transparent; }
        QCheckBox { color: #D8DAE2; font-size: 10pt; }
        QCheckBox::indicator { width: 17px; height: 17px; border-radius: 5px;
            border: 1px solid rgba(255,255,255,0.25);
            background: rgba(255,255,255,0.06); }
        QCheckBox::indicator:hover { border-color: rgba(255,255,255,0.55); }
        QCheckBox::indicator:checked { background: #F2F4F8;
            border: 1px solid #F2F4F8; }
        QDoubleSpinBox { background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.10); border-radius: 10px;
            padding: 6px 10px; color: #F5F6F8; font-size: 9.5pt;
            selection-background-color: rgba(255,255,255,0.45); }
        QDoubleSpinBox:hover { border-color: rgba(255,255,255,0.38); }
        QPushButton { border-radius: 10px; padding: 8px 18px;
            font-size: 9.5pt; font-weight: 600; border: none; }
    """

    def __init__(self, settings: Settings, parent: QWidget | None = None,
                 db=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._db = db
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setFixedWidth(540)
        self.setMinimumSize(540, 620)
        self.setStyleSheet(self._QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(10)

        title = QLabel("SETTINGS")
        title.setStyleSheet("color:#F5F6F8; font-size:13pt; font-weight:700;"
                            " letter-spacing:4px;")
        root.addWidget(title)

        host = QWidget()
        host.setObjectName("SettingsHost")
        root_cards = QVBoxLayout(host)
        root_cards.setContentsMargins(0, 0, 6, 0)
        root_cards.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        def add_card(card) -> None:
            root_cards.addWidget(card)

        card1 = _Row("Riot auto-PLAY",
                     "After launching a Riot title, Orbit presses PLAY inside "
                     "the genuine Riot Client window (ownership is verified by "
                     "process, and the mouse never moves). Turn off if you "
                     "prefer pressing PLAY yourself.")
        self._riot_check = QCheckBox("Enabled")
        self._riot_check.setChecked(settings.riot_clicker_enabled)
        card1.layout().addWidget(self._riot_check)
        add_card(card1)

        card2 = _Row("Discord Rich Presence",
                     "Show what you are playing on your Discord profile "
                     "(game name only - nothing else is shared).")
        self._rpc_check = QCheckBox("Enabled")
        self._rpc_check.setChecked(settings.discord_rpc_enabled)
        card2.layout().addWidget(self._rpc_check)
        add_card(card2)

        card3 = _Row("Splash duration",
                     "How long the loading screen stays, in seconds (0-15).")
        spin_row = QHBoxLayout()
        self._splash_spin = QDoubleSpinBox()
        self._splash_spin.setRange(0.0, 15.0)
        self._splash_spin.setSingleStep(0.5)
        self._splash_spin.setValue(settings.splash_min_seconds)
        self._splash_spin.setSuffix(" s")
        spin_row.addWidget(self._splash_spin)
        spin_row.addStretch(1)
        card3.layout().addLayout(spin_row)
        add_card(card3)

        hidden_n = self._db.hidden_count() if self._db is not None else 0
        card4 = _Row("Removed games",
                     "Games you removed from the library stay hidden so the "
                     "scanner never re-adds them. Restore them to let the "
                     "next scan detect them again.")
        self._hidden_btn = QPushButton(
            f"Restore {hidden_n} hidden game(s)" if hidden_n
            else "No hidden games")
        self._hidden_btn.setEnabled(hidden_n > 0)
        self._hidden_btn.clicked.connect(self._restore_hidden)
        card4.layout().addWidget(self._hidden_btn)
        add_card(card4)

        startup_now = (win32.is_in_startup() if os.name == "nt"
                       else settings.auto_startup)
        card5 = _Row("Start with Windows",
                     "ON: Orbit launches automatically when you sign in. "
                     "You can change this at any time.")
        self._startup_check = QCheckBox("Enabled")
        self._startup_check.setChecked(startup_now)
        card5.layout().addWidget(self._startup_check)
        add_card(card5)

        card6 = _Row("Theme", "Current theme: Aurora Glass. More themes in a "
                              "future update.")
        add_card(card6)

        card7 = _Row("Cover art cache",
                     "Cached cover images downloaded for your library.")
        cache_row = QHBoxLayout()
        self._cache_label = QLabel(self._cache_size_text())
        self._cache_label.setObjectName("SettingsNote")
        clear_btn = QPushButton("Clear cache")
        clear_btn.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.07); color:#D8DAE2;"
            " border:1px solid rgba(255,255,255,0.11); }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }"
            "QPushButton:pressed { background:rgba(255,255,255,0.19); }")
        clear_btn.clicked.connect(self._clear_cache)
        cache_row.addWidget(self._cache_label)
        cache_row.addStretch(1)
        cache_row.addWidget(clear_btn)
        card7.layout().addLayout(cache_row)
        add_card(card7)

        card8 = _Row("Weekly playtime goal",
                     "A soft target for how long you play per rolling week. "
                     "Progress shows on the stats line and Orbit celebrates "
                     "once when you reach it. 0 = off.")
        goal_row = QHBoxLayout()
        self._goal_spin = QSpinBox()
        self._goal_spin.setRange(0, 80)
        self._goal_spin.setSuffix(" h")
        self._goal_spin.setSpecialValueText("Off")
        self._goal_spin.setValue(settings.weekly_goal_hours)
        goal_row.addWidget(self._goal_spin)
        goal_row.addStretch(1)
        card8.layout().addLayout(goal_row)
        add_card(card8)

        card9 = _Row("Quick launcher",
                     "A global hotkey that opens a small search box above "
                     "everything: type a game name, press Enter, it starts. "
                     "It also works while Orbit is in the tray. The capture "
                     "hotkey Ctrl + Alt + S saves a screenshot of the game "
                     "you are playing.")
        quick_row = QHBoxLayout()
        self._quick_check = QCheckBox("Enabled")
        quick_enabled = settings.quick_hotkey != "off"
        self._quick_check.setChecked(quick_enabled)
        self._quick_combo = QComboBox()
        for key in HOTKEY_CHOICES:
            if key == "off":
                continue
            self._quick_combo.addItem(HOTKEY_LABELS[key], key)
        current_key = settings.quick_hotkey
        index = self._quick_combo.findData(
            current_key if current_key != "off" else "ctrl+alt+space")
        self._quick_combo.setCurrentIndex(max(0, index))
        self._quick_combo.setEnabled(quick_enabled)
        self._quick_check.toggled.connect(self._quick_combo.setEnabled)
        quick_row.addWidget(self._quick_check)
        quick_row.addStretch(1)
        quick_row.addWidget(self._quick_combo)
        card9.layout().addLayout(quick_row)
        add_card(card9)

        card10 = _Row("Cloud sync (backup)",
                      "Point Orbit at a folder inside OneDrive, Google Drive "
                      "or Dropbox and it keeps a small orbit-profile.json "
                      "there: your library, playtime, tags, launch options "
                      "and app settings. On another PC, choose the same "
                      "folder and restore. No account, no server.")
        sync_path_row = QHBoxLayout()
        self._sync_dir_value = settings.sync_dir
        self._sync_dir_label = QLabel(self._short_dir(self._sync_dir_value))
        self._sync_dir_label.setObjectName("SettingsNote")
        browse_btn = QPushButton("Choose folder\u2026")
        browse_btn.setStyleSheet(self._ghost_qss())
        browse_btn.clicked.connect(self._choose_sync_dir)
        sync_path_row.addWidget(self._sync_dir_label, 1)
        sync_path_row.addWidget(browse_btn)
        card10.layout().addLayout(sync_path_row)
        sync_action_row = QHBoxLayout()
        backup_btn = QPushButton("Back up now")
        backup_btn.setStyleSheet(self._ghost_qss())
        backup_btn.clicked.connect(self._backup_now)
        restore_btn = QPushButton("Restore\u2026")
        restore_btn.setStyleSheet(self._ghost_qss())
        restore_btn.clicked.connect(self._restore_now)
        self._sync_auto_check = QCheckBox("Sync automatically")
        self._sync_auto_check.setChecked(settings.sync_auto)
        sync_action_row.addWidget(backup_btn)
        sync_action_row.addWidget(restore_btn)
        sync_action_row.addStretch(1)
        sync_action_row.addWidget(self._sync_auto_check)
        card10.layout().addLayout(sync_action_row)
        self._sync_status = QLabel("")
        self._sync_status.setObjectName("SettingsNote")
        card10.layout().addWidget(self._sync_status)
        add_card(card10)
        root_cards.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(
            "QPushButton { background:rgba(255,255,255,0.07); color:#D8DAE2;"
            " border:1px solid rgba(255,255,255,0.11); }"
            "QPushButton:hover { background:rgba(255,255,255,0.13);"
            " border-color:rgba(255,255,255,0.30); }"
            "QPushButton:pressed { background:rgba(255,255,255,0.19); }")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setStyleSheet(
            "QPushButton { background:#F2F4F8; color:#0A0D14;"
            " font-weight:700; }"
            "QPushButton:hover { background:#FFFFFF; }"
            "QPushButton:pressed { background:#C9CEDA; }")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _cache_size_text(self) -> str:
        total = 0
        cache = _cache_dir()
        if cache.is_dir():
            for f in cache.iterdir():
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
        return f"{total / (1024 * 1024):.1f} MB used"

    @staticmethod
    def _ghost_qss() -> str:
        return ("QPushButton { background:rgba(255,255,255,0.07); "
                "color:#D8DAE2; border:1px solid rgba(255,255,255,0.11); }"
                "QPushButton:hover { background:rgba(255,255,255,0.13); "
                "border-color:rgba(255,255,255,0.30); }"
                "QPushButton:pressed { background:rgba(255,255,255,0.19); }")

    @staticmethod
    def _short_dir(path: str) -> str:
        if not path:
            return "No folder chosen yet"
        text = str(path)
        return text if len(text) <= 58 else text[:55] + "\u2026"

    def _choose_sync_dir(self) -> None:
        start = self._sync_dir_value or ""
        chosen = QFileDialog.getExistingDirectory(self,
                                                  "Choose the sync folder",
                                                  start)
        if not chosen:
            return
        self._sync_dir_value = chosen
        self._sync_dir_label.setText(self._short_dir(chosen))
        self._settings.set("sync_dir", chosen)

    def _backup_now(self) -> None:
        if self._db is None or not self._sync_dir_value:
            self._sync_status.setText(
                "Choose a sync folder first.")
            return
        profile = cloudsync.build_profile(self._db, self._settings)
        path = cloudsync.write_profile(self._sync_dir_value, profile)
        if path is None:
            self._sync_status.setText("Backup failed \u2014 folder not writable?")
            return
        self._settings.set("last_sync_seen",
                           str(profile.get("saved_at") or ""))
        games = len(profile.get("games") or [])
        self._sync_status.setText(
            f"Backed up {games} games to {path.name}.")

    def _restore_now(self) -> None:
        if self._db is None or not self._sync_dir_value:
            self._sync_status.setText("Choose a sync folder first.")
            return
        profile = cloudsync.read_profile(self._sync_dir_value)
        if profile is None:
            self._sync_status.setText(
                "No orbit-profile.json found in that folder.")
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
        box.setWindowTitle("Restore from backup")
        saved = str(profile.get("saved_at") or "unknown time")
        box.setText("Found a backup saved " + saved +
                    "\n\nRestore (replace) wipes this library and loads the "
                    "backup. Merge keeps this library and adds anything "
                    "missing from the backup.")
        replace_btn = box.addButton("Restore (replace)",
                                    QMessageBox.ButtonRole.AcceptRole)
        merge_btn = box.addButton("Merge",
                                  QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace_btn:
            mode = "replace"
        elif clicked is merge_btn:
            mode = "merge"
        else:
            return
        summary = cloudsync.apply_profile(self._db, profile, mode)
        self._settings.set("last_sync_seen",
                           str(profile.get("saved_at") or ""))
        if mode == "replace":
            for key, value in cloudsync.settings_from_profile(profile).items():
                self._settings.set(key, value)
        self._sync_status.setText(
            "Restored: " + cloudsync.describe_summary(summary))
        self._restored = True

    def _clear_cache(self) -> None:
        cache = _cache_dir()
        if cache.is_dir():
            for f in cache.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
        self._cache_label.setText(self._cache_size_text())

    def _restore_hidden(self) -> None:
        if self._db is None:
            return
        count = self._db.unhide_all()
        self._hidden_btn.setText("No hidden games")
        self._hidden_btn.setEnabled(False)
        QMessageBox.information(
            self, "Removed games",
            f"{count} game(s) restored. Run a new scan to detect them again.")

    def _save(self) -> None:
        self._settings.set("riot_clicker_enabled", self._riot_check.isChecked())
        self._settings.set("discord_rpc_enabled", self._rpc_check.isChecked())
        self._settings.set("splash_min_seconds", float(self._splash_spin.value()))
        want_startup = self._startup_check.isChecked()
        self._settings.set("auto_startup", want_startup)
        if os.name == "nt":
            if want_startup and not win32.is_in_startup():
                win32.add_to_startup()
            elif not want_startup and win32.is_in_startup():
                win32.remove_from_startup()
        self._settings.set("weekly_goal_hours", int(self._goal_spin.value()))
        quick_key = (str(self._quick_combo.currentData())
                     if self._quick_check.isChecked() else "off")
        self._settings.set("quick_hotkey", quick_key)
        if self._sync_dir_value != self._settings.sync_dir:
            self._settings.set("sync_dir", self._sync_dir_value)
        self._settings.set("sync_auto", self._sync_auto_check.isChecked())
        self.accept()

    @staticmethod
    def open_dialog(settings: Settings, parent: QWidget | None = None,
                    db=None) -> tuple[bool, bool]:
        dialog = SettingsDialog(settings, parent, db=db)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return accepted, getattr(dialog, "_restored", False)
