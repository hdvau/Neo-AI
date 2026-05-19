#!/usr/bin/env bash
# Neo AI — uninstaller
# Usage:  bash uninstall.sh

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${CYAN}[neo]${NC} $*"; }
ok()   { echo -e "${GREEN} ✓${NC}  $*"; }
warn() { echo -e "${YELLOW} !${NC}  $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}  Neo AI — Uninstaller${NC}"
echo "  ─────────────────────────────"
echo ""

remove_file() {
    local path="$1"
    if [[ -f "$path" ]]; then
        if [[ -w "$path" ]] || [[ -w "$(dirname "$path")" ]]; then
            rm "$path"
        else
            sudo rm "$path"
        fi
        ok "Removed $path"
    fi
}

# Remove `neo` launchers from known locations
info "Removing 'neo' command..."
remove_file "/usr/local/bin/neo"
remove_file "$HOME/.local/bin/neo"

# Remove virtual environment
info "Removing virtual environment..."
if [[ -d "$SCRIPT_DIR/.venv" ]]; then
    rm -rf "$SCRIPT_DIR/.venv"
    ok "Removed .venv"
else
    warn ".venv not found — already removed?"
fi

echo ""
warn "config/config.yaml was ${BOLD}not${NC}${YELLOW} deleted (your settings are safe)."
warn "Remove it manually if you want a clean slate: rm config/config.yaml"
echo ""
echo -e "${GREEN}${BOLD}  Done.${NC}  Neo AI has been uninstalled."
echo ""
