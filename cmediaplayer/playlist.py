"""The play queue — the single source of truth for what's queued and what's
playing.

Previously the ordered paths and the "currently playing" index lived as loose
attributes on the main window, mutated inline alongside the QListWidget in
several places. The fiddly, easy-to-get-wrong part is keeping ``current_index``
pointing at the same video when items are removed or reordered; that logic now
lives here, in one small, testable place. The window keeps its QListWidget as a
pure view and drives every change through these methods.
"""


class Playlist:
    def __init__(self):
        self.paths = []
        self.current_index = -1

    def __len__(self):
        return len(self.paths)

    @property
    def is_empty(self):
        return not self.paths

    @property
    def current_path(self):
        if 0 <= self.current_index < len(self.paths):
            return self.paths[self.current_index]
        return None

    def append(self, path):
        """Append one path to the end of the queue."""
        self.paths.append(path)

    def clear(self):
        self.paths.clear()
        self.current_index = -1

    def remove(self, row):
        """Remove the item at ``row``.

        Returns ``True`` if that row was the currently playing item (so the
        caller should stop playback); ``False`` otherwise. The current index is
        shifted so it keeps pointing at the same video."""
        if not (0 <= row < len(self.paths)):
            return False
        was_current = row == self.current_index
        del self.paths[row]
        if was_current:
            self.current_index = -1
        elif row < self.current_index:
            self.current_index -= 1
        return was_current

    def set_order(self, new_order):
        """Adopt a new ordering (after a drag-reorder in the view), keeping the
        same video current by identity."""
        playing = self.current_path
        self.paths = list(new_order)
        if playing is not None and playing in self.paths:
            self.current_index = self.paths.index(playing)

    def set_current(self, index):
        self.current_index = index

    def has_next(self):
        return self.current_index + 1 < len(self.paths)

    def has_previous(self):
        return self.current_index - 1 >= 0
