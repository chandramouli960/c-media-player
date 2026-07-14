"""The main window (``ReelPlayer``) and the ``main()`` entry point.

This is the controller: it builds the UI, owns the play queue (``Playlist``) and
the mpv engine (``PlayerCore``), and connects the two to the widgets. All the
mpv thread-safety and the queue's index bookkeeping live in those helpers, so
this file is about wiring and window behaviour (detach/attach, fullscreen,
shortcuts, persistence).
"""
import json
import locale
import logging
import os
import sys
import time

from PyQt6.QtCore import Qt, QThreadPool, QTimer
from PyQt6.QtGui import (
    QCursor, QDragEnterEvent, QDropEvent, QIcon, QKeySequence, QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .config import (
    APP_NAME, CONFIG_DIR, ICON_PATH, PLAYLISTS_FILE, STATE_FILE, VIDEO_EXTS,
)
from .player_core import PlayerCore
from .playlist import Playlist
from .scanning import PlaylistScanWorker, ScanSignals
from .style import STYLE
from .widgets import DetachedVideoWindow, HomePage, VideoSurface

log = logging.getLogger(__name__)


class ReelPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1180, 700)
        self.setAcceptDrops(True)
        # Frosted-glass look: the window paints no opaque background, so the
        # desktop shows through the translucent chrome (the video stays opaque).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # The play queue (single source of truth for order + current item).
        self.playlist = Playlist()
        self.detached = False
        # Set while we tear a player down on purpose, so the shutdown signal
        # that mpv fires during our own terminate() isn't mistaken for the user
        # clicking the OSC close button.
        self._closing_player = False

        # The mpv engine. Its observers/bindings fire on mpv's own threads and
        # only emit Qt signals, which we connect (queued) to main-thread slots.
        self.core = PlayerCore(self)
        self.core.eof_reached.connect(self._on_eof)
        self.core.pause_changed.connect(self._on_mpv_pause)
        self.core.shutdown.connect(self._on_mpv_shutdown)
        self.core.minimized.connect(self._on_mpv_minimize)
        self.core.maximized.connect(self._on_mpv_maximize)
        self.core.aspect.connect(self._on_mpv_aspect)
        self.core.drag.connect(self._on_mpv_drag)
        self.core.click.connect(self._on_video_click)
        self.core.dblclick.connect(self._on_video_dblclick)

        # Manual drag of the detached window: while the left button is held on
        # the video body, a timer moves the window to follow the global cursor.
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(8)
        self._drag_timer.timeout.connect(self._drag_follow)
        self._drag_origin_cursor = None
        self._drag_origin_win = None

        self.detached_window = DetachedVideoWindow(on_close=self._attach)

        # Click-to-pause is debounced so a double-click (fullscreen toggle)
        # doesn't also flip pause. The delay must exceed mpv's double-click
        # window (input-doubleclick-time, set to 220 ms) so a pending
        # single-click can be cancelled when the second click arrives.
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(240)
        self._click_timer.timeout.connect(self.toggle_pause)

        # The detached window's transport buttons drive the same actions as the
        # docked ones.
        self.detached_window.btn_prev.clicked.connect(self.play_previous)
        self.detached_window.btn_rewind.clicked.connect(lambda: self.seek_relative(-5))
        self.detached_window.btn_pause.clicked.connect(self.toggle_pause)
        self.detached_window.btn_skip.clicked.connect(lambda: self.seek_relative(5))
        self.detached_window.btn_next.clicked.connect(self.play_next)
        # Close = re-attach the video to the main window without raising/focusing
        # it, so the user stays on their current workspace.
        self.detached_window.btn_close.clicked.connect(self._attach)

        # Persist the playlist + resume position periodically (and on close), so
        # a crash can't lose more than a few seconds of progress.
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(5000)
        self._state_timer.timeout.connect(self._save_state)
        self._state_timer.start()

        # Saved playlists (folders) for the home page, scanned off-thread.
        self.playlists = self._load_playlists()
        self._pool = QThreadPool.globalInstance()
        self._scan_signals = ScanSignals()
        self._scan_signals.result.connect(self._on_scan_result)

        self._build_ui()
        self._build_player()
        self._build_shortcuts()

        self.home_page.set_playlists(self.playlists)
        self._scan_all()

    # ---- convenience accessors (the queue lives in self.playlist) ----------
    @property
    def player(self):
        """The live mpv instance (created by PlayerCore)."""
        return self.core.player

    @property
    def playlist_paths(self):
        return self.playlist.paths

    @property
    def current_index(self):
        return self.playlist.current_index

    @current_index.setter
    def current_index(self, value):
        self.playlist.current_index = value

    def _fix_locale(self):
        self.core.fix_locale()

    # ---------- UI ----------
    def _build_ui(self):
        self.pages = QStackedWidget()
        self.pages.setObjectName("central")
        self.setCentralWidget(self.pages)

        # --- home / playlists page (index 0) ---
        self.home_page = HomePage()
        self.home_page.open_playlist.connect(self.open_playlist)
        self.home_page.add_requested.connect(self.add_playlist_dialog)
        self.home_page.remove_requested.connect(self.remove_playlist)
        self.home_page.rename_requested.connect(self.rename_playlist)
        self.home_page.reorder.connect(self.reorder_playlists)
        self.pages.addWidget(self.home_page)

        # --- player page (index 1) ---
        player_root = QWidget()
        player_root.setObjectName("central")
        root = QVBoxLayout(player_root)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter
        root.addWidget(splitter)

        # --- left: video + controls ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.video_stack = QStackedWidget()
        self.surface = VideoSurface()
        self.detach_message = QLabel("Video detached — playing in its own window")
        self.detach_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detach_message.setStyleSheet("background-color: rgba(18, 20, 28, 0.68); color: #8b8f9c; font-size: 13px;")
        self.video_stack.addWidget(self.surface)
        self.video_stack.addWidget(self.detach_message)
        left_layout.addWidget(self.video_stack, 1)

        controls = QWidget()
        controls.setObjectName("transportBar")
        controls.setFixedHeight(56)
        c_layout = QVBoxLayout(controls)
        c_layout.setContentsMargins(14, 8, 14, 8)

        btn_row = QHBoxLayout()
        self.btn_home = QPushButton("≡ Playlists")
        self.btn_home.clicked.connect(self.show_home)
        self.btn_prev = QPushButton("⏮ Prev")
        self.btn_rewind = QPushButton("⏪ 5")
        self.btn_pause = QPushButton("⏸")
        self.btn_skip = QPushButton("5 ⏩")
        self.btn_next = QPushButton("Next ⏭")
        self.btn_fullscreen = QPushButton("⛶ Fullscreen")
        self.btn_detach = QPushButton("Detach Video")
        self.btn_open_folder = QPushButton("Open Folder…")
        self.btn_add = QPushButton("Add Videos…")
        self.btn_add.setObjectName("accent")

        self.btn_prev.clicked.connect(self.play_previous)
        self.btn_rewind.clicked.connect(lambda: self.seek_relative(-5))
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_skip.clicked.connect(lambda: self.seek_relative(5))
        self.btn_next.clicked.connect(self.play_next)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.btn_detach.clicked.connect(self.toggle_detach)
        self.btn_open_folder.clicked.connect(self.open_folder_dialog)
        self.btn_add.clicked.connect(self.add_files_dialog)

        btn_row.addWidget(self.btn_home)
        btn_row.addSpacing(6)
        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_rewind)
        btn_row.addWidget(self.btn_pause)
        btn_row.addWidget(self.btn_skip)
        btn_row.addWidget(self.btn_next)
        btn_row.addWidget(self.btn_fullscreen)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_detach)
        btn_row.addWidget(self.btn_open_folder)
        btn_row.addWidget(self.btn_add)
        c_layout.addLayout(btn_row)

        left_layout.addWidget(controls)
        splitter.addWidget(left)

        # --- right: playlist ---
        right = QWidget()
        right.setObjectName("sidePanel")
        right.setMinimumWidth(260)
        right.setMaximumWidth(360)
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(10, 10, 10, 10)
        r_layout.setSpacing(8)

        title = QLabel("PLAYLIST")
        title.setObjectName("title")
        r_layout.addWidget(title)

        self.playlist_widget = QListWidget()
        self.playlist_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.playlist_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.playlist_widget.model().rowsMoved.connect(self._on_rows_moved)
        r_layout.addWidget(self.playlist_widget, 1)

        pl_btn_row = QHBoxLayout()
        self.btn_remove = QPushButton("Remove")
        self.btn_clear = QPushButton("Clear")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_playlist)
        pl_btn_row.addWidget(self.btn_remove)
        pl_btn_row.addWidget(self.btn_clear)
        r_layout.addLayout(pl_btn_row)

        self.right_panel = right
        self.controls_widget = controls
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([880, 300])

        self.player_page = player_root
        self.pages.addWidget(player_root)
        self.pages.setCurrentWidget(self.home_page)

    def _build_shortcuts(self):
        # Shortcuts on the main window (docked mode).
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_pause)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.seek_relative(5))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.seek_relative(-5))
        QShortcut(QKeySequence("N"), self, activated=self.play_next)
        QShortcut(QKeySequence("P"), self, activated=self.play_previous)
        QShortcut(QKeySequence("F"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("M"), self, activated=self.toggle_mute)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)
        # The detached window is a separate top-level, so it needs its own copies
        # (main-window shortcuts don't fire while it's the active window).
        dw = self.detached_window
        QShortcut(QKeySequence(Qt.Key.Key_Space), dw, activated=self.toggle_pause)
        QShortcut(QKeySequence(Qt.Key.Key_Right), dw, activated=lambda: self.seek_relative(5))
        QShortcut(QKeySequence(Qt.Key.Key_Left), dw, activated=lambda: self.seek_relative(-5))
        QShortcut(QKeySequence("F"), dw, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("M"), dw, activated=self.toggle_mute)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), dw, activated=self._on_escape)

    # ---------- mpv ----------
    def _build_player(self):
        self.core.create(self.surface)
        self.player.volume = 80

    def _safe_seek(self, pos):
        self.core.seek(pos)

    def _on_eof(self):
        # Advance shortly after end-of-file so mpv has settled the transition.
        QTimer.singleShot(50, self.play_next)

    # ---------- playlist management ----------
    def add_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add videos", os.path.expanduser("~"),
            "Video files (*.mp4 *.mkv *.webm *.avi *.mov *.flv *.m4v *.ts *.wmv);;All files (*)"
        )
        if files:
            self.add_files(files)

    def open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Open folder as playlist", os.path.expanduser("~")
        )
        if not folder:
            return
        self.clear_playlist()
        self.add_files([folder])

    def add_files(self, paths):
        was_empty = self.playlist.is_empty
        for p in paths:
            if os.path.isdir(p):
                for root, _dirs, entries in os.walk(p):
                    for entry in sorted(entries):
                        if os.path.splitext(entry)[1].lower() in VIDEO_EXTS:
                            self._append_item(os.path.join(root, entry))
            elif os.path.splitext(p)[1].lower() in VIDEO_EXTS:
                self._append_item(p)
        if was_empty and not self.playlist.is_empty:
            self.play_index(0)
        self._save_state()

    def _append_item(self, path):
        self.playlist.append(path)
        item = QListWidgetItem(os.path.basename(path))
        item.setToolTip(path)
        self.playlist_widget.addItem(item)

    def remove_selected(self):
        row = self.playlist_widget.currentRow()
        if row < 0:
            return
        self.playlist_widget.takeItem(row)
        was_current = self.playlist.remove(row)
        if was_current:
            self.player.command("stop")
        self._save_state()

    def clear_playlist(self):
        self.player.command("stop")
        self.playlist_widget.clear()
        self.playlist.clear()
        self._save_state()

    # ---------- session persistence ----------
    def _save_state(self):
        """Persist the playlist, which video is current, and its position so the
        next launch resumes exactly where the user left off. Written atomically
        and best-effort (never raises into the UI)."""
        try:
            cur = self.playlist.current_path
            try:
                pos = self.player.time_pos
            except Exception:  # noqa: BLE001 — mpv may be mid-teardown
                pos = None
            if pos is None:
                pos = self.core.last_time_pos
            try:
                vol = float(self.player.volume)
            except Exception:  # noqa: BLE001
                vol = 80.0
            data = {
                "playlist": list(self.playlist.paths),
                "current_path": cur,
                "position": float(pos or 0),
                "volume": vol,
            }
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            log.debug("could not save state: %s", e)

    def restore_session(self):
        """Reload the saved playlist and cue the last-played video, paused at the
        position it was left at (files that no longer exist are dropped)."""
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        paths = [p for p in data.get("playlist", []) if os.path.exists(p)]
        if not paths:
            return
        for p in paths:
            self._append_item(p)
        cur = data.get("current_path")
        idx = paths.index(cur) if cur in paths else 0
        pos = data.get("position", 0) or 0
        self._fix_locale()
        try:
            self.player.volume = data.get("volume", 80)
        except Exception:  # noqa: BLE001
            pass
        self.playlist.set_current(idx)
        self.playlist_widget.setCurrentRow(idx)
        path = paths[idx]
        self.player.play(path)
        # Start paused on the frame we left off — the user presses play to resume.
        self.player.pause = True
        self.setWindowTitle(f"{APP_NAME} — {os.path.basename(path)}")
        if pos:
            QTimer.singleShot(500, lambda p=pos: self._safe_seek(p))

    # ---------- home page / saved playlists ----------
    def _load_playlists(self):
        try:
            with open(PLAYLISTS_FILE) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = []
        out = []
        for e in raw:
            path = e.get("path")
            if not path or not os.path.isdir(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0
            out.append({
                "name": e.get("name") or os.path.basename(path.rstrip("/")) or path,
                "path": path,
                "added": e.get("added", 0),
                "_mtime": mtime,
                "_count": None,
                "_thumb": "",
            })
        return out

    def _save_playlists(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = [{"name": p["name"], "path": p["path"], "added": p.get("added", 0)}
                    for p in self.playlists]
            tmp = PLAYLISTS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, PLAYLISTS_FILE)
        except OSError as e:
            log.debug("could not save playlists: %s", e)

    def _scan_all(self):
        for p in self.playlists:
            self._pool.start(PlaylistScanWorker(p["path"], self._scan_signals))

    def _on_scan_result(self, path, count, thumb):
        for p in self.playlists:
            if p["path"] == path:
                p["_count"] = count
                if thumb:
                    p["_thumb"] = thumb
                break
        self.home_page.update_scan(path, count, thumb)

    def add_playlist_dialog(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Add a folder as a playlist", os.path.expanduser("~")
        )
        if not folder:
            return
        if any(p["path"] == folder for p in self.playlists):
            return
        try:
            mtime = os.path.getmtime(folder)
        except OSError:
            mtime = 0
        entry = {
            "name": os.path.basename(folder.rstrip("/")) or folder,
            "path": folder,
            "added": time.time(),
            "_mtime": mtime,
            "_count": None,
            "_thumb": "",
        }
        self.playlists.append(entry)
        self._save_playlists()
        self.home_page.set_playlists(self.playlists)
        self._pool.start(PlaylistScanWorker(folder, self._scan_signals))

    def remove_playlist(self, path):
        self.playlists = [p for p in self.playlists if p["path"] != path]
        self._save_playlists()
        self.home_page.set_playlists(self.playlists)

    def rename_playlist(self, path):
        entry = next((p for p in self.playlists if p["path"] == path), None)
        if entry is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename playlist", "Playlist name:", text=entry["name"]
        )
        if ok and new_name.strip():
            entry["name"] = new_name.strip()
            self._save_playlists()
            self.home_page.set_playlists(self.playlists)

    def reorder_playlists(self, src_path, target_path):
        src = next((p for p in self.playlists if p["path"] == src_path), None)
        if src is None:
            return
        self.playlists.remove(src)
        if target_path:
            try:
                idx = next(i for i, p in enumerate(self.playlists) if p["path"] == target_path)
            except StopIteration:
                idx = len(self.playlists)
            self.playlists.insert(idx, src)
        else:
            self.playlists.append(src)
        self._save_playlists()
        # Show the manual arrangement (a drag implies "my order").
        self.home_page.set_sort_custom()
        self.home_page.set_playlists(self.playlists)

    def open_playlist(self, path):
        # Load the folder's videos into the queue and switch to the player.
        self._show_player()
        self.clear_playlist()
        self.add_files([path])

    def show_home(self):
        if self.detached:
            self._attach()
        self.pages.setCurrentWidget(self.home_page)

    def _show_player(self):
        self.pages.setCurrentWidget(self.player_page)

    def _on_item_double_clicked(self, item):
        self.play_index(self.playlist_widget.row(item))

    def _on_rows_moved(self, *_args):
        new_order = []
        for i in range(self.playlist_widget.count()):
            new_order.append(self.playlist_widget.item(i).toolTip())
        self.playlist.set_order(new_order)
        self._save_state()

    # ---------- playback control ----------
    def play_index(self, index):
        if not (0 <= index < len(self.playlist)):
            return
        self._fix_locale()
        self.playlist.set_current(index)
        path = self.playlist.paths[index]
        self.player.play(path)
        self.player.pause = False
        self.core.last_time_pos = 0
        self.playlist_widget.setCurrentRow(index)
        self.setWindowTitle(f"{APP_NAME} — {os.path.basename(path)}")
        self._save_state()

    def play_next(self):
        if self.playlist.has_next():
            self.play_index(self.playlist.current_index + 1)

    def play_previous(self):
        if self.playlist.has_previous():
            self.play_index(self.playlist.current_index - 1)

    def toggle_pause(self):
        if self.playlist.current_index == -1 and not self.playlist.is_empty:
            self.play_index(0)
            return
        self._fix_locale()
        self.player.pause = not self.player.pause

    def toggle_mute(self):
        self._fix_locale()
        self.player.mute = not self.player.mute

    def set_volume(self, value):
        self._fix_locale()
        self.player.volume = value
        self.player.mute = False

    def seek_relative(self, secs):
        self.core.seek(secs, reference="relative")

    def toggle_fullscreen(self):
        if self.detached:
            self._set_detached_fullscreen(not self.detached_window.isFullScreen())
        else:
            self._set_docked_fullscreen(not self.isFullScreen())

    def _set_docked_fullscreen(self, on):
        # Hide the playlist + transport bar so the embedded video fills the
        # screen; restore them on exit.
        self.right_panel.setVisible(not on)
        self.controls_widget.setVisible(not on)
        if on:
            # Remember whether we were maximised so exiting fullscreen returns
            # to the same size instead of shrinking to the "normal" geometry.
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        elif getattr(self, "_was_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()

    def _set_detached_fullscreen(self, on):
        self.detached_window.set_fullscreen(on)

    def _on_escape(self):
        # Escape backs out one level: leave fullscreen, else re-dock a detached
        # window.
        if self.isFullScreen():
            self._set_docked_fullscreen(False)
        elif self.detached and self.detached_window.isFullScreen():
            self._set_detached_fullscreen(False)
        elif self.detached:
            self._attach()

    # ---------- Detached-window OSC controls ----------
    def _on_mpv_shutdown(self):
        # The detached window's OSC close button (or `q`) issues mpv `quit`,
        # which shuts the core down. Treat that as "re-dock" so the video
        # returns to the main window. Ignore the shutdowns we trigger ourselves
        # while swapping players.
        if self.detached and not self._closing_player:
            self._attach()

    def _on_mpv_minimize(self):
        if self.detached:
            self.detached_window.showMinimized()

    def _on_mpv_maximize(self, maximized):
        if not self.detached:
            return
        if maximized:
            self.detached_window.showMaximized()
        else:
            self.detached_window.showNormal()

    def _on_mpv_pause(self, paused):
        icon = "▶" if paused else "⏸"
        self.btn_pause.setText(icon)
        self.detached_window.btn_pause.setText(icon)

    def _on_video_click(self):
        # Defer the pause toggle; a double-click cancels it (see _click_timer).
        self._click_timer.start()

    def _on_video_dblclick(self):
        self._click_timer.stop()   # swallow the pending single-click pause
        self.toggle_fullscreen()

    def _on_mpv_aspect(self, aspect):
        if self.detached and not self.detached_window.isMaximized():
            self.detached_window.apply_aspect(aspect)

    def _on_mpv_drag(self, pressed):
        # Left button pressed/released on the video body → start/stop moving the
        # detached window so it follows the cursor.
        if pressed:
            if not self.detached:
                return
            self._drag_origin_cursor = QCursor.pos()
            self._drag_origin_win = self.detached_window.pos()
            self._drag_timer.start()
        else:
            self._drag_timer.stop()

    def _drag_follow(self):
        if not self.detached or self._drag_origin_cursor is None:
            self._drag_timer.stop()
            return
        delta = QCursor.pos() - self._drag_origin_cursor
        self.detached_window.move(self._drag_origin_win + delta)

    # ---------- Detach / Attach ----------
    def toggle_detach(self):
        if not self.detached:
            self._detach()
        else:
            self._attach()

    def _save_playback_state(self):
        path = None
        pos, vol, was_paused = 0, 80, False
        if self.playlist.current_path is not None:
            path = self.playlist.current_path
            try:
                pos = self.player.time_pos or 0
            except Exception:  # noqa: BLE001
                pos = self.core.last_time_pos
            try:
                was_paused = bool(self.player.pause)
            except Exception:  # noqa: BLE001
                pass
        try:
            vol = self.player.volume
        except Exception:  # noqa: BLE001
            vol = 80
        return path, pos, vol, was_paused

    def _restore_playback_state(self, path, pos, vol, was_paused):
        self.player.volume = vol
        if path:
            self.player.play(path)
            self.player.pause = False
            if pos:
                QTimer.singleShot(300, lambda p=pos: self._safe_seek(p))
            if was_paused:
                QTimer.singleShot(350, lambda: setattr(self.player, "pause", True))

    def _detach(self):
        path, pos, vol, was_paused = self._save_playback_state()
        self._closing_player = True
        self.core.terminate()

        # Show the frameless window (and realize its native video_holder) before
        # embedding — querying winId() pre-show hands mpv a preliminary native
        # window Qt may still replace, which used to crash. Showing first avoids
        # that.
        self.detached_window.show()
        self.detached_window.raise_()
        self.detached_window.activateWindow()

        self.core.create(self.detached_window.video_holder, window_controls=True)
        self._closing_player = False
        self._restore_playback_state(path, pos, vol, was_paused)

        self.video_stack.setCurrentWidget(self.detach_message)
        self.detached = True
        self.btn_detach.setText("Attach Video")

    def _attach(self):
        if not self.detached:
            return
        self._drag_timer.stop()
        self._closing_player = True
        path, pos, vol, was_paused = self._save_playback_state()
        self.core.terminate()

        self.detached_window.hide()

        self.core.create(self.surface)
        self._closing_player = False
        self._restore_playback_state(path, pos, vol, was_paused)

        self.video_stack.setCurrentWidget(self.surface)
        self.detached = False
        self.btn_detach.setText("Detach Video")

    # ---------- drag & drop ----------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.add_files(paths)

    def closeEvent(self, event):
        self._save_state()
        self._closing_player = True
        self.core.terminate()
        try:
            self.detached_window._force_close = True
            self.detached_window.close()
        except Exception as e:  # noqa: BLE001
            log.debug("closing detached window raised: %s", e)
        event.accept()


def main():
    # Quiet by default; set CMP_DEBUG=1 to see the debug diagnostics that the
    # best-effort error handlers log instead of silently swallowing.
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("CMP_DEBUG") else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    os.environ["LC_NUMERIC"] = "C"
    app = QApplication(sys.argv)
    # Qt can change the process locale on startup (e.g. decimal comma locales),
    # which makes libmpv misparse numeric option strings and crash. Force it back.
    locale.setlocale(locale.LC_NUMERIC, "C")
    app.setStyleSheet(STYLE)
    window = ReelPlayer()
    window.show()

    # Allow launching with file args: python main.py video1.mp4 video2.mkv.
    # With no args, start on the Playlists home page.
    if len(sys.argv) > 1:
        window._show_player()
        window.add_files(sys.argv[1:])

    sys.exit(app.exec())
