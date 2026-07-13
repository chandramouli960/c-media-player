#!/usr/bin/env python3
"""
Reel — a lightweight local video player with playlist + Picture-in-Picture.
Built with PyQt6 + libmpv.
"""
import hashlib
import json
import locale
import os
import shutil
import subprocess
import sys
import time

# mpv's window embedding (the `wid` parameter below) only works under X11/XWayland.
# On a native Wayland Qt platform, embedding silently fails and mpv opens its own
# separate top-level window instead — that's the "two title bars" / unresponsive
# buttons bug. Forcing xcb here (before PyQt is imported) fixes Qt's side of it.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
# libmpv makes its own, independent backend choice: if it still sees WAYLAND_DISPLAY
# it'll open its own native Wayland window regardless of what Qt is doing, ignoring
# `wid` entirely (this is the "video plays in a separate bare window" symptom).
# Hiding the variable forces it onto the same X11 path so embedding actually works.
os.environ.pop("WAYLAND_DISPLAY", None)

from PyQt6.QtCore import (
    Qt, QTimer, QMimeData, pyqtSignal, QThreadPool, QRunnable, QObject, QSize,
    QRect, QPoint
)
from PyQt6.QtGui import (
    QKeySequence, QShortcut, QDragEnterEvent, QDropEvent, QIcon, QCursor,
    QPixmap, QColor, QPainter, QLinearGradient, QFont, QPainterPath, QDrag
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFileDialog, QSplitter, QAbstractItemView, QSizePolicy, QStackedWidget,
    QScrollArea, QComboBox, QLineEdit, QLayout, QFrame, QMenu, QInputDialog
)

import mpv

APP_NAME = "C Media Player"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(APP_DIR, "icons", "icon-256.png")
# Self-contained mpv config dir bundled with the app. It carries uosc
# (github.com/tomasklaen/uosc) as the seek bar, plus its icon fonts and
# script-opts. Pointing mpv here keeps everything isolated from the user's
# own ~/.config/mpv.
MPV_CONFIG_DIR = os.path.join(APP_DIR, "mpv")

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4v", ".ts", ".wmv"}

# Where the playlist + resume position are persisted between sessions.
CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "c-media-player",
)
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")
# Saved "playlists" (each is a folder) shown on the home page, and the cache
# for their generated thumbnails.
PLAYLISTS_FILE = os.path.join(CONFIG_DIR, "playlists.json")
THUMB_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "c-media-player", "thumbs",
)
FFMPEG = shutil.which("ffmpeg")

# Transparent "frosted glass" theme. Top-level windows are marked with
# WA_TranslucentBackground and paint nothing themselves, so the desktop shows
# through wherever a widget doesn't draw an opaque background. The video surface
# stays opaque (mpv), while the chrome (playlist, transport bars) uses
# semi-transparent fills for the see-through look.
ACCENT = "#e0b64a"
STYLE = """
* { font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 13px; color: #eceae6; }
QMainWindow, QWidget#central { background: transparent; }

QWidget#sidePanel { background-color: rgba(18, 20, 28, 0.68); border-left: 1px solid rgba(255,255,255,0.06); }
QWidget#transportBar { background-color: rgba(14, 16, 22, 0.72); border-top: 1px solid rgba(255,255,255,0.05); }

QListWidget { background-color: rgba(255,255,255,0.03); border: none; outline: none; padding: 4px; border-radius: 10px; }
QListWidget::item { padding: 9px 10px; border-radius: 7px; margin: 2px 2px; }
QListWidget::item:selected { background-color: rgba(224,182,74,0.16); color: %(accent)s; }
QListWidget::item:hover:!selected { background-color: rgba(255,255,255,0.06); }

QPushButton { background-color: rgba(255,255,255,0.055); border: 1px solid rgba(255,255,255,0.10);
              border-radius: 9px; padding: 7px 13px; color: #eceae6; }
QPushButton:hover { background-color: rgba(255,255,255,0.12); border-color: rgba(224,182,74,0.65); }
QPushButton:pressed { background-color: rgba(224,182,74,0.22); }
QPushButton#accent { background-color: %(accent)s; color: #14161c; font-weight: 600; border: none; }
QPushButton#accent:hover { background-color: #ecc25a; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.30); }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QLabel#title { font-size: 12px; font-weight: 700; letter-spacing: 2px; color: %(accent)s; }
QSplitter::handle { background: transparent; }

/* ---- home / playlists page ---- */
QWidget#home { background-color: rgba(13, 14, 19, 0.88); }
QWidget#homeScroll, QWidget#gridHost { background: transparent; }
QLabel#pageTitle { font-size: 30px; font-weight: 800; color: #f4f2ee; }
QLineEdit#search { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
                   border-radius: 18px; padding: 8px 15px; color: #eceae6; selection-background-color: rgba(224,182,74,0.35); }
QLineEdit#search:focus { border-color: rgba(224,182,74,0.7); }
QComboBox#sort { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
                 border-radius: 16px; padding: 6px 14px; color: #eceae6; }
QComboBox#sort:hover { border-color: rgba(224,182,74,0.6); }
QComboBox#sort::drop-down { border: none; width: 22px; }
QComboBox#sort QAbstractItemView { background: #1b1e27; color: #eceae6; border: 1px solid rgba(255,255,255,0.12);
                                   border-radius: 8px; outline: none; selection-background-color: rgba(224,182,74,0.28); }
QFrame#card { background: transparent; border-radius: 12px; }
QFrame#card:hover { background: rgba(255,255,255,0.055); }
QLabel#cardTitle { font-size: 14px; font-weight: 600; color: #f0eee9; }
QLabel#cardSub { font-size: 12px; color: #9aa0ad; }
QLabel#badge { background-color: rgba(0,0,0,0.80); color: #ffffff; font-size: 11px; font-weight: 600;
               padding: 2px 7px; border-radius: 5px; }
QLabel#emptyState { color: #8b8f9c; font-size: 15px; }
""" % {"accent": ACCENT}


