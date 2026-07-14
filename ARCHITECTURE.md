# Architecture

C Media Player is a PyQt6 desktop app that embeds **libmpv** for playback. The
code is organised as a small package, `cmediaplayer/`, with one responsibility
per module. `main.py` at the repo root is just a launcher.

```
main.py                     thin entry point → cmediaplayer.app:main
cmediaplayer/
  __init__.py               package init + the X11 window-embedding env fix
  config.py                 paths, constants, app metadata (one source of truth)
  style.py                  the Qt stylesheet (frosted-glass theme)
  utils.py                  pure helpers: time formatting, pixmap drawing
  scanning.py               off-thread folder scan + ffmpeg thumbnail worker
  playlist.py               the play-queue model (order + current index)
  player_core.py            owns the libmpv instance, its lifecycle & signals
  widgets/
    video.py                VideoSurface (docked) + DetachedVideoWindow (PiP)
    flow_layout.py          wrapping flow layout for the home grid
    playlist_card.py        one playlist card (thumb, drag, context menu)
    home_page.py            the searchable/sortable/reorderable card grid
  app.py                    ReelPlayer (main window) — the controller + main()
tests/
  test_playlist.py          unit tests for the queue's index bookkeeping
```

## The three load-bearing ideas

### 1. libmpv lives behind `PlayerCore`

libmpv fires its property observers and key bindings on **its own threads**.
Touching Qt widgets from there would crash. `PlayerCore` is a `QObject` whose
observers only ever `emit` Qt signals; the connections are queued, so the slots
run back on the Qt main thread. It also owns the one genuinely dangerous
workaround — re-asserting `LC_NUMERIC=C` before numeric calls, because Qt resets
the locale during normal use and libmpv then misparses numbers and segfaults.

`ReelPlayer` connects to `PlayerCore`'s signals (`eof_reached`, `pause_changed`,
`shutdown`, `aspect`, `drag`, `click`, …) and never talks to mpv's callback
threads directly.

### 2. The play queue lives in `Playlist`

`Playlist` is the single source of truth for what's queued and what's playing.
The fiddly part — keeping `current_index` pointing at the same video when items
are removed or reordered — is all here, in one small, unit-tested place
(`tests/test_playlist.py`). The window keeps its `QListWidget` as a pure view
and drives every change through `Playlist` methods.

### 3. `ReelPlayer` is the controller

`app.py` builds the UI, holds a `Playlist` and a `PlayerCore`, and wires them to
the widgets and to window behaviour: detach/attach (Picture-in-Picture),
fullscreen, keyboard shortcuts, drag-and-drop, and periodic state persistence.
It stays focused on *wiring*, because the hard mechanics live in the two helpers
above.

## Window embedding (why `__init__.py` sets env vars)

mpv's `wid` embedding only works under X11/XWayland. On a native Wayland Qt
platform, embedding silently fails and mpv opens its own top-level window. The
package `__init__` forces `QT_QPA_PLATFORM=xcb` and unsets `WAYLAND_DISPLAY`
**before** PyQt6/libmpv are imported — importing any submodule runs the package
`__init__` first, which guarantees the ordering.

## Running the tests

```bash
python -m unittest discover -s tests
```

The unit tests are pure logic (no Qt/mpv), so they run anywhere. For a fuller
check that construction and mpv embedding still work, the app can be built
headless with `QT_QPA_PLATFORM=offscreen`.
