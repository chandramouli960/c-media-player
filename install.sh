#!/usr/bin/env bash
# Installer for C Media Player (CachyOS / Arch-based systems)
set -e

APP_ID="c-media-player"
APP_NAME="C Media Player"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/${APP_ID}"
BIN_DIR="$HOME/.local/bin"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "==> Installing ${APP_NAME}"

# 1. System dependencies (mpv engine + Qt bindings)
if ! pacman -Qi mpv >/dev/null 2>&1 || ! pacman -Qi python-pyqt6 >/dev/null 2>&1; then
    echo "==> Installing system packages (mpv, python-pyqt6) via pacman"
    sudo pacman -S --needed mpv python-pyqt6
else
    echo "==> mpv and python-pyqt6 already installed, skipping"
fi

# 2. Copy app files
echo "==> Copying app files to ${INSTALL_DIR}"
mkdir -p "$INSTALL_DIR"
cp "$SRC_DIR/main.py" "$INSTALL_DIR/"
# Bundled mpv config dir carrying uosc (the seek bar) + its fonts/options.
rm -rf "$INSTALL_DIR/mpv"
cp -r "$SRC_DIR/mpv" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/mpv/scripts/uosc/bin/ziggy-linux" 2>/dev/null || true
cp -r "$SRC_DIR/icons" "$INSTALL_DIR/"
cp "$SRC_DIR/icon.svg" "$INSTALL_DIR/"

# 3. Python venv with access to system PyQt6, plus python-mpv installed inside
echo "==> Setting up virtual environment"
python -m venv "$INSTALL_DIR/venv" --system-site-packages
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet python-mpv

# 4. Launcher script
echo "==> Creating launcher at ${BIN_DIR}/${APP_ID}"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/${APP_ID}" <<EOF
#!/usr/bin/env bash
source "${INSTALL_DIR}/venv/bin/activate"
exec python "${INSTALL_DIR}/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/${APP_ID}"

# 5. Install icons into the hicolor theme so GNOME/other DEs pick it up by name
echo "==> Installing icons"
for size in 16 32 48 64 128 256; do
    dest="${ICON_THEME_DIR}/${size}x${size}/apps"
    mkdir -p "$dest"
    cp "$SRC_DIR/icons/icon-${size}.png" "${dest}/${APP_ID}.png"
done
mkdir -p "${ICON_THEME_DIR}/scalable/apps"
cp "$SRC_DIR/icon.svg" "${ICON_THEME_DIR}/scalable/apps/${APP_ID}.svg"

# 6. Desktop entry (app launcher + default-app + "Open With" integration)
echo "==> Creating desktop entry"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/${APP_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=Local video player with playlist and Picture-in-Picture
Exec=${BIN_DIR}/${APP_ID} %U
Icon=${APP_ID}
Terminal=false
Categories=AudioVideo;Video;Player;
MimeType=video/mp4;video/x-matroska;video/webm;video/x-msvideo;video/quicktime;video/x-flv;video/x-ms-wmv;video/mpeg;video/3gpp;video/ogg;
StartupWMClass=${APP_NAME}
EOF

# 7. Refresh desktop/icon caches so the app grid picks everything up immediately
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICON_THEME_DIR" 2>/dev/null || true

echo ""
echo "==> Done. ${APP_NAME} is installed."
echo "    Launch from your app grid, or run: ${APP_ID}"
echo ""

# 8. Offer to set as default video player
read -p "Set ${APP_NAME} as the default app for video files now? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    if ! command -v xdg-mime >/dev/null 2>&1; then
        echo "xdg-mime not found — install 'xdg-utils' first, then re-run:"
        echo "  sudo pacman -S xdg-utils"
    else
        for mime in video/mp4 video/x-matroska video/webm video/x-msvideo video/quicktime video/x-flv video/x-ms-wmv video/mpeg video/3gpp video/ogg; do
            xdg-mime default "${APP_ID}.desktop" "$mime"
        done
        echo "==> Set as default for common video types."
    fi
fi

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    echo ""
    echo "NOTE: ${BIN_DIR} is not on your PATH."
    echo "Add this to your fish config (~/.config/fish/config.fish):"
    echo "  fish_add_path ${BIN_DIR}"
fi