def fmt_time(seconds):
    if seconds is None:
        return "00:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class VideoSurface(QWidget):
    """Plain child widget embedded in the main layout — mpv renders into this
    while docked. No custom window flags; it's just a normal part of the
    window, positioned by Qt's layout system like anything else."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Match the playlist panel's frosted translucency for the empty state.
        # mpv paints opaque frames over this once a video actually plays, so this
        # fill only shows when nothing is loaded.
        self.setStyleSheet("background-color: rgba(18, 20, 28, 0.68);")


class DetachedVideoWindow(QWidget):
    """Frameless detached video window with no title bar. mpv is embedded into
    an inset child (``video_holder``), which leaves a thin grab frame that the
    window manager never draws but Qt still receives mouse events on. That frame
    gives us real, client-side window management with no decorations:

        • drag any EDGE or CORNER → resize (startSystemResize)
        • drag the VIDEO itself    → move   (startSystemMove, driven by mpv;
                                            see the MBTN_LEFT binding in
                                            _create_mpv_core)

    Both hand off to the compositor via the _NET_WM_MOVERESIZE protocol, so they
    feel exactly like resizing/moving a normal window. Closing/minimising is
    done from mpv's OSC window controls inside the video."""

    BORDER = 8    # thickness of the resize grab frame around the video
    CORNER = 28   # distance from a corner that still counts as "the corner"
    CONTROLS_H = 44  # height of the always-visible transport bar

    def __init__(self, on_close):
        super().__init__()
        self._on_close = on_close
        self._force_close = False
        self._aspect = 0.0      # locked video aspect (holder width / height)
        self._locking = False   # reentrancy guard for the resize correction
        self.setWindowTitle(f"{APP_NAME} — Video")
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(960, 540)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._layout = QVBoxLayout(self)
        b = self.BORDER
        self._layout.setContentsMargins(b, b, b, b)
        self._layout.setSpacing(0)
        self.video_holder = QWidget(self)
        self.video_holder.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_holder.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.video_holder.setStyleSheet("background-color: black;")
        # Give the video area its own plain cursor so it never inherits the
        # resize cursor the frame sets (that leak is why resize arrows showed
        # over the middle of the video).
        self.video_holder.setCursor(Qt.CursorShape.ArrowCursor)
        self._layout.addWidget(self.video_holder, 1)

        # Always-visible transport bar (prev / rewind / play-pause / skip / next).
        # It has a fixed height and stays laid out below the video, so the
        # buttons remain hittable no matter how small the window gets — unlike
        # mpv's OSC, which shrinks with the video. ReelPlayer wires the buttons.
        self.controls = self._build_controls()
        self._layout.addWidget(self.controls)

        # Keep the window big enough that all the buttons always fit.
        self.setMinimumSize(340, 200)

    def _build_controls(self):
        bar = QWidget()
        bar.setObjectName("transportBar")
        bar.setFixedHeight(self.CONTROLS_H)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 5, 10, 5)
        row.setSpacing(8)
        self.btn_prev = QPushButton("⏮")       # previous video in the playlist
        self.btn_rewind = QPushButton("⏪ 5")
        self.btn_pause = QPushButton("⏸")
        self.btn_skip = QPushButton("5 ⏩")
        self.btn_next = QPushButton("⏭")        # next video in the playlist
        self.btn_close = QPushButton("✕")       # attach video back, no focus steal
        self.btn_prev.setToolTip("Previous video")
        self.btn_next.setToolTip("Next video")
        self.btn_close.setToolTip("Close — attach video back to the main window")
        row.addStretch(1)
        for btn in (self.btn_prev, self.btn_rewind, self.btn_pause,
                    self.btn_skip, self.btn_next):
            btn.setMinimumWidth(52)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
        row.addStretch(1)
        self.btn_close.setMinimumWidth(40)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.btn_close)
        return bar

    def set_fullscreen(self, on):
        # In fullscreen the video goes edge-to-edge: drop the resize frame and
        # hide the transport bar; mpv's OSC and the shortcut keys still work.
        m = 0 if on else self.BORDER
        self._layout.setContentsMargins(m, m, m, m)
        self.controls.setVisible(not on)
        if on:
            self.raise_()
            self.activateWindow()
            self.showFullScreen()
        else:
            self.showNormal()

    def _edges_at(self, pos):
        """Which resize edges a point is on. Only points inside the grab frame
        (which is all the parent ever receives — the video covers the rest) get
        here; near a corner we combine both axes for a diagonal resize."""
        b, c, w, h = self.BORDER, self.CORNER, self.width(), self.height()
        x, y = pos.x(), pos.y()
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        on_l, on_r, on_t, on_b = x <= b, x >= w - b, y <= b, y >= h - b
        near_l, near_r, near_t, near_b = x <= c, x >= w - c, y <= c, y >= h - c
        if (on_l or on_t) and near_l and near_t:
            return L | T
        if (on_r or on_t) and near_r and near_t:
            return R | T
        if (on_l or on_b) and near_l and near_b:
            return L | B
        if (on_r or on_b) and near_r and near_b:
            return R | B
        if on_l:
            return L
        if on_r:
            return R
        if on_t:
            return T
        if on_b:
            return B
        return Qt.Edge(0)

    def _cursor_for(self, edges):
        L, R = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
        T, B = Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if edges in (L | T, R | B):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (R | T, L | B):
            return Qt.CursorShape.SizeBDiagCursor
        if edges in (L, R):
            return Qt.CursorShape.SizeHorCursor
        if edges in (T, B):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def apply_aspect(self, aspect):
        """Lock to the given display aspect ratio (video width/height) and size
        the window so the video area matches it, keeping the current width and
        clamping to the screen. Called when a video's real dimensions arrive.
        From then on resizeEvent keeps the ratio, so black bars never appear."""
        if aspect <= 0:
            return
        self._aspect = aspect
        chrome_w = 2 * self.BORDER
        chrome_h = 2 * self.BORDER + self.CONTROLS_H
        holder_w = max(1, self.width() - chrome_w)
        holder_h = max(1, round(holder_w / aspect))
        new_w, new_h = holder_w + chrome_w, holder_h + chrome_h
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            max_w, max_h = int(avail.width() * 0.95), int(avail.height() * 0.95)
            if new_w > max_w:
                new_h = round(new_h * max_w / new_w)
                new_w = max_w
            if new_h > max_h:
                new_w = round(new_w * max_h / new_h)
                new_h = max_h
        self._locking = True
        self.resize(new_w, new_h)
        self._locking = False

    def resizeEvent(self, event):
        # Keep the window locked to the video's aspect ratio as the user drags a
        # wall/corner, so the picture always fills it (no black bars). Whichever
        # dimension the user changed more is the driver; the other is derived.
        super().resizeEvent(event)
        if (self._aspect <= 0 or self._locking
                or self.isMaximized() or self.isFullScreen()):
            return
        chrome_w = 2 * self.BORDER
        chrome_h = 2 * self.BORDER + self.CONTROLS_H
        w, h = self.width(), self.height()
        holder_w, holder_h = w - chrome_w, h - chrome_h
        if holder_w <= 0 or holder_h <= 0:
            return
        old = event.oldSize()
        d_w = abs(w - old.width()) if old.width() > 0 else 0
        d_h = abs(h - old.height()) if old.height() > 0 else 0
        if d_h > d_w:
            target_w = round(holder_h * self._aspect) + chrome_w
            new_size = (target_w, h)
        else:
            target_h = round(holder_w / self._aspect) + chrome_h
            new_size = (w, target_h)
        if new_size != (w, h):
            self._locking = True
            self.resize(*new_size)
            self._locking = False

    def mouseMoveEvent(self, event):
        # This only fires over the grab frame (the video covers the rest). Show
        # the matching resize cursor there, and a plain arrow otherwise.
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self.setCursor(QCursor(self._cursor_for(edges)))
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        # The frame resizes; moving the window from the video body is handled by
        # mpv's MBTN_LEFT binding (see _create_mpv_core / _on_mpv_drag).
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            edges = self._edges_at(event.position().toPoint())
            if handle is not None and edges:
                handle.startSystemResize(edges)
        super().mousePressEvent(event)

    def closeEvent(self, event):
        if self._force_close:
            event.accept()
            return
        # Alt+F4 etc. re-docks instead of destroying the reusable window.
        event.ignore()
        self._on_close()


