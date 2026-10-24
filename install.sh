#!/usr/bin/env bash
# Instala el script y su lanzador para el usuario actual (no requiere sudo).
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/install-games"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DEST" "$APPS"
install -m 755 "$SRC/install_games.py" "$DEST/install_games.py"
sed "s|@SCRIPT_PATH@|$DEST/install_games.py|g" "$SRC/install_games.desktop.in" > "$APPS/install_games.desktop"
chmod 644 "$APPS/install_games.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
echo "Instalado:"
echo "  Script   : $DEST/install_games.py"
echo "  Lanzador : $APPS/install_games.desktop  (búscalo como «Instalar Juegos»)"
