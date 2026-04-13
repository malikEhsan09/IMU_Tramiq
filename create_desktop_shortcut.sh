#!/usr/bin/env bash
# Creates a desktop shortcut for tramiqsdr so you can run it by double-clicking.
# Run once from the project directory: ./create_desktop_shortcut.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="TRAMIQ INS/GNSS Navigation Solution Software"
# Use a filesystem-safe filename (APP_NAME can contain slashes for display).
DESKTOP_FILE_NAME="TRAMIQ INS-GNSS Navigation Solution Software.desktop"
DESKTOP_FILE="$HOME/Desktop/$DESKTOP_FILE_NAME"
ICON="$SCRIPT_DIR/images/tramiq.png"

# Use a generic icon if project icon is missing
if [ ! -f "$ICON" ]; then
    ICON="application-x-executable"
fi

# Prefer project venv python if available
if [ -x "$SCRIPT_DIR/python/venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/python/venv/bin/python"
else
    PYTHON_BIN="python3"
fi

# Default command for this project; override with first argument if needed.
# Example:
#   ./create_desktop_shortcut.sh "python3 python/pocket_trk.py -sig L1CA -prn 1"
if [ "${1-}" != "" ]; then
    RUN_CMD="$1"
else
    RUN_CMD="$PYTHON_BIN $SCRIPT_DIR/gui.py"
fi

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Run tramiqsdr project
Exec=bash -lc 'cd "$SCRIPT_DIR" && $RUN_CMD'
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