# ---------------------------------------------------------------------------
# Home / Playlists page
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """A left-to-right wrapping layout (the classic Qt flow layout) so the
    playlist cards reflow into as many columns as the width allows."""
    def __init__(self, parent=None, margin=0, spacing=18):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        sp = self.spacing()
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            if x + w > right and line_h > 0:
                x = rect.x() + m.left()
                y = y + line_h + sp
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = x + w + sp
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


def _rounded_pixmap(src, w, h, radius=10):
    scaled = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(w), float(h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
    p.end()
    return out


def _placeholder_pixmap(name, w, h, radius=10):
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(w), float(h), radius, radius)
    p.setClipPath(path)
    hue = (sum(ord(c) for c in name) * 37) % 360
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor.fromHsl(hue, 120, 78))
    grad.setColorAt(1.0, QColor.fromHsl((hue + 40) % 360, 130, 42))
    p.fillRect(0, 0, w, h, grad)
    p.setPen(QColor(255, 255, 255, 235))
    f = QFont()
    f.setPointSize(max(12, int(h * 0.30)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, (name.strip()[:1] or "?").upper())
    p.end()
    return out


class _ScanSignals(QObject):
    result = pyqtSignal(str, int, str)   # folder path, video count, thumb path ("" if none)


class PlaylistScanWorker(QRunnable):
    """Off the UI thread: recursively count videos in a folder and render a
    thumbnail from the first one (cached on disk). Keeps the home page snappy."""
    def __init__(self, path, signals):
        super().__init__()
        self.path = path
        self.signals = signals

    def run(self):
        vids = []
        try:
            for root, _dirs, files in os.walk(self.path):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                        vids.append(os.path.join(root, f))
        except Exception:
            pass
        thumb = ""
        if vids and FFMPEG:
            first = vids[0]
            try:
                stamp = str(int(os.path.getmtime(first)))
            except Exception:
                stamp = "0"
            key = hashlib.md5((first + stamp).encode("utf-8", "replace")).hexdigest()
            out = os.path.join(THUMB_DIR, key + ".jpg")
            if not os.path.exists(out):
                try:
                    os.makedirs(THUMB_DIR, exist_ok=True)
                    subprocess.run(
                        [FFMPEG, "-y", "-ss", "3", "-i", first, "-frames:v", "1",
                         "-vf", "scale=480:-2", out],
                        timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            if os.path.exists(out):
                thumb = out
        self.signals.result.emit(self.path, len(vids), thumb)


class PlaylistCard(QFrame):
    THUMB_W = 288
    THUMB_H = 162   # 16:9

    clicked = pyqtSignal(str)
    remove_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)

    def __init__(self, name, path, count=None):
        super().__init__()
        self.path = path
        self.name = name
        self._press_pos = None
        self._dragging = False
        self.setObjectName("card")
        self.setFixedWidth(self.THUMB_W + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 10)
        lay.setSpacing(8)

        self.thumb = QLabel()
        self.thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.thumb.setPixmap(_placeholder_pixmap(name, self.THUMB_W, self.THUMB_H))
        self.badge = QLabel("…", self.thumb)
        self.badge.setObjectName("badge")
        lay.addWidget(self.thumb)

        self.title = QLabel(name)
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)

        self.subtitle = QLabel("Scanning…")
        self.subtitle.setObjectName("cardSub")
        lay.addWidget(self.subtitle)

        self.set_count(count)

    def _place_badge(self):
        self.badge.adjustSize()
        self.badge.move(self.THUMB_W - self.badge.width() - 8,
                        self.THUMB_H - self.badge.height() - 8)

    def set_count(self, count):
        if count is None:
            self.badge.setText("…")
            self.subtitle.setText("Scanning…")
        else:
            self.badge.setText(f"{count} videos")
            self.subtitle.setText(f"{count} video" + ("" if count == 1 else "s"))
        self._place_badge()

    def set_thumb(self, thumb_path):
        pm = QPixmap(thumb_path)
        if not pm.isNull():
            self.thumb.setPixmap(_rounded_pixmap(pm, self.THUMB_W, self.THUMB_H))
            self.badge.raise_()
            self._place_badge()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Past the drag threshold, start a drag so cards can be rearranged.
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._press_pos is not None:
            if (event.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # A press+release without a drag is a click → open the playlist.
        if (event.button() == Qt.MouseButton.LeftButton
                and self._press_pos is not None and not self._dragging):
            self.clicked.emit(self.path)
        self._press_pos = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        self._dragging = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.path)
        drag.setMimeData(mime)
        pm = self.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(self._press_pos)
        drag.exec(Qt.DropAction.MoveAction)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_rename = menu.addAction("Rename…")
        act_remove = menu.addAction("Remove from home")
        chosen = menu.exec(event.globalPos())
        if chosen == act_rename:
            self.rename_requested.emit(self.path)
        elif chosen == act_remove:
            self.remove_requested.emit(self.path)


