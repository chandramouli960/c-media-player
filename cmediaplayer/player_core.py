"""PlayerCore — owns the libmpv instance and its whole lifecycle.

This isolates every direct interaction with libmpv (creation, teardown,
seeking, the locale workaround) and, crucially, the thread hand-off: mpv fires
its property observers and key bindings on *its own* thread, so touching Qt
widgets from there would crash. PlayerCore is a ``QObject`` whose observers only
ever ``emit`` Qt signals; because the connections are queued, the slots run
safely back on the Qt main thread. ``ReelPlayer`` connects to these signals and
never talks to mpv's callback threads directly.
"""
import locale
import logging
import os

from PyQt6.QtCore import QObject, pyqtSignal

import mpv

from .config import MPV_CONFIG_DIR

log = logging.getLogger(__name__)


class PlayerCore(QObject):
    # Emitted from mpv's threads, delivered (queued) on the Qt main thread.
    eof_reached = pyqtSignal()
    pause_changed = pyqtSignal(bool)     # reflects the player's pause state
    shutdown = pyqtSignal()              # detached window: OSC close / `q`
    minimized = pyqtSignal()             # detached window: OSC minimize
    maximized = pyqtSignal(bool)         # detached window: OSC maximize toggle
    aspect = pyqtSignal(float)           # video display aspect ratio (dw/dh)
    drag = pyqtSignal(bool)              # left button down (True) / up (False)
    click = pyqtSignal()                 # single left-click on docked video
    dblclick = pyqtSignal()             # double left-click on docked video

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        # Last known playback position, kept live via a time-pos observer. Used
        # as a fallback when re-docking, where the core is already gone and its
        # time_pos can no longer be queried.
        self.last_time_pos = 0

    # ---- locale guard -----------------------------------------------------
    @staticmethod
    def fix_locale():
        # Qt resets the process locale during ordinary widget interaction (slider
        # drags, dialogs, etc), not just at startup. libmpv segfaults if a number
        # reaches it while LC_NUMERIC isn't "C", so we re-assert this defensively
        # right before every call into mpv that involves a number.
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except locale.Error:
            pass

    # ---- lifecycle --------------------------------------------------------
    def create(self, target_widget, window_controls=False):
        """(Re)create the mpv core rendering into ``target_widget``.

        ``window_controls`` selects the detached-window binding set (OSC window
        buttons + drag-to-move) instead of the docked one (click-to-pause,
        double-click-to-fullscreen)."""
        self.fix_locale()
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
                self.eof_reached.emit()

        @self.player.property_observer("time-pos")
        def _time_pos(_name, value):
            if value is not None:
                self.last_time_pos = value

        @self.player.property_observer("pause")
        def _pause(_name, value):
            self.pause_changed.emit(bool(value))

        if window_controls:
            # Detached window: the OSC's own fading buttons drive the frameless
            # window. Close issues `quit` (→ re-dock); minimize/maximize toggle
            # mpv properties we mirror onto the real Qt window.
            @self.player.event_callback("shutdown")
            def _shutdown(_event):
                self.shutdown.emit()

            @self.player.property_observer("window-minimized")
            def _minimized(_name, value):
                if value:
                    self.minimized.emit()

            @self.player.property_observer("window-maximized")
            def _maximized(_name, value):
                self.maximized.emit(bool(value))

            # Fit the frameless window to the video's real aspect ratio (e.g. a
            # 1440×1080 file makes a 4:3 window) so there are no black bars.
            @self.player.property_observer("video-params")
            def _vparams(_name, value):
                if value:
                    dw, dh = value.get("dw"), value.get("dh")
                    if dw and dh:
                        self.aspect.emit(dw / dh)

            # Let the user move the window by dragging the video body. mpv routes
            # MBTN_LEFT to us (in default mode, so the OSC's own forced binding
            # still wins over its seek bar / buttons); we get both the press and
            # the release, and drive a manual follow-the-cursor move in between.
            @self.player.key_binding("MBTN_LEFT", mode="default")
            def _drag(state, *_):
                if state and state[0] == "d":
                    self.drag.emit(True)
                elif state and state[0] == "u":
                    self.drag.emit(False)
        else:
            # Docked video: single left-click on the body toggles pause,
            # double-click toggles fullscreen. mpv owns the embedded window, so
            # Qt never sees these clicks — bind them on mpv (default mode, so
            # uosc's forced seek-bar bindings still win over the timeline).
            @self.player.key_binding("MBTN_LEFT", mode="default")
            def _click(state, *_):
                if state and state[0] == "d":
                    self.click.emit()

            @self.player.key_binding("MBTN_LEFT_DBL", mode="default")
            def _dblclick(state, *_):
                if state and state[0] == "d":
                    self.dblclick.emit()

        return self.player

    def terminate(self):
        """Tear down the mpv core. Safe to call when there is nothing to tear
        down; never raises into the caller."""
        if self.player is None:
            return
        try:
            self.player.terminate()
        except Exception as e:  # noqa: BLE001 — mpv can raise assorted C errors
            log.debug("mpv terminate raised: %s", e)

    # ---- imperative helpers used by the controller ------------------------
    def seek(self, pos, reference="absolute"):
        self.fix_locale()
        try:
            self.player.seek(pos, reference=reference)
        except Exception as e:  # noqa: BLE001
            log.debug("seek(%s, %s) failed: %s", pos, reference, e)
