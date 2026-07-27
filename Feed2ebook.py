import os
import sys
import re
import json
import time
import curses
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import feedparser
import requests
from readability import Document
from bs4 import BeautifulSoup
from ebooklib import epub

VERSION = "1.0"
RAW_UPDATE_URL = "https://raw.githubusercontent.com/ajay9634/Feed2ebook/main/Feed2ebook.py"

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
FEEDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def ensure_directory_exists(path):
    """Utility to safely create directory if it doesn't exist."""
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"[-] Warning: Could not create folder {path}: {e}")

def load_config():
    """Load configuration with default fallback and ensure target directory exists."""
    default_config = {
        "download_path": "/sdcard/Download/Feed2ebook_Articles",
        "max_days": 7,
        "max_articles_per_feed": 20,
        "export_format": "epub"  # Options: 'epub', 'xml', 'all'
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                default_config.update(cfg)
        except Exception:
            pass

    # Fallback to epub if an invalid format was previously saved
    if default_config["export_format"] not in ["epub", "xml", "all"]:
        default_config["export_format"] = "epub"

    # Create target download folder immediately on setup/load
    ensure_directory_exists(default_config["download_path"])

    return default_config

def save_config(config):
    # Ensure folder exists when saving modified configuration
    ensure_directory_exists(config["download_path"])
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_feeds():
    if os.path.exists(FEEDS_FILE):
        try:
            with open(FEEDS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_feeds(feeds):
    with open(FEEDS_FILE, "w") as f:
        json.dump(feeds, f, indent=4)

def check_for_updates():
    """Checks GitHub repo for updates and offers to overwrite current file."""
    print(f"\n[+] Current Version: v{VERSION}")
    print("[+] Checking GitHub for updates...")
    try:
        req = urllib.request.Request(RAW_UPDATE_URL, headers={'User-Agent': HEADERS['User-Agent']})
        with urllib.request.urlopen(req, timeout=10) as response:
            remote_code = response.read().decode('utf-8')

        match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', remote_code)
        if not match:
            print("[-] Unable to parse remote version info.")
            return

        remote_version = match.group(1)
        if remote_version != VERSION:
            print(f"\n[!] New update available: v{remote_version}")
            choice = input("Would you like to update now? (y/n): ").strip().lower()
            if choice in ['y', 'yes']:
                script_path = os.path.realpath(sys.argv[0])
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(remote_code)
                print("\n[+] Update successfully installed!")
                print("[*] Restarting Feed2ebook...")
                os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            print("[+] You are using the latest version!")
    except Exception as e:
        print(f"[-] Failed to check for updates: {e}")

def import_opml(filepath):
    if not os.path.exists(filepath):
        print(f"[-] OPML file not found: {filepath}")
        return []
    
    feeds = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        for outline in root.iter('outline'):
            xml_url = outline.attrib.get('xmlUrl')
            if xml_url and xml_url not in feeds:
                feeds.append(xml_url)
        print(f"[+] Successfully imported {len(feeds)} feeds from OPML.")
    except Exception as e:
        print(f"[-] Error parsing OPML: {e}")
    return feeds

def export_opml(feeds, filepath):
    root = ET.Element("opml", version="1.0")
    head = ET.SubElement(root, "head")
    title = ET.SubElement(head, "title")
    title.text = "Feed2ebook Subscriptions"
    body = ET.SubElement(root, "body")
    
    for url in feeds:
        ET.SubElement(body, "outline", type="rss", text=url, xmlUrl=url)
        
    tree = ET.ElementTree(root)
    try:
        ensure_directory_exists(os.path.dirname(filepath))
        tree.write(filepath, encoding="utf-8", xml_declaration=True)
        print(f"[+] Feeds exported to OPML: {filepath}")
    except Exception as e:
        print(f"[-] Error exporting OPML: {e}")

def sanitize_filename(name):
    return "".join([c if c.isalnum() else "_" for c in name])[:50]

def extract_full_html_readability(url):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    
    doc = Document(response.text)
    clean_html = doc.summary()
    title = doc.title()
    
    soup = BeautifulSoup(clean_html, "html.parser")
    
    for tag in soup.find_all(True):
        if tag.name in ["script", "style", "iframe", "form", "button", "nav", "footer"]:
            tag.decompose()
        elif getattr(tag, 'attrs', None):
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in ["href", "src", "alt", "title"]}
            
    return title, str(soup)

def export_rss_xml(articles_data, output_filepath, bundle_title):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    
    title_elem = ET.SubElement(channel, "title")
    title_elem.text = bundle_title
    link_elem = ET.SubElement(channel, "link")
    link_elem.text = "https://github.com"
    desc_elem = ET.SubElement(channel, "description")
    desc_elem.text = "Generated Full-Text RSS Stream by Feed2ebook"
    
    for item_data in articles_data:
        item = ET.SubElement(channel, "item")
        i_title = ET.SubElement(item, "title")
        i_title.text = item_data['title']
        i_link = ET.SubElement(item, "link")
        i_link.text = item_data['url']
        i_desc = ET.SubElement(item, "description")
        i_desc.text = item_data['html_content']
        
    tree = ET.ElementTree(rss)
    ensure_directory_exists(os.path.dirname(output_filepath))
    tree.write(output_filepath, encoding="utf-8", xml_declaration=True)
    print(f"[+] Full-text RSS XML saved: {output_filepath}")

def build_epub(articles_data, output_dir, base_filename):
    full_title = base_filename
    book = epub.EpubBook()
    book.set_identifier(str(time.time()))
    book.set_title(full_title)
    book.set_language('en')
    book.add_author("Feed2ebook")

    chapters = []
    spine = ['nav']

    for i, data in enumerate(articles_data):
        c = epub.EpubHtml(title=data['title'], file_name=f'chap_{i}.xhtml', lang='en')
        c.content = f"""
        <html>
        <head><title>{data['title']}</title></head>
        <body>
            <h2>{data['title']}</h2>
            <p><b>Feed:</b> {data['feed_title']} | <a href='{data['url']}'>Original Source</a></p>
            <hr/>
            <div class="article-body">
                {data['html_content']}
            </div>
        </body>
        </html>
        """
        book.add_item(c)
        chapters.append(c)
        spine.append(c)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    ensure_directory_exists(output_dir)
    clean_name = sanitize_filename(base_filename)
    epub_filepath = os.path.join(output_dir, f"{clean_name}.epub")
    
    epub.write_epub(epub_filepath, book, {})
    print(f"[+] EPUB file saved: {epub_filepath}")

def process_feeds():
    config = load_config()
    feeds = load_feeds()
    
    if not feeds:
        print("[-] No RSS feeds found. Add them manually or import via OPML first.")
        return

    print(f"\n[+] Processing {len(feeds)} feed(s) with Feed2ebook Readability extraction...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=config["max_days"])
    all_collected_articles = []

    for feed_url in feeds:
        print(f"\nFetching Feed: {feed_url}")
        parsed_feed = feedparser.parse(feed_url)
        feed_title = parsed_feed.feed.get("title", "RSS_Feed")
        
        count = 0
        for entry in parsed_feed.entries:
            if count >= config["max_articles_per_feed"]:
                break
                
            pub_date = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                pub_date = datetime.fromtimestamp(time.mktime(entry.updated_parsed), tz=timezone.utc)
                
            if pub_date and pub_date < cutoff_date:
                continue
                
            article_url = entry.link
            try:
                print(f" -> Downloading HTML: {entry.get('title', article_url)}")
                title, html_content = extract_full_html_readability(article_url)
                
                all_collected_articles.append({
                    "title": title or entry.get("title", "Untitled"),
                    "url": article_url,
                    "feed_title": feed_title,
                    "html_content": html_content
                })
                
                count += 1
            except Exception as e:
                print(f"    [-] Error extracting article HTML: {e}")

    if not all_collected_articles:
        print("[-] No matching articles found to compile.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    base_title = f"Feed2ebook_Digest_{timestamp}"
    fmt = config["export_format"].lower()

    if fmt == "epub":
        build_epub(all_collected_articles, config["download_path"], base_title)
    elif fmt == "xml":
        xml_filepath = os.path.join(config["download_path"], f"{sanitize_filename(base_title)}.xml")
        export_rss_xml(all_collected_articles, xml_filepath, base_title)
    elif fmt == "all":
        build_epub(all_collected_articles, config["download_path"], base_title)
        xml_filepath = os.path.join(config["download_path"], f"{sanitize_filename(base_title)}.xml")
        export_rss_xml(all_collected_articles, xml_filepath, base_title)

    print("\n[+] Feed2ebook processing completed!")

# --- COLORFUL CURSES TUI INTERFACE ---

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)     # Header Title
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN) # Highlighted Option
    curses.init_pair(3, curses.COLOR_GREEN, -1)    # Action / Active Status
    curses.init_pair(4, curses.COLOR_YELLOW, -1)   # Settings / Info
    curses.init_pair(5, curses.COLOR_RED, -1)      # Exit / Delete
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)  # OPML / Imports

