#!/usr/bin/env bash

set -e

echo "========================================="
echo "     Feed2ebook Automated Installer     "
echo "========================================="

# 1. Detect Environment & Install System Packages
if [ -d "/data/data/com.termux/files/usr" ]; then
    echo "[+] Termux environment detected."
    termux-setup-storage || true
    pkg update -y
    pkg install python libxml2 libxslt python-lxml clang make git curl -y
else
    echo "[+] Standard Linux environment detected."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -y
        sudo apt-get install -y python3 python3-pip python3-lxml libxml2-dev libxslt1-dev git curl
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y python3 python3-pip python3-lxml libxml2-devel libxslt-devel git curl
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm python python-pip python-lxml libxml2 libxslt git curl
    fi
fi

# 2. Install Python Dependencies
echo ""
echo "[+] Installing required Python libraries..."
pip install requests beautifulsoup4 readability-lxml feedparser ebooklib --break-system-packages 2>/dev/null || \
pip install requests beautifulsoup4 readability-lxml feedparser ebooklib

# 3. Setup Directory & Fetch Latest Script directly via GitHub API (Bypasses CDN Cache)
INSTALL_DIR="$HOME/.feed2ebook"
mkdir -p "$INSTALL_DIR"

PYTHON_SCRIPT="$INSTALL_DIR/Feed2ebook.py"

echo "[+] Cleaning up previous script version..."
rm -f "$PYTHON_SCRIPT"

echo "[+] Downloading fresh Feed2ebook.py from GitHub API..."
curl -sSLf -H "Accept: application/vnd.github.v3.raw" \
    "https://api.github.com/repos/ajay9634/Feed2ebook/contents/Feed2ebook.py" \
    -o "$PYTHON_SCRIPT"

chmod +x "$PYTHON_SCRIPT"

# 4. Create / Update Terminal Shortcut Command
echo ""
echo "[+] Updating shortcut command 'feed2ebook'..."

if [ -d "/data/data/com.termux/files/usr/bin" ]; then
    BIN_DIR="/data/data/com.termux/files/usr/bin"
else
    BIN_DIR="/usr/local/bin"
fi

WRAPPER_PATH="$BIN_DIR/feed2ebook"

if [ -w "$BIN_DIR" ]; then
    cat << 'EOF' > "$WRAPPER_PATH"
#!/usr/bin/env bash
INSTALL_DIR="$HOME/.feed2ebook"
PY_SCRIPT="$INSTALL_DIR/Feed2ebook.py"

if [ "$1" = "--update" ] || [ "$1" = "-u" ]; then
    echo "[+] Force updating Feed2ebook from GitHub..."
    rm -f "$PY_SCRIPT"
    curl -sSLf -H "Accept: application/vnd.github.v3.raw" \
        "https://api.github.com/repos/ajay9634/Feed2ebook/contents/Feed2ebook.py" \
        -o "$PY_SCRIPT"
    echo "[+] Update complete!"
fi

python "$PY_SCRIPT" "$@"
EOF
    chmod +x "$WRAPPER_PATH"
else
    echo '#!/usr/bin/env bash' | sudo tee "$WRAPPER_PATH" > /dev/null
    echo 'python3 "$HOME/.feed2ebook/Feed2ebook.py" "$@"' | sudo tee -a "$WRAPPER_PATH" > /dev/null
    sudo chmod +x "$WRAPPER_PATH"
fi

echo ""
echo "========================================="
echo "   [+] Installation Completed!           "
echo "   Launch the app anytime by typing:     "
echo "        feed2ebook                       "
echo "========================================="
