# C Media Player

A local video player built with **PyQt6** and **libmpv** — playlist, drag & drop,
and real Picture-in-Picture. Installs as a proper desktop app with an icon,
launches from your app grid, and can be set as your default video player.

## Install (CachyOS / Arch)

```bash
chmod +x install.sh
./install.sh
```

This will:
1. Install `mpv` and `python-pyqt6` via pacman (only if missing)
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