def draw_tui_menu(stdscr, selected_row, options, title=f"=== Feed2ebook Manager v{VERSION} ==="):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    
    stdscr.attron(curses.A_BOLD | curses.color_pair(1))
    stdscr.addstr(1, 2, title[:w-4])
    stdscr.attroff(curses.A_BOLD | curses.color_pair(1))
    
    stdscr.addstr(2, 2, "=" * (w - 4), curses.color_pair(1))

    for idx, (label, color_pair_id) in enumerate(options):
        x = 4
        y = 4 + idx
        if idx == selected_row:
            stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
            stdscr.addstr(y, x, f"> {label} "[:w-6])
            stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
        else:
            stdscr.attron(curses.color_pair(color_pair_id))
            stdscr.addstr(y, x, f"  {label} "[:w-6])
            stdscr.attroff(curses.color_pair(color_pair_id))

    stdscr.addstr(h - 2, 2, "[UP/DOWN]: Navigate | [ENTER]: Select | [Q]: Classic Menu", curses.color_pair(4))
    stdscr.refresh()

def curses_tui_loop(stdscr):
    curses.curs_set(0)
    init_colors()
    
    current_row = 0
    
    while True:
        config = load_config()
        feeds = load_feeds()
        
        menu_items = [
            (f"Run Processing Pipeline (Target: {config['export_format'].upper()})", 3),
            (f"Manage Feeds ({len(feeds)} active)", 1),
            (f"Import OPML Subscriptions", 6),
            (f"Export OPML Subscriptions", 6),
            (f"Configure Settings (Format: {config['export_format'].upper()}, Days: {config['max_days']})", 4),
            (f"Check for Script Updates (v{VERSION})", 3),
            ("Switch to Classic CLI Menu", 1),
            ("Exit Program", 5)
        ]
        
        current_row = max(0, min(current_row, len(menu_items) - 1))
        
        draw_tui_menu(stdscr, current_row, menu_items)
        key = stdscr.getch()

        if key in [curses.KEY_UP, ord('k')]:
            if current_row > 0:
                current_row -= 1
            else:
                current_row = len(menu_items) - 1
        elif key in [curses.KEY_DOWN, ord('j')]:
            if current_row < len(menu_items) - 1:
                current_row += 1
            else:
                current_row = 0
        elif key in [10, 13]:
            curses.endwin()
            if current_row == 0:
                process_feeds()
            elif current_row == 1:
                manage_feeds_cli()
            elif current_row == 2:
                import_opml_cli()
            elif current_row == 3:
                export_opml_cli()
            elif current_row == 4:
                settings_cli()
            elif current_row == 5:
                check_for_updates()
            elif current_row == 6:
                return "cli"
            elif current_row == 7:
                return "exit"
            
            input("\nPress Enter to return to Feed2ebook TUI...")
            stdscr = curses.initscr()
            curses.curs_set(0)

        elif key in [ord('q'), ord('Q')]:
            return "cli"

