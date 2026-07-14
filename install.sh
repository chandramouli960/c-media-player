#!/usr/bin/env bash
# Installer for C Media Player.
# Works on all major Linux distros — auto-detects the package manager
# (apt / dnf / pacman / zypper) and installs the right package names.
set -e

APP_ID="c-media-player"
APP_NAME="C Media Player"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/${APP_ID}"
BIN_DIR="$HOME/.local/bin"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "==> Installing ${APP_NAME}"

# 1. System dependencies: libmpv (playback engine), PyQt6 (GUI bindings),
#    python venv + pip (to install python-mpv), and ffmpeg (thumbnails).
#    Package names differ per distro, so detect the package manager first.
if command -v apt >/dev/null 2>&1; then
    echo "==> Detected apt (Debian / Ubuntu / Mint / Pop!_OS)"
    sudo apt update
    sudo apt install -y mpv python3-pyqt6 python3-venv python3-pip ffmpeg
    # libmpv is a separate package; the version suffix changed across releases.
    sudo apt install -y libmpv2 || sudo apt install -y libmpv1 || \
        echo "!! Could not install libmpv2/libmpv1 — install your distro's libmpv package."
elif command -v dnf >/dev/null 2>&1; then
    echo "==> Detected dnf (Fedora / RHEL / Rocky / Alma)"
    sudo dnf install -y mpv-libs python3-pyqt6 python3-pip ffmpeg-free || \
    sudo dnf install -y mpv-libs python3-pyqt6 python3-pip ffmpeg
    echo "   NOTE (Fedora): for full codec support you may need RPM Fusion:"
    echo "     https://rpmfusion.org/Configuration  then: sudo dnf install ffmpeg mpv-libs"
elif command -v pacman >/dev/null 2>&1; then
    echo "==> Detected pacman (Arch / CachyOS / Manjaro / EndeavourOS)"
    sudo pacman -S --needed --noconfirm mpv python-pyqt6 python-pip ffmpeg
elif command -v zypper >/dev/null 2>&1; then
    echo "==> Detected zypper (openSUSE)"
    sudo zypper install -y mpv libmpv2 python3-PyQt6 python3-pip ffmpeg
    echo "   NOTE (openSUSE): mpv/ffmpeg codecs come from the Packman repo."
    echo "     https://en.opensuse.org/Additional_package_repositories#Packman"
else
    echo "!! No supported package manager (apt / dnf / pacman / zypper) found."
    echo "   Install these manually from your distro, then re-run this script:"
    echo "     - libmpv   (the mpv shared library, e.g. libmpv2 / mpv-libs)"
    echo "     - PyQt6    (Python 6 Qt bindings, e.g. python3-pyqt6)"
    echo "     - python venv + pip"
    echo "     - ffmpeg   (for thumbnail generation)"
    exit 1
fi

# 2. Copy app files
echo "==> Copying app files to ${INSTALL_DIR}"
mkdir -p "$INSTALL_DIR"
cp "$SRC_DIR/main.py" "$INSTALL_DIR/"
# The application package (main.py imports it; it sits next to main.py so the
# launcher's `python .../main.py` finds it on sys.path automatically).
rm -rf "$INSTALL_DIR/cmediaplayer"
cp -r "$SRC_DIR/cmediaplayer" "$INSTALL_DIR/"
# Drop any stale bytecode so a reinstall never runs old cached modules.
rm -rf "$INSTALL_DIR/cmediaplayer/__pycache__" "$INSTALL_DIR/cmediaplayer/widgets/__pycache__"
# Bundled mpv config dir carrying uosc (the seek bar) + its fonts/options.
rm -rf "$INSTALL_DIR/mpv"
cp -r "$SRC_DIR/mpv" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/mpv/scripts/uosc/bin/ziggy-linux" 2>/dev/null || true
cp -r "$SRC_DIR/icons" "$INSTALL_DIR/"
cp "$SRC_DIR/icon.svg" "$INSTALL_DIR/"

# 3. Python venv with access to system PyQt6, plus python-mpv installed inside
echo "==> Setting up virtual environment"
python3 -m venv "$INSTALL_DIR/venv" --system-site-packages
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
        echo "xdg-mime not found — install the 'xdg-utils' package with your"
        echo "distro's package manager, then re-run this script."
    else
        for mime in video/mp4 video/x-matroska video/webm video/x-msvideo video/quicktime video/x-flv video/x-ms-wmv video/mpeg video/3gpp video/ogg; do
            xdg-mime default "${APP_ID}.desktop" "$mime"
        done
        echo "==> Set as default for common video types."
    fi
fi

if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    echo ""
    echo "NOTE: ${BIN_DIR} is not on your PATH, so the '${APP_ID}' command"
    echo "      won't be found until you add it. Pick the line for your shell:"
    echo "  bash:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    echo "  zsh:   echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
    echo "  fish:  fish_add_path ${BIN_DIR}"
    echo "Then open a new terminal (or 'source' the file above)."
    echo "The app grid launcher works regardless of PATH."
fi
