"""C Media Player — a lightweight local video player with playlist and
Picture-in-Picture, built with PyQt6 + libmpv.

The package is split into focused modules:

    config        paths, constants, and app metadata
    style         the Qt stylesheet
    utils         small pure helpers (time formatting, pixmap drawing)
    scanning      off-thread folder scan + thumbnail worker
    playlist      the play queue model (single source of truth)
    player_core   owns the libmpv instance and its lifecycle/signals
    widgets/      the custom Qt widgets (video surface, home page, cards…)
    app           the main window (ReelPlayer) that wires it all together
"""
import os

# --- mpv/Qt window-embedding fix --------------------------------------------
# This MUST run before PyQt6 (or libmpv) is imported anywhere in the package.
# Because importing any submodule executes this package __init__ first, setting
# it here guarantees the ordering no matter which entry point is used.
#
# mpv's window embedding (the `wid` parameter in player_core) only works under
# X11/XWayland. On a native Wayland Qt platform, embedding silently fails and
# mpv opens its own separate top-level window (the "two title bars" bug).
# Forcing xcb fixes Qt's side.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
# libmpv makes its own, independent backend choice: if it still sees
# WAYLAND_DISPLAY it opens its own native Wayland window regardless of Qt,
# ignoring `wid` entirely. Hiding the variable forces it onto the same X11 path
# so embedding actually works.
os.environ.pop("WAYLAND_DISPLAY", None)

__version__ = "1.0.0"
__app_name__ = "C Media Player"
