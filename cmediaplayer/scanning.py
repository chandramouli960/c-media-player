"""Off-thread folder scanning + thumbnail generation for the home page.

Counting videos and shelling out to ffmpeg are slow, so they run on a
``QThreadPool`` worker and report back to the UI thread through a signal.
"""
import hashlib
import logging
import os
import subprocess

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from .config import FFMPEG, THUMB_DIR, VIDEO_EXTS

log = logging.getLogger(__name__)


class ScanSignals(QObject):
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
        except OSError as e:
            log.debug("scan walk failed for %s: %s", self.path, e)
        thumb = ""
        if vids and FFMPEG:
            first = vids[0]
            try:
                stamp = str(int(os.path.getmtime(first)))
            except OSError:
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
                except (OSError, subprocess.SubprocessError) as e:
                    log.debug("thumbnail generation failed for %s: %s", first, e)
            if os.path.exists(out):
                thumb = out
        self.signals.result.emit(self.path, len(vids), thumb)