# --- CLI FALLBACK & MANUAL MENUS ---

def manage_feeds_cli():
    feeds = load_feeds()
    print("\nCurrent Feeds:")
    for idx, f in enumerate(feeds, 1):
        print(f"{idx}. {f}")
    sub = input("\nType a URL to add, or enter a number to delete (or press Enter to go back): ").strip()
    if sub.startswith("http"):
        feeds.append(sub)
        save_feeds(feeds)
        print("[+] Feed added.")
    elif sub.isdigit():
        idx = int(sub) - 1
        if 0 <= idx < len(feeds):
            removed = feeds.pop(idx)
            save_feeds(feeds)
            print(f"[-] Removed: {removed}")

def import_opml_cli():
    path = input("Enter path to OPML file (e.g., /sdcard/Download/subscriptions.opml): ").strip()
    new_feeds = import_opml(path)
    if new_feeds:
        existing = load_feeds()
        merged = list(set(existing + new_feeds))
        save_feeds(merged)

def export_opml_cli():
    config = load_config()
    feeds = load_feeds()
    if not feeds:
        print("[-] No feeds to export.")
        return
    path = input(f"Enter destination OPML path [{os.path.join(config['download_path'], 'subscriptions.opml')}]: ").strip()
    if not path:
        path = os.path.join(config['download_path'], "subscriptions.opml")
    export_opml(feeds, path)

