#!/usr/bin/env bash
# Quita el script y el lanzador (no desinstala ningún juego).
set -euo pipefail
BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -f "$BASE/applications/install_games.desktop"
rm -rf "$BASE/install-games"
echo "Lanzador y script eliminados."
