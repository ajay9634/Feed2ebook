#!/usr/bin/env bash

set -e

echo "========================================="
echo "    Feed2ebook Automated Uninstaller    "
echo "========================================="

# 1. Remove Application Files
INSTALL_DIR="$HOME/.feed2ebook"

if [ -d "$INSTALL_DIR" ]; then
    echo "[+] Removing installation directory: $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
else
    echo "[-] Installation directory not found. Skipping."
fi

# 2. Remove Terminal Shortcut Wrapper
if [ -d "/data/data/com.termux/files/usr/bin" ]; then
    WRAPPER_PATH="/data/data/com.termux/files/usr/bin/feed2ebook"
    if [ -f "$WRAPPER_PATH" ]; then
        echo "[+] Removing Termux binary shortcut..."
        rm -f "$WRAPPER_PATH"
    fi
else
    WRAPPER_PATH="/usr/local/bin/feed2ebook"
    if [ -f "$WRAPPER_PATH" ]; then
        echo "[+] Removing system binary shortcut..."
        if [ -w "/usr/local/bin" ]; then
            rm -f "$WRAPPER_PATH"
        else
            sudo rm -f "$WRAPPER_PATH"
        fi
    fi
fi

echo ""
echo "========================================="
echo "   [+] Uninstallation Complete!         "
echo "========================================="
