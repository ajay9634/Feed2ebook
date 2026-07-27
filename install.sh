#!/usr/bin/env bash

set -e

echo "========================================="
echo "     Feed2ebook Automated Installer     "
echo "========================================="

# 1. Detect Environment & Install System Packages
if [ -d "/data/data/com.termux/files/usr" ]; then
    echo "[+] Termux environment detected."
    pkg update -y
    pkg install python python-pip libxml2 libxslt clang make git curl -y
else
    echo "[+] Standard Linux environment detected."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -y
        sudo apt-get install -y python3 python3-pip libxml2-dev libxslt1-dev git curl
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y python3 python3-pip libxml2-devel libxslt-devel git curl
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm python python-pip libxml2 libxslt git curl
    fi
fi

# 2. Install Python Dependencies
echo ""
echo "[+] Installing required Python libraries..."
pip install requests beautifulsoup4 readability-lxml feedparser ebooklib

# 3. Setup Script Directory & Download feed2ebook.py if missing
INSTALL_DIR="$HOME/.feed2ebook"
mkdir -p "$INSTALL_DIR"

PYTHON_SCRIPT="$INSTALL_DIR/feed2ebook.py"

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo ""
    echo "[+] Downloading feed2ebook.py from GitHub..."
    curl -sSL "https://raw.githubusercontent.com/ajay9634/Feed2ebook/main/feed2ebook.py" -o "$PYTHON_SCRIPT"
fi

chmod +x "$PYTHON_SCRIPT"

# 4. Create Terminal Shortcut / Wrapper Command
echo ""
echo "[+] Creating shortcut command 'feed2ebook'..."

if [ -d "/data/data/com.termux/files/usr/bin" ]; then
    BIN_DIR="/data/data/com.termux/files/usr/bin"
else
    BIN_DIR="/usr/local/bin"
fi

WRAPPER_PATH="$BIN_DIR/feed2ebook"

if [ -w "$BIN_DIR" ]; then
    echo "#!/usr/bin/env bash" > "$WRAPPER_PATH"
    echo "python \"$PYTHON_SCRIPT\" \"\$@\"" >> "$WRAPPER_PATH"
    chmod +x "$WRAPPER_PATH"
else
    echo "#!/usr/bin/env bash" | sudo tee "$WRAPPER_PATH" > /dev/null
    echo "python3 \"$PYTHON_SCRIPT\" \"\$@\"" | sudo tee -a "$WRAPPER_PATH" > /dev/null
    sudo chmod +x "$WRAPPER_PATH"
fi

echo ""
echo "========================================="
echo "   [+] Installation Completed!           "
echo "   Launch the app anytime by typing:     "
echo "        feed2ebook                       "
echo "========================================="
