# C Media Player

A local video player built with **PyQt6** and **libmpv** — playlist, drag & drop,
and real Picture-in-Picture. Installs as a proper desktop app with an icon,
launches from your app grid, and can be set as your default video player.

## Install (any major Linux distro)

```bash
chmod +x install.sh
./install.sh
```

The installer auto-detects your package manager, so the same command works on:

| Distro family | Package manager |
|---|---|
| Debian / Ubuntu / Mint / Pop!_OS | `apt` |
| Fedora / RHEL / Rocky / Alma | `dnf` |
| Arch / CachyOS / Manjaro / EndeavourOS | `pacman` |
| openSUSE | `zypper` |

It works on any desktop environment (GNOME, KDE, XFCE, …) — it installs a
standard `.desktop` entry and hicolor icons that every DE picks up.

This will:
1. Install `libmpv`, `PyQt6`, and `ffmpeg` using your distro's package manager
2. Copy the app to `~/.local/share/c-media-player`
3. Create a virtual environment and install `python-mpv` inside it
4. Add a launcher command: `c-media-player`
5. Install the app icon into your icon theme
6. Create a desktop entry so it shows up in your GNOME app grid, with an "Open With" entry for video files
7. Ask whether to set it as your **default video player**

## Launch

- From the GNOME app grid — search "C Media Player"
- From a terminal: `c-media-player`
- With files: `c-media-player ~/Videos/some_folder/*.mp4`
- Right-click any video → **Open With → C Media Player**

## Set as default later

If you skip it during install, or want to change it back:

```bash
xdg-mime default c-media-player.desktop video/mp4
xdg-mime default c-media-player.desktop video/x-matroska
# repeat for other formats you use, e.g. video/webm, video/x-msvideo
```

Or right-click a video file in **Files (Nautilus)** → Properties → Open With → set C Media Player as default.

## Features
- Add files/folders or drag & drop straight into the window
- Auto-advancing playlist, drag to reorder
- Real Picture-in-Picture: shrinks to a small always-on-top corner window
- Keyboard shortcuts: `Space` play/pause, `←`/`→` seek 5s, `N`/`P` next/prev, `F` fullscreen, `M` mute, `Esc` exit PiP

## Uninstall

```bash
rm -rf ~/.local/share/c-media-player
rm ~/.local/bin/c-media-player
rm ~/.local/share/applications/c-media-player.desktop
rm ~/.local/share/icons/hicolor/*/apps/c-media-player.png
rm ~/.local/share/icons/hicolor/scalable/apps/c-media-player.svg
update-desktop-database ~/.local/share/applications
```

## Development

The app is a small Python package, `cmediaplayer/`, with `main.py` as a thin
launcher. See **[ARCHITECTURE.md](ARCHITECTURE.md)** for how the pieces fit
together (libmpv lives behind `PlayerCore`; the play queue lives in `Playlist`;
`ReelPlayer` is the controller).

Run from a source checkout (needs `PyQt6`, `python-mpv`, and `libmpv` + `ffmpeg`
from your distro):

```bash
python main.py                    # or: python main.py ~/Videos/*.mp4
CMP_DEBUG=1 python main.py        # verbose logging for troubleshooting
```

Run the unit tests (pure logic — no Qt or mpv needed):

```bash
python -m unittest discover -s tests
```

## Credits

Bundles [uosc](https://github.com/tomasklaen/uosc) (the on-screen seek bar) in
`mpv/`. Playback is powered by [mpv](https://mpv.io/) / libmpv.

## License

Released under the [MIT License](LICENSE). Replace the copyright line in
`LICENSE` with your name if you publish your own fork.
