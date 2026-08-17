# Feed2ebook 📚⚡

**Feed2ebook** is a lightweight, terminal-based RSS feed reader and ebook compiler. It automatically fetches news and blog articles from your favorite RSS feeds, extracts full-text clean content using Readability, and bundles them into neatly formatted **EPUB** books or custom **XML** feeds for offline reading on your phone or ereader.

---

## ✨ Features

- 📖 **Full-Text Article Extraction:** Cleans ads, sidebars, scripts, and clutter using Readability algorithms to deliver pure, readable content.
- 🎨 **Colorful TUI & CLI Interfaces:** Modern interactive terminal menu with keyboard navigation (`curses`), alongside a full classic CLI fallback mode.
- 📁 **Flexible Export Options & Formats:** Bundle articles into clean **EPUB** eBooks, full-text **RSS XML** feeds, or generate both formats simultaneously.
- 📱 **Wide Reader Compatibility:** Generated EPUBs work out-of-the-box with standard Android/iOS eBook apps (e.g., Moon+ Reader, ReadEra) or **KOReader**. For native Kindle devices, easily convert or transfer via Amazon's Send-to-Kindle service or Calibre.
- 📍 **Smart Path & Storage Management:** Easily set output locations to shared phone storage (`/sdcard/Download`), Termux storage, or custom local paths. Includes automatic fallback protection if storage access is restricted.
- 🩺 **Automated Health Check & Diagnostics:** Built-in environment and dependency testing system to verify Python libraries, write permissions, and EPUB creation capabilities on the fly.
- 📂 **OPML Import & Export:** Effortlessly migrate and backup your subscription lists from tools like Feedly, Inoreader, or NetNewsWire.
- ⚙️ **Customizable Content Bundling:** Filter articles by publication age (max days) and set custom article limits per feed to prevent bloated files.
- ⚡ **Pure Python Stack:** Lightweight and fast execution without heavy external binary dependencies.

---

## ⚡ Feed2ebook Installer and Updater
### Automatic
Note: Run `termux-setup-storage` first in Termux to allow saving to your Download folder. If you encounter a "CANNOT LINK EXECUTABLE" error, run `apt update && apt full-upgrade` and then run the installation command again.

For **Termux** , run this command to install or update : 

```bash
curl -sSL https://raw.githubusercontent.com/ajay9634/Feed2ebook/main/install.sh | bash
```

After installation, launch the app anytime by typing: `feed2ebook`

### Manual

Run these commands one by one :

1. Storage permission for termux : `termux-setup-storage`
2. Termux Dependencies and package fix : `apt update && apt full-upgrade`
3. Python Dependencies installation :
```bash
curl -sSL https://raw.githubusercontent.com/ajay9634/Feed2ebook/main/dependencies.sh | bash
```
4. Run this to install or Update Feed2ebook :
```bash
curl -sSL https://raw.githubusercontent.com/ajay9634/Feed2ebook/main/install_feed2book.sh | bash
```
5. After installation, launch the app anytime by typing: `feed2ebook`
---
## Installation using pip

You can install `feed2ebook` directly from source or via GitHub using `pip`.

### Prerequisites
Make sure you have **Python 3.8+**, `pip`, and `git` installed on your system.

##### For Android (Termux) Users Only:
Termux requires system-level C libraries to build one of the dependencies (`lxml`). Before running the pip install command, you must install these required packages inside Termux:
```bash
pkg install python-lxml python-pillow libxml2 libxslt libjpeg-turbo zlib clang make git -y
```

##### For For Debian/Ubuntu Users:

```bash
sudo apt update && sudo apt install python3 python3-pip python3-lxml python3-pil libxml2-dev libxslt1-dev git libjpeg-dev zlib1g-dev build-essential -y
```

### Installation
```bash
pip install git+https://github.com/ajay9634/Feed2ebook.git
```
### Uninstallation

```pip uninstall feed2ebook -y```

## Samples

- **Sample Subscriptions:** [subscriptions.opml](./example/subscriptions.opml)
- **Generated EPUB Digest:** [Feed2ebook_Digest_2026_07_31_07_53.epub](./example/Feed2ebook_Digest_2026_07_31_07_53.epub)

---
