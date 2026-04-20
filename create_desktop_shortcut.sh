#!/usr/bin/env bash
# Creates a desktop shortcut for tramiqsdr so you can run it by double-clicking.
# Run once from the project directory: ./create_desktop_shortcut.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="TRAMIQ INS/GNSS Navigation Solution Software"
# Use a filesystem-safe filename (APP_NAME can contain slashes for display).
DESKTOP_FILE_NAME="TRAMIQ INS-GNSS Navigation Solution Software.desktop"
DESKTOP_FILE="$HOME/Desktop/$DESKTOP_FILE_NAME"
LAUNCHER_SCRIPT="$SCRIPT_DIR/.launch_tramiq_desktop.sh"
ICON="$SCRIPT_DIR/images/tramiq.png"

# Use a generic icon if project icon is missing
if [ ! -f "$ICON" ]; then
    ICON="application-x-executable"
fi

# Build a launcher script so desktop execution always uses the correct environment.
# You can override the launch command by passing the first argument.
# Example:
#   ./create_desktop_shortcut.sh "python3 \"$SCRIPT_DIR/python/pocket_trk.py\" -sig L1CA -prn 1"
if [ "${1-}" != "" ]; then
    RUN_CMD="$1"
    cat > "$LAUNCHER_SCRIPT" << EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$SCRIPT_DIR"
exec bash -lc '$RUN_CMD'
EOF
else
    cat > "$LAUNCHER_SCRIPT" << EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$SCRIPT_DIR"
if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/gui.py"
elif [ -x "$SCRIPT_DIR/python/venv/bin/python" ]; then
    exec "$SCRIPT_DIR/python/venv/bin/python" "$SCRIPT_DIR/gui.py"
else
    exec python3 "$SCRIPT_DIR/gui.py"
fi
EOF
fi

chmod +x "$LAUNCHER_SCRIPT"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Run tramiqsdr project
Exec=bash "$LAUNCHER_SCRIPT"
Icon=$ICON
Path=$SCRIPT_DIR
Terminal=true
Categories=Application;Science;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"

# Mark as trusted so double-click runs the app instead of opening in editor (GNOME/Ubuntu)
if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

echo "Desktop shortcut created: $DESKTOP_FILE"
echo "Double-click '$APP_NAME' on your desktop to run the application."
echo "If double-click only opens the file: right-click the icon -> Allow Launching (or Trust and Launch)."