def settings_cli():
    config = load_config()
    print(f"\nCurrent Settings:")
    print(f"A. Max Article Age (Days): {config['max_days']}")
    print(f"B. Max Articles Per Feed: {config['max_articles_per_feed']}")
    print(f"C. Export Format ('epub', 'xml', or 'all'): {config['export_format']}")
    print(f"D. Download Path: {config['download_path']}")
    
    field = input("Choose setting to modify (A/B/C/D) or press Enter to return: ").strip().upper()
    if field == "A":
        config["max_days"] = int(input("Enter max days: ").strip())
    elif field == "B":
        config["max_articles_per_feed"] = int(input("Enter max articles per feed: ").strip())
    elif field == "C":
        fmt = input("Enter format ('epub', 'xml', 'all'): ").strip().lower()
        if fmt in ["epub", "xml", "all"]:
            config["export_format"] = fmt
        else:
            print("[-] Invalid format option.")
    elif field == "D":
        new_path = input("Enter new path: ").strip()
        if new_path:
            config["download_path"] = new_path
    save_config(config)
    print("[+] Settings updated successfully!")

def main_cli_menu():
    while True:
        config = load_config()
        print(f"\n=== Feed2ebook Manager v{VERSION} ===")
        print(f"1. Run Downloader (Format: {config['export_format'].upper()})")
        print(f"2. Manage Feeds ({len(load_feeds())} currently saved)")
        print("3. Import OPML File")
        print("4. Export OPML File")
        print(f"5. Settings (Format: {config['export_format'].upper()}, Days limit: {config['max_days']})")
        print("6. Check for Script Updates")
        print("7. Launch TUI Graphical Menu")
        print("8. Exit")
        
        choice = input("Select an option (1-8): ").strip()
        
        if choice == "1":
            process_feeds()
        elif choice == "2":
            manage_feeds_cli()
        elif choice == "3":
            import_opml_cli()
        elif choice == "4":
            export_opml_cli()
        elif choice == "5":
            settings_cli()
        elif choice == "6":
            check_for_updates()
        elif choice == "7":
            res = curses.wrapper(curses_tui_loop)
            if res == "exit":
                break
        elif choice == "8":
            break

def main():
    try:
        res = curses.wrapper(curses_tui_loop)
        if res == "cli":
            main_cli_menu()
    except Exception:
        main_cli_menu()

if __name__ == "__main__":
    main()
        
