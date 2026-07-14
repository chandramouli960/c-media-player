"""Unit tests for the Playlist model — specifically the current-index
bookkeeping that used to be scattered, inline, and easy to get wrong.

Run:  python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cmediaplayer.playlist import Playlist


class PlaylistTest(unittest.TestCase):
    def make(self, n=4, current=None):
        pl = Playlist()
        for i in range(n):
            pl.append(f"/v/{i}.mp4")
        if current is not None:
            pl.set_current(current)
        return pl

    def test_append_and_len(self):
        pl = self.make(3)
        self.assertEqual(len(pl), 3)
        self.assertEqual(pl.paths, ["/v/0.mp4", "/v/1.mp4", "/v/2.mp4"])

    def test_current_path(self):
        pl = self.make(3, current=1)
        self.assertEqual(pl.current_path, "/v/1.mp4")
        pl.set_current(-1)
        self.assertIsNone(pl.current_path)

    def test_remove_before_current_shifts_index(self):
        pl = self.make(4, current=2)          # playing /v/2.mp4
        was_current = pl.remove(0)            # remove /v/0.mp4
        self.assertFalse(was_current)
        self.assertEqual(pl.current_index, 1)  # still /v/2.mp4
        self.assertEqual(pl.current_path, "/v/2.mp4")

    def test_remove_after_current_keeps_index(self):
        pl = self.make(4, current=1)
        was_current = pl.remove(3)
        self.assertFalse(was_current)
        self.assertEqual(pl.current_index, 1)
        self.assertEqual(pl.current_path, "/v/1.mp4")

    def test_remove_current_signals_and_clears(self):
        pl = self.make(4, current=2)
        was_current = pl.remove(2)
        self.assertTrue(was_current)
        self.assertEqual(pl.current_index, -1)
        self.assertIsNone(pl.current_path)

    def test_remove_out_of_range_is_noop(self):
        pl = self.make(2, current=0)
        self.assertFalse(pl.remove(5))
        self.assertFalse(pl.remove(-1))
        self.assertEqual(len(pl), 2)

    def test_reorder_keeps_same_video_current(self):
        pl = self.make(3, current=0)          # playing /v/0.mp4
        pl.set_order(["/v/2.mp4", "/v/1.mp4", "/v/0.mp4"])
        self.assertEqual(pl.current_index, 2)  # /v/0.mp4 moved to the end
        self.assertEqual(pl.current_path, "/v/0.mp4")

    def test_clear_resets(self):
        pl = self.make(3, current=1)
        pl.clear()
        self.assertEqual(len(pl), 0)
        self.assertEqual(pl.current_index, -1)
        self.assertTrue(pl.is_empty)

    def test_has_next_previous(self):
        pl = self.make(3, current=1)
        self.assertTrue(pl.has_next())
        self.assertTrue(pl.has_previous())
        pl.set_current(2)
        self.assertFalse(pl.has_next())
        pl.set_current(0)
        self.assertFalse(pl.has_previous())


if __name__ == "__main__":
    unittest.main()
