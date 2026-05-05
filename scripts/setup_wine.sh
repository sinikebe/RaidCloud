#!/usr/bin/env bash
# scripts/setup_wine.sh
# Install Wine + Windows Python 3.12 + project deps + PyInstaller
# for cross-compiling raidcloud.exe on Linux.
#
# Run once before using: python scripts/build.py --target windows
set -euo pipefail

PYTHON_VERSION="3.12.10"
# Use the embeddable zip — no installer needed, works in headless Wine/CI
PYTHON_EMBED_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip"
WINE_PYTHON="$HOME/.wine/drive_c/python312/python.exe"

# ---------------------------------------------------------------------------
# 1. Install Wine (if not present)
# ---------------------------------------------------------------------------
if ! command -v wine &>/dev/null; then
    echo "Installing Wine..."
    sudo dpkg --add-architecture i386
    sudo apt-get update -q
    sudo apt-get install -y wine wine64 wine32 winbind
fi

# Ensure unzip is available (needed to extract embeddable Python)
if ! command -v unzip &>/dev/null; then
    sudo apt-get install -y unzip
fi

echo "Wine version: $(wine --version)"

# ---------------------------------------------------------------------------
# 2. Bootstrap Wine prefix
# ---------------------------------------------------------------------------
export WINEARCH=win64
export WINEPREFIX="$HOME/.wine"
export WINEDEBUG="-all"

echo "Initialising Wine prefix (this may take a moment)..."
wineboot --init
wineserver --wait

# Verify the prefix is functional
if ! wine cmd /c "echo OK" &>/dev/null; then
    echo "Wine prefix appears broken — wiping and reinitialising..."
    rm -rf "$WINEPREFIX"
    wineboot --init
    wineserver --wait
fi

# ---------------------------------------------------------------------------
# 3. Install Windows Python 3.12 (embeddable zip — no installer required)
# ---------------------------------------------------------------------------
if [[ ! -f "$WINE_PYTHON" ]]; then
    echo "Downloading Python ${PYTHON_VERSION} embeddable package..."
    TMP=$(mktemp -d)
    curl -fsSL "$PYTHON_EMBED_URL" -o "$TMP/python_embed.zip"

    echo "Extracting Python into Wine prefix..."
    PYTHON_DIR="$HOME/.wine/drive_c/python312"
    mkdir -p "$PYTHON_DIR"
    unzip -q "$TMP/python_embed.zip" -d "$PYTHON_DIR"
    rm -rf "$TMP"

    # Enable site-packages (required for pip-installed packages to be importable)
    PTH_FILE="$PYTHON_DIR/python312._pth"
    if [[ -f "$PTH_FILE" ]]; then
        # Uncomment or append "import site"
        sed -i 's/^#import site/import site/' "$PTH_FILE"
        grep -q "^import site" "$PTH_FILE" || echo "import site" >> "$PTH_FILE"
    fi

    # Bootstrap pip
    echo "Bootstrapping pip..."
    PIP_BOOTSTRAP=$(mktemp)
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$PIP_BOOTSTRAP"
    wine "$WINE_PYTHON" "$PIP_BOOTSTRAP" --quiet
    rm "$PIP_BOOTSTRAP"
fi

echo "Wine Python: $WINE_PYTHON"

# ---------------------------------------------------------------------------
# 4. Install pip packages into Wine Python
# ---------------------------------------------------------------------------
echo "Installing project dependencies into Wine Python..."
wine "$WINE_PYTHON" -m pip install --upgrade pip --quiet

# Install the project and its deps
wine "$WINE_PYTHON" -m pip install \
    "click>=8.1" \
    "pyyaml>=6.0" \
    "dropbox>=12.0" \
    "boto3>=1.38" \
    "google-api-python-client>=2.160" \
    "google-auth-oauthlib>=1.2" \
    "msal>=1.30" \
    "requests>=2.32" \
    "cryptography>=46.0.5" \
    --quiet

# Install PyInstaller
wine "$WINE_PYTHON" -m pip install "pyinstaller>=6.0" --quiet

echo ""
echo "Setup complete. You can now run:"
echo "  python scripts/build.py --target windows"
