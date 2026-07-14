"""The home / playlists page: a searchable, sortable, drag-reorderable grid of
playlist cards."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from .flow_layout import FlowLayout
from .playlist_card import PlaylistCard


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
