#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${FOLIO_PYTHON:-/usr/bin/python3}"
VENV_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/folio-pdf/venv"

if ! "$PYTHON_BIN" -c 'import gi, cairo' >/dev/null 2>&1; then
  echo 'Folio PDF needs GTK 4, python-gobject, and python-cairo from the system.' >&2
  exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]] || ! "$VENV_DIR/bin/python" -c 'import pymupdf; assert pymupdf.VersionBind == "1.28.2"' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
  if compgen -G "$APP_DIR/wheels/pymupdf-1.28.2-*.whl" >/dev/null; then
    "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-index \
      --find-links "$APP_DIR/wheels" 'PyMuPDF==1.28.2'
  else
    "$VENV_DIR/bin/python" -m pip install --disable-pip-version-check 'PyMuPDF==1.28.2'
  fi
fi

exec "$VENV_DIR/bin/python" "$APP_DIR/app.py" "$@"
