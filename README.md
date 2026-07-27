# Feed2ebook 📚⚡

**Feed2ebook** is a lightweight, terminal-based RSS feed reader and ebook compiler. It automatically fetches news and blog articles from your favorite RSS feeds, extracts full-text clean content using Readability, and bundles them into neatly formatted **EPUB** books or custom **XML** feeds for offline reading on your phone or ereader.

---

## ✨ Features

- 📖 **Full-Text Article Extraction:** Cleans ads, sidebars, scripts, and clutter using Readability algorithms.
- 🎨 **Colorful TUI & CLI:** Modern terminal menu with keyboard navigation (`curses`), plus a classic CLI fallback.
- 📂 **OPML Import/Export:** Effortlessly migrate your feed subscriptions from feeder tools like Inoreader or Feedly.
- ⚙️ **Customizable Bundles:** Filter articles by publication date (max age in days) and set per-feed article limits.
- 📦 **Zero Heavy Dependencies:** Built with a pure Python stack—no Calibre required.

---

## ⚡ One-Line Automatic Installer

For **Termux** or **Linux**, run this single command:

curl -sSL https://raw.githubusercontent.com/ajay9634/Feed2ebook/main/install.sh | bash

Note: Run termux-setup-storage first on Termux to allow saving to your Download folder.

Launch the app anytime by typing: feed2ebook
