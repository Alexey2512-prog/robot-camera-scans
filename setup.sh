#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
ASSUME_YES=0

log() {
    printf '\n==> %s\n' "$*"
}

warn() {
    printf 'WARNING: %s\n' "$*" >&2
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $0 [--yes]

Checks and installs dependencies for Robot Camera Scanner.

Options:
  --yes, -y   Do not ask for confirmation
  --help, -h  Show this help
EOF
}

for arg in "$@"; do
    case "$arg" in
        --yes|-y)
            ASSUME_YES=1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $arg"
            ;;
    esac
done

if [[ $EUID -eq 0 ]]; then
    fail "Do not run setup.sh with sudo. It requests sudo only when needed."
fi

confirm() {
    local reply

    if ((ASSUME_YES == 1)); then
        return 0
    fi

    printf '\nThe installer may add system packages and USB permission rules.\n'
    read -r -p "Continue? [y/N] " reply
    case "$reply" in
        y|Y|yes|YES)
            return 0
            ;;
        *)
            echo "Installation cancelled."
            exit 0
            ;;
    esac
}

ensure_sudo() {
    command -v sudo >/dev/null 2>&1 ||
        fail "sudo is required for system package installation."
    sudo -v
}

refresh_homebrew_path() {
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}

install_homebrew() {
    local installer

    if command -v brew >/dev/null 2>&1; then
        return
    fi

    log "Homebrew is missing; installing it"
    command -v curl >/dev/null 2>&1 ||
        fail "curl is required to download Homebrew."

    installer=$(mktemp)
    curl -fsSL \
        https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
        -o "$installer"
    NONINTERACTIVE=1 /bin/bash "$installer"
    rm -f "$installer"
    refresh_homebrew_path

    command -v brew >/dev/null 2>&1 ||
        fail "Homebrew was installed but is not available in PATH."
}

install_macos_dependencies() {
    install_homebrew

    if ! command -v python3 >/dev/null 2>&1; then
        log "Installing Python 3"
        brew install python
    else
        log "Python 3 is already installed: $(python3 --version 2>&1)"
    fi

    if ! command -v rs-enumerate-devices >/dev/null 2>&1; then
        log "Installing Intel RealSense SDK"
        brew install librealsense
    else
        log "Intel RealSense SDK is already installed"
    fi
}

install_linux_prerequisites() {
    local packages=()

    command -v python3 >/dev/null 2>&1 || packages+=("python3")
    python3 -m venv --help >/dev/null 2>&1 || packages+=("python3-venv")
    command -v curl >/dev/null 2>&1 || packages+=("curl")
    command -v gpg >/dev/null 2>&1 || packages+=("gnupg")
    command -v lsb_release >/dev/null 2>&1 || packages+=("lsb-release")

    if ((${#packages[@]} > 0)); then
        log "Installing Linux prerequisites: ${packages[*]}"
        ensure_sudo
        sudo apt-get update
        sudo apt-get install -y apt-transport-https "${packages[@]}"
    else
        log "Linux prerequisites are already installed"
    fi
}

install_linux_realsense() {
    local codename
    local key_file
    local key_source
    local repo_file="/etc/apt/sources.list.d/librealsense.list"
    local repo_line

    if command -v rs-enumerate-devices >/dev/null 2>&1; then
        log "Intel RealSense SDK is already installed"
        return
    fi

    codename=$(lsb_release -cs)
    key_file=$(mktemp)
    key_source=$(mktemp)
    repo_line="deb [signed-by=/etc/apt/keyrings/librealsenseai.gpg] https://librealsense.realsenseai.com/Debian/apt-repo $codename main"

    log "Adding the official RealSense package repository"
    ensure_sudo
    sudo install -d -m 0755 /etc/apt/keyrings
    curl -fsSL \
        https://librealsense.realsenseai.com/Debian/librealsenseai.asc \
        -o "$key_source"
    gpg --batch --yes --dearmor --output "$key_file" "$key_source"
    sudo install -m 0644 "$key_file" /etc/apt/keyrings/librealsenseai.gpg
    printf '%s\n' "$repo_line" | sudo tee "$repo_file" >/dev/null
    rm -f "$key_file" "$key_source"

    log "Installing Intel RealSense SDK and kernel support"
    sudo apt-get update
    sudo apt-get install -y librealsense2-utils librealsense2-dkms
}

install_linux_oak_udev_rule() {
    local rule='SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"'
    local rule_file="/etc/udev/rules.d/80-movidius.rules"

    if sudo test -f "$rule_file" &&
        sudo grep -Fqx "$rule" "$rule_file"; then
        log "Luxonis OAK USB permission rule is already installed"
        return
    fi

    log "Installing the Luxonis OAK USB permission rule"
    ensure_sudo
    printf '%s\n' "$rule" | sudo tee "$rule_file" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
}

install_linux_dependencies() {
    if ! command -v apt-get >/dev/null 2>&1; then
        fail "This installer supports Ubuntu/Debian systems with apt-get."
    fi

    install_linux_prerequisites
    install_linux_realsense
    install_linux_oak_udev_rule
}

install_python_dependencies() {
    local python_bin
    local venv_python

    python_bin=$(command -v python3 2>/dev/null || true)
    [[ -n "$python_bin" ]] || fail "Python 3 is not available after installation."

    if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
        log "Creating local Python environment: $VENV_DIR"
        "$python_bin" -m venv "$VENV_DIR"
    else
        log "Local Python environment already exists"
    fi

    venv_python="$VENV_DIR/bin/python3"
    log "Checking and installing Python packages"
    "$venv_python" -m pip install --disable-pip-version-check \
        -r "$REQUIREMENTS_FILE"
}

verify_installation() {
    local failed=0

    log "Verifying installation"

    if command -v rs-enumerate-devices >/dev/null 2>&1; then
        echo "[OK] rs-enumerate-devices"
    else
        echo "[FAILED] rs-enumerate-devices"
        failed=1
    fi

    if "$VENV_DIR/bin/python3" -c 'import depthai' >/dev/null 2>&1; then
        depthai_version=$(
            "$VENV_DIR/bin/python3" -c \
                'import depthai; print(getattr(depthai, "__version__", "unknown"))'
        )
        echo "[OK] DepthAI $depthai_version"
    else
        echo "[FAILED] DepthAI"
        failed=1
    fi

    if ((failed != 0)); then
        fail "Dependency verification failed. See README.md troubleshooting."
    fi
}

confirm

case "$(uname -s)" in
    Darwin)
        install_macos_dependencies
        ;;
    Linux)
        install_linux_dependencies
        ;;
    *)
        fail "Unsupported operating system: $(uname -s)"
        ;;
esac

install_python_dependencies
chmod +x "$SCRIPT_DIR/camera-scan" "$SCRIPT_DIR/setup.sh"
verify_installation

echo
echo "Setup complete."
echo "Connect the cameras and run:"
echo "  $SCRIPT_DIR/camera-scan"
