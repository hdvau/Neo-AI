#!/bin/bash
# Neo-AI installer
# Usage: bash install.sh   (run from the project root containing main.py)
set -euo pipefail

DEBUG=0
debug() {
    if [ "$DEBUG" -eq 1 ]; then
        echo "DEBUG: $1"
    fi
}

if [[ ! -f "main.py" ]]; then
    echo "ERROR: Run this script from the project root containing 'main.py'." >&2
    exit 1
fi

# ── Python version check ──────────────────────────────────────────────────────
check_python_version() {
    if ! command -v python3 &>/dev/null; then
        echo "ERROR: Python 3 is not installed. Please install Python 3.9 or later." >&2
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    debug "Found Python version: $PYTHON_VERSION"

    python3 - <<'EOF'
import sys
if sys.version_info < (3, 9):
    print("ERROR: Python 3.9 or higher is required.", file=sys.stderr)
    sys.exit(1)
EOF

    echo "Python $PYTHON_VERSION — OK."
}

# ── Package manager detection & prerequisite install ─────────────────────────
install_prerequisites() {
    debug "Detecting package manager..."

    if command -v apt &>/dev/null; then
        debug "Using apt"
        sudo apt-get update -q
        sudo apt-get install -y python3-pip python3-venv portaudio19-dev
    elif command -v dnf &>/dev/null; then
        debug "Using dnf"
        sudo dnf install -y python3 python3-pip portaudio-devel
    elif command -v yum &>/dev/null; then
        debug "Using yum"
        sudo yum install -y python3 python3-pip portaudio-devel
    elif command -v zypper &>/dev/null; then
        debug "Using zypper"
        sudo zypper install -y python3 python3-pip portaudio-devel
    elif command -v pacman &>/dev/null; then
        debug "Using pacman"
        sudo pacman -Sy --noconfirm python python-pip portaudio
    else
        echo "WARNING: Unsupported package manager. Please install Python 3, pip, venv, and portaudio manually." >&2
    fi
}

# ── Virtual environment ───────────────────────────────────────────────────────
create_virtualenv() {
    debug "Creating virtual environment..."
    if [[ ! -d "venv" ]]; then
        python3 -m venv venv
        echo "Virtual environment created."
    else
        echo "Virtual environment already exists."
    fi
}

activate_virtualenv() {
    debug "Activating virtual environment..."
    # shellcheck disable=SC1091
    source venv/bin/activate || { echo "ERROR: Failed to activate virtual environment." >&2; exit 1; }
}

# ── Python package installation ───────────────────────────────────────────────
install_python_packages() {
    debug "Installing Python packages..."
    # requirements.txt is the committed source of truth — do not overwrite it.
    if [[ ! -f "requirements.txt" ]]; then
        echo "ERROR: requirements.txt not found. The repository may be incomplete." >&2
        exit 1
    fi
    pip install --upgrade pip
    pip install -r requirements.txt
}

check_python_packages() {
    debug "Checking installed Python packages..."
    local required=("setuptools" "openai" "pyyaml" "pynput")
    for pkg in "${required[@]}"; do
        if ! pip show "$pkg" &>/dev/null; then
            echo "ERROR: Package '$pkg' is not installed correctly." >&2
            exit 1
        fi
    done
}

# ── Persistent memory ─────────────────────────────────────────────────────────
create_persistent_memory() {
    local MEMORY_FILE="/tmp/persistent_memory.txt"
    echo "Gathering system information for persistent memory..."
    {
        echo "Kernel Version: $(uname -r)"
        echo "OS Info: $(uname -o 2>/dev/null || uname -s)"
        echo "Architecture: $(uname -m)"
        echo "Hostname: $(hostname)"
    } > "$MEMORY_FILE"
    echo "Persistent memory created at $MEMORY_FILE."
}

# ── Shell alias ───────────────────────────────────────────────────────────────
add_alias_to_bashrc() {
    local INSTALL_DIR
    INSTALL_DIR="$(pwd)"
    if ! grep -Fxq "# Neo AI Integration" ~/.bashrc; then
        {
            echo ""
            echo "# Neo AI Integration"
            echo "alias neo='source ${INSTALL_DIR}/venv/bin/activate && python3 ${INSTALL_DIR}/main.py'"
        } >> ~/.bashrc
        echo "Alias added to ~/.bashrc"
    else
        echo "Neo alias already present in ~/.bashrc."
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
check_python_version
install_prerequisites
create_virtualenv
activate_virtualenv
install_python_packages
check_python_packages
create_persistent_memory
add_alias_to_bashrc

echo ""
echo "Installation complete."
echo "Run 'source ~/.bashrc' or restart your terminal, then type 'neo' to start."
