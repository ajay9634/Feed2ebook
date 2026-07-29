#!/usr/bin/env bash

set -e

echo "========================================="
echo "     Feed2ebook Dependencies Installer     "
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