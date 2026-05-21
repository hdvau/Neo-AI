#!/usr/bin/env bash
# Neo AI — installer
# Usage:  bash install.sh          (install / update)
#
# What it does:
#   1. Checks Python 3.10+
#   2. Creates .venv inside the project directory
#   3. Installs all dependencies via pip (using pyproject.toml)
#   4. Copies config.yaml.example → config.yaml if no config exists yet
#   5. Writes a `neo` launcher to /usr/local/bin  (or ~/.local/bin as fallback)

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[neo]${NC} $*"; }
ok()    { echo -e "${GREEN} ✓${NC}  $*"; }
warn()  { echo -e "${YELLOW} !${NC}  $*"; }
fail()  { echo -e "${RED} ✗${NC}  $*" >&2; exit 1; }

# ── Locate project root ───────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$SCRIPT_DIR/main.py" ]]; then
    fail "Run install.sh from the Neo-AI project root (main.py not found)."
fi

VENV="$SCRIPT_DIR/.venv"
CONFIG="$SCRIPT_DIR/config/config.yaml"
EXAMPLE="$SCRIPT_DIR/config/config.yaml.example"

echo ""
echo -e "${BOLD}  Neo AI — Installer${NC}"
echo "  ─────────────────────────────"
echo ""

# ── 1. Python version ─────────────────────────────────────────────────────────
info "Checking Python version..."
PYTHON=$(command -v python3 2>/dev/null) || fail "python3 not found. Install Python 3.10+."
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$("$PYTHON" -c "import sys; print(sys.version_info >= (3, 10))")
[[ "$PY_OK" == "True" ]] || fail "Python 3.10+ required (found $PY_VER)."
ok "Python $PY_VER"

# ── 2. Virtual environment ────────────────────────────────────────────────────
info "Setting up virtual environment..."
if [[ ! -d "$VENV" ]]; then
    "$PYTHON" -m venv "$VENV"
    ok "Virtual environment created at .venv"
else
    ok "Virtual environment already exists"
fi

# ── 3. Install / upgrade dependencies ────────────────────────────────────────
info "Installing dependencies..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
ok "Dependencies installed"

# ── 4. Config file ────────────────────────────────────────────────────────────
if [[ ! -f "$CONFIG" ]]; then
    info "Creating config from example..."
    cp "$EXAMPLE" "$CONFIG"
    ok "config/config.yaml created"
    warn "Edit ${BOLD}config/config.yaml${NC}${YELLOW} before first use."
else
    ok "config/config.yaml already present"
fi

# ── 5. Install `neo` launcher ─────────────────────────────────────────────────
info "Installing 'neo' command..."

# The launcher is a tiny shell wrapper so it works in any shell (bash/zsh/fish).
NEO_LAUNCHER="#!/usr/bin/env bash
exec \"$VENV/bin/python\" \"$SCRIPT_DIR/main.py\" \"\$@\""

# Preferred: /usr/local/bin (system-wide, writable on macOS with brew)
# Fallback:  ~/.local/bin  (user-local, no sudo needed on Linux)
SYSTEM_BIN="/usr/local/bin/neo"
USER_BIN="$HOME/.local/bin/neo"

write_launcher() {
    local dest="$1"
    mkdir -p "$(dirname "$dest")"
    printf '%s\n' "$NEO_LAUNCHER" > "$dest"
    chmod +x "$dest"
}

if [[ -w "/usr/local/bin" ]]; then
    write_launcher "$SYSTEM_BIN"
    ok "'neo' installed to $SYSTEM_BIN"
    # Also install 'neo:' for one-shot usage: neo: <prompt>
    write_launcher "${SYSTEM_BIN}:"
    ok "'neo:' installed to ${SYSTEM_BIN}:"
elif command -v sudo &>/dev/null; then
    printf '%s\n' "$NEO_LAUNCHER" | sudo tee "$SYSTEM_BIN" > /dev/null
    sudo chmod +x "$SYSTEM_BIN"
    ok "'neo' installed to $SYSTEM_BIN (via sudo)"
    printf '%s\n' "$NEO_LAUNCHER" | sudo tee "${SYSTEM_BIN}:" > /dev/null
    sudo chmod +x "${SYSTEM_BIN}:"
    ok "'neo:' installed to ${SYSTEM_BIN}: (via sudo)"
else
    write_launcher "$USER_BIN"
    ok "'neo' installed to $USER_BIN"
    write_launcher "${USER_BIN}:"
    ok "'neo:' installed to ${USER_BIN}:"

    # Ensure ~/.local/bin is on PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        SHELL_PROFILE=""
        case "${SHELL##*/}" in
            zsh)  SHELL_PROFILE="$HOME/.zshrc" ;;
            bash) SHELL_PROFILE="$HOME/.bashrc" ;;
        esac
        if [[ -n "$SHELL_PROFILE" ]]; then
            echo "" >> "$SHELL_PROFILE"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_PROFILE"
            warn "Added ~/.local/bin to PATH in $SHELL_PROFILE"
            warn "Run: source $SHELL_PROFILE"
        else
            warn "Add ~/.local/bin to your PATH manually."
        fi
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}  Done!${NC}  Run ${BOLD}neo${NC} to start, or ${BOLD}neo: <prompt>${NC} for one-shot mode."
echo ""