class _GridHost(QWidget):
    """Holds the card flow layout and accepts card drops for reordering."""
    reorder = pyqtSignal(str, str)   # dragged path, target path ("" = drop at end)

    def __init__(self):
        super().__init__()
        self.setObjectName("gridHost")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        src = event.mimeData().text()
        target = self._card_at(event.position().toPoint())
        if src and src != target:
            self.reorder.emit(src, target)
        event.acceptProposedAction()

    def _card_at(self, pos):
        w = self.childAt(pos)
        while w is not None and not isinstance(w, PlaylistCard):
            w = w.parentWidget() if w is not self else None
        return w.path if isinstance(w, PlaylistCard) else ""


class HomePage(QWidget):
    open_playlist = pyqtSignal(str)
    add_requested = pyqtSignal()
    remove_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)
    reorder = pyqtSignal(str, str)
    go_back = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("home")
        self._playlists = []       # list of shared dicts (owned by ReelPlayer)
        self._cards = {}           # path -> PlaylistCard
        self._sort = "custom"
        self._query = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 12)
        outer.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Playlists")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search playlists…")
        self.search.setFixedWidth(300)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        header.addWidget(self.search)
        self.btn_add = QPushButton("＋  Add Playlist")
        self.btn_add.setObjectName("accent")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self.add_requested.emit)
        header.addWidget(self.btn_add)
        outer.addLayout(header)

        filt = QHBoxLayout()
        filt.setSpacing(10)
        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("sort")
        self.sort_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort_combo.addItem("My order", "custom")
        self.sort_combo.addItem("Recently added", "added")
        self.sort_combo.addItem("Updated recently", "updated")
        self.sort_combo.currentIndexChanged.connect(self._on_sort)
        filt.addWidget(self.sort_combo)
        hint = QLabel("Drag cards to rearrange")
        hint.setObjectName("cardSub")
        filt.addWidget(hint)
        filt.addStretch(1)
        outer.addLayout(filt)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("homeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = _GridHost()
        host.reorder.connect(self.reorder.emit)
        self.flow = FlowLayout(host, margin=0, spacing=18)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll, 1)

        self.empty = QLabel("No playlists yet.\nClick “＋ Add Playlist” to add a folder of videos.")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.empty, 1)
        self.empty.hide()

    def set_playlists(self, playlists):
        self._playlists = playlists
        self._rebuild()

    def _on_sort(self, _i):
        self._sort = self.sort_combo.currentData()
        self._rebuild()

    def _on_search(self, text):
        self._query = text.strip().lower()
        self._rebuild()

    def _visible_items(self):
        items = list(self._playlists)   # already in the user's manual order
        if self._query:
            items = [p for p in items if self._query in p["name"].lower()]
        if self._sort == "updated":
            items.sort(key=lambda p: p.get("_mtime", 0), reverse=True)
        elif self._sort == "added":
            items.sort(key=lambda p: p.get("added", 0), reverse=True)
        # "custom" keeps the manual list order as-is.
        return items

    def set_sort_custom(self):
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(0)   # "My order"
        self.sort_combo.blockSignals(False)
        self._sort = "custom"

    def _rebuild(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()
        items = self._visible_items()
        for p in items:
            card = PlaylistCard(p["name"], p["path"], p.get("_count"))
            if p.get("_thumb"):
                card.set_thumb(p["_thumb"])
            card.clicked.connect(self.open_playlist.emit)
            card.remove_requested.connect(self.remove_requested.emit)
            card.rename_requested.connect(self.rename_requested.emit)
            self._cards[p["path"]] = card
            self.flow.addWidget(card)
        has_any = bool(self._playlists)
        self.scroll.setVisible(has_any)
        self.empty.setVisible(not has_any)

    def update_scan(self, path, count, thumb):
        card = self._cards.get(path)
        if card is not None:
            card.set_count(count)
            if thumb:
                card.set_thumb(thumb)


class ReelPlayer(QMainWindow):
    # mpv's OSC callbacks fire on its own thread; these signals hop the
    # resulting UI actions back onto the Qt main thread (a queued cross-thread
    # connection) so we never touch widgets from the wrong thread.
    _mpv_shutdown = pyqtSignal()
    _mpv_minimize = pyqtSignal()
    _mpv_maximize = pyqtSignal(bool)
    _mpv_aspect = pyqtSignal(float)
    _mpv_drag = pyqtSignal(bool)   # True on button-down (start), False on up (end)
    _mpv_pause = pyqtSignal(bool)  # reflects the player's pause state to the buttons
    _mpv_click = pyqtSignal()      # single left-click on the docked video body
    _mpv_dblclick = pyqtSignal()   # double left-click on the docked video body

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

        self.playlist_paths = []
        self.current_index = -1
        self.detached = False
        # Last known playback position, kept live via a time-pos observer. Used
        # as a fallback when re-docking via the OSC close button, where the core
        # is already gone and its time_pos can no longer be queried.
        self._last_time_pos = 0
        # Set while we tear a player down on purpose, so the shutdown signal
        # that mpv fires during our own terminate() isn't mistaken for the user
        # clicking the OSC close button.
        self._closing_player = False

        # Manual drag of the detached window: while the left button is held on
        # the video body, a timer moves the window to follow the global cursor.
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(8)
        self._drag_timer.timeout.connect(self._drag_follow)
        self._drag_origin_cursor = None
        self._drag_origin_win = None

        self.detached_window = DetachedVideoWindow(on_close=self._attach)
        self._mpv_shutdown.connect(self._on_mpv_shutdown)
        self._mpv_minimize.connect(self._on_mpv_minimize)
        self._mpv_maximize.connect(self._on_mpv_maximize)
        self._mpv_aspect.connect(self._on_mpv_aspect)
        self._mpv_drag.connect(self._on_mpv_drag)
        self._mpv_pause.connect(self._on_mpv_pause)
        self._mpv_click.connect(self._on_video_click)
        self._mpv_dblclick.connect(self._on_video_dblclick)

        # Click-to-pause is debounced so a double-click (fullscreen toggle)
        # doesn't also flip pause. The delay must exceed mpv's double-click
        # window (input-doubleclick-time, set to 220 ms below) so a pending
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
        self._scan_signals = _ScanSignals()
        self._scan_signals.result.connect(self._on_scan_result)

        self._build_ui()
        self._build_player()
        self._build_shortcuts()

        self.home_page.set_playlists(self.playlists)
        self._scan_all()

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
    def _fix_locale(self):
        # Qt resets the process locale during ordinary widget interaction (slider
        # drags, dialogs, etc), not just at startup. libmpv segfaults if a number
        # reaches it while LC_NUMERIC isn't "C", so we re-assert this defensively
        # right before every call into mpv that involves a number.
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except Exception:
            pass

    def _create_mpv_core(self, target_widget, window_controls=False):
        self._fix_locale()
        # mpv renders into the given native Qt widget (docked surface, or the
        # detached window's video_holder). The built-in OSC is disabled in favour
        # of uosc (loaded from our bundled MPV_CONFIG_DIR), which draws a modern
        # YouTube-style seek bar and handles seeking/dragging natively; the
        # play/pause/fullscreen controls live on the app's own Qt buttons.
        kwargs = dict(
            wid=str(int(target_widget.winId())),
            vo="gpu",
            hwdec="no",
            input_default_bindings=True,
            input_vo_keyboard=False,
            input_doubleclick_time=220,
            osc=False,
            keep_open="yes",
        )
        # Load uosc + its fonts/options from the bundled config dir. config=True
        # makes mpv auto-load scripts/ and fonts/ from config_dir; there's no
        # mpv.conf there, so it doesn't otherwise change playback behaviour.
        if os.path.isdir(MPV_CONFIG_DIR):
            kwargs["config"] = True
            kwargs["config_dir"] = MPV_CONFIG_DIR
        if window_controls:
            # Turn off mpv's own window dragging: for an embedded window it can
            # only try (and fail) to drag mpv's child window, and it swallows the
            # MBTN_LEFT press our drag-to-move binding needs.
            kwargs["window_dragging"] = "no"
        self.player = mpv.MPV(**kwargs)

        @self.player.property_observer("eof-reached")
        def _eof(_name, value):
            if value:
                QTimer.singleShot(50, self.play_next)

        @self.player.property_observer("time-pos")
        def _time_pos(_name, value):
            if value is not None:
                self._last_time_pos = value

        @self.player.property_observer("pause")
        def _pause(_name, value):
            self._mpv_pause.emit(bool(value))

        if window_controls:
            # Detached window: the OSC's own fading buttons drive the frameless
            # window. Close issues `quit` (→ re-dock); minimize/maximize toggle
            # mpv properties we mirror onto the real Qt window.
            @self.player.event_callback("shutdown")
            def _shutdown(_event):
                self._mpv_shutdown.emit()

            @self.player.property_observer("window-minimized")
            def _minimized(_name, value):
                if value:
                    self._mpv_minimize.emit()

            @self.player.property_observer("window-maximized")
            def _maximized(_name, value):
                self._mpv_maximize.emit(bool(value))

            # Fit the frameless window to the video's real aspect ratio (e.g. a
            # 1440×1080 file makes a 4:3 window) so there are no black bars.
            @self.player.property_observer("video-params")
            def _vparams(_name, value):
                if value:
                    dw, dh = value.get("dw"), value.get("dh")
                    if dw and dh:
                        self._mpv_aspect.emit(dw / dh)

            # Let the user move the window by dragging the video body. mpv routes
            # MBTN_LEFT to us (in default mode, so the OSC's own forced binding
            # still wins over its seek bar / buttons); we get both the press and
            # the release, and drive a manual follow-the-cursor move in between.
            @self.player.key_binding("MBTN_LEFT", mode="default")
            def _drag(state, *_):
                if state and state[0] == "d":
                    self._mpv_drag.emit(True)
                elif state and state[0] == "u":
                    self._mpv_drag.emit(False)
        else:
            # Docked video: single left-click on the body toggles pause,
            # double-click toggles fullscreen. mpv owns the embedded window, so
            # Qt never sees these clicks — bind them on mpv (default mode, so
            # uosc's forced seek-bar bindings still win over the timeline).
            @self.player.key_binding("MBTN_LEFT", mode="default")
            def _click(state, *_):
                if state and state[0] == "d":
                    self._mpv_click.emit()

            @self.player.key_binding("MBTN_LEFT_DBL", mode="default")
            def _dblclick(state, *_):
                if state and state[0] == "d":
                    self._mpv_dblclick.emit()

    def _build_player(self):
        self._create_mpv_core(self.surface)
        self.player.volume = 80

    def _safe_seek(self, pos):
        self._fix_locale()
        try:
            self.player.seek(pos, reference="absolute")
        except Exception:
            pass

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
        was_empty = not self.playlist_paths
        for p in paths:
            if os.path.isdir(p):
                for root, _dirs, entries in os.walk(p):
                    for entry in sorted(entries):
                        if os.path.splitext(entry)[1].lower() in VIDEO_EXTS:
                            self._append_item(os.path.join(root, entry))
            elif os.path.splitext(p)[1].lower() in VIDEO_EXTS:
                self._append_item(p)
        if was_empty and self.playlist_paths:
            self.play_index(0)
        self._save_state()

    def _append_item(self, path):
        self.playlist_paths.append(path)
        item = QListWidgetItem(os.path.basename(path))
        item.setToolTip(path)
        self.playlist_widget.addItem(item)

    def remove_selected(self):
        row = self.playlist_widget.currentRow()
        if row < 0:
            return
        self.playlist_widget.takeItem(row)
        del self.playlist_paths[row]
        if row == self.current_index:
            self.player.command("stop")
            self.current_index = -1
        elif row < self.current_index:
            self.current_index -= 1
        self._save_state()

    def clear_playlist(self):
        self.player.command("stop")
        self.playlist_widget.clear()
        self.playlist_paths.clear()
        self.current_index = -1
        self._save_state()

    # ---------- session persistence ----------
    def _save_state(self):
        """Persist the playlist, which video is current, and its position so the
        next launch resumes exactly where the user left off. Written atomically
        and best-effort (never raises into the UI)."""
        try:
            cur = None
            if 0 <= self.current_index < len(self.playlist_paths):
                cur = self.playlist_paths[self.current_index]
            try:
                pos = self.player.time_pos
            except Exception:
                pos = None
            if pos is None:
                pos = self._last_time_pos
            try:
                vol = float(self.player.volume)
            except Exception:
                vol = 80.0
            data = {
                "playlist": list(self.playlist_paths),
                "current_path": cur,
                "position": float(pos or 0),
                "volume": vol,
            }
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, STATE_FILE)
        except Exception:
            pass

    def restore_session(self):
        """Reload the saved playlist and cue the last-played video, paused at the
        position it was left at (files that no longer exist are dropped)."""
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
        except Exception:
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
        except Exception:
            pass
        self.current_index = idx
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
        except Exception:
            raw = []
        out = []
        for e in raw:
            path = e.get("path")
            if not path or not os.path.isdir(path):
                continue
            try:
                mtime = os.path.getmtime(path)
            except Exception:
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
        except Exception:
            pass

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
        except Exception:
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
        playing_path = self.playlist_paths[self.current_index] if 0 <= self.current_index < len(self.playlist_paths) else None
        self.playlist_paths = new_order
        if playing_path in new_order:
            self.current_index = new_order.index(playing_path)
        self._save_state()

    # ---------- playback control ----------
    def play_index(self, index):
        if not (0 <= index < len(self.playlist_paths)):
            return
        self._fix_locale()
        self.current_index = index
        path = self.playlist_paths[index]
        self.player.play(path)
        self.player.pause = False
        self._last_time_pos = 0
        self.playlist_widget.setCurrentRow(index)
        self.setWindowTitle(f"{APP_NAME} — {os.path.basename(path)}")
        self._save_state()

    def play_next(self):
        if self.current_index + 1 < len(self.playlist_paths):
            self.play_index(self.current_index + 1)

    def play_previous(self):
        if self.current_index - 1 >= 0:
            self.play_index(self.current_index - 1)

    def toggle_pause(self):
        if self.current_index == -1 and self.playlist_paths:
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
        self._fix_locale()
        try:
            self.player.seek(secs, reference="relative")
        except Exception:
            pass

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
        if 0 <= self.current_index < len(self.playlist_paths):
            path = self.playlist_paths[self.current_index]
            try:
                pos = self.player.time_pos or 0
            except Exception:
                pos = self._last_time_pos
            try:
                was_paused = bool(self.player.pause)
            except Exception:
                pass
        try:
            vol = self.player.volume
        except Exception:
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
        try:
            self.player.terminate()
        except Exception:
            pass

        # Show the frameless window (and realize its native video_holder) before
        # embedding — querying winId() pre-show hands mpv a preliminary native
        # window Qt may still replace, which used to crash. Showing first avoids
        # that.
        self.detached_window.show()
        self.detached_window.raise_()
        self.detached_window.activateWindow()

        self._create_mpv_core(self.detached_window.video_holder, window_controls=True)
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
        try:
            self.player.terminate()
        except Exception:
            pass

        self.detached_window.hide()

        self._create_mpv_core(self.surface)
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
        try:
            self.player.terminate()
        except Exception:
            pass
        try:
            self.detached_window._force_close = True
            self.detached_window.close()
        except Exception:
            pass
        event.accept()


def main():
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


if __name__ == "__main__":
    main()
