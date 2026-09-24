#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/dev.folio.PDF.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Folio PDF
Comment=View and edit PDF pages, text, and pictures
Exec=$APP_DIR/run.sh %F
Icon=$APP_DIR/icon.svg
Terminal=false
Categories=Office;
MimeType=application/pdf;
StartupNotify=true
EOF
echo "Installed Folio PDF in the app launcher."
