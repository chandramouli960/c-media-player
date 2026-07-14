"""The two surfaces mpv renders into: the docked ``VideoSurface`` and the
frameless, self-managed ``DetachedVideoWindow`` (Picture-in-Picture)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..config import APP_NAME, ICON_PATH


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
        • drag the VIDEO itself    → move   (driven by mpv; see the MBTN_LEFT
                                            binding in PlayerCore.create)

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
        # mpv's MBTN_LEFT binding (see PlayerCore.create / ReelPlayer._on_mpv_drag).
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
