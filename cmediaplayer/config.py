"""Paths, constants, and app metadata — the single place these are defined.

APP_DIR is the app's install/source root: the directory that holds the bundled
``icons/`` and ``mpv/`` folders. Since this module lives one level down inside
the ``cmediaplayer`` package, the root is the package's parent directory. This
resolves correctly both when running from a source checkout and when installed
(install.sh lays the package next to icons/ and mpv/).
"""
import os
import shutil

APP_NAME = "C Media Player"

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(_PKG_DIR)
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
