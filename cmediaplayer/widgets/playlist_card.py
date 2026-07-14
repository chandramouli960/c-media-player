"""A single playlist card on the home page: thumbnail, title, video count,
plus click-to-open, drag-to-reorder, and a right-click context menu."""
from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QLabel, QMenu, QVBoxLayout,
)

from ..utils import placeholder_pixmap, rounded_pixmap


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
        self.thumb.setPixmap(placeholder_pixmap(name, self.THUMB_W, self.THUMB_H))
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
            self.thumb.setPixmap(rounded_pixmap(pm, self.THUMB_W, self.THUMB_H))
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
