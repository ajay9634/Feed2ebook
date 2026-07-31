import os
import sys
import json
import time
import curses
import importlib.util
import subprocess
import urllib.parse
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import feedparser
import requests
from readability import Document
from bs4 import BeautifulSoup
from ebooklib import epub

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
FEEDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

PRESET_PATHS = {
    "1": ("/sdcard/Download/Feed2ebook_Articles", "Phone Downloads Folder (/sdcard/Download)"),
    "2": (os.path.expanduser("~/storage/downloads/Feed2ebook_Articles"), "Termux Shared Downloads (~/storage/downloads)"),
    "3": (os.path.expanduser("~/Feed2ebook_Articles"), "Termux Internal Storage (~/Feed2ebook_Articles)"),
}

VALID_FORMATS = ["epub", "xml", "html", "md", "all"]
TOC_MODES = ["auto", "disabled", "simple", "advanced"]

def check_and_install_package(package_name, import_name=None):
    """Checks if a module is installed; prompts user to install via pip if missing."""
    import_module = import_name or package_name
    if importlib.util.find_spec(import_module) is not None:
        return True

    print(f"\n[!] Required package '{package_name}' is not installed for this export format.")
    choice = input(f"Would you like to install '{package_name}' now using pip? (y/n): ").strip().lower()
    if choice == 'y':
        print(f"[+] Installing '{package_name}'...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            print(f"[+] Package '{package_name}' installed successfully!")
            return True
        except Exception as e:
            print(f"[-] Failed to install '{package_name}': {e}")
            return False
    else:
        print(f"[-] Skipped installation of '{package_name}'. Export for this format cannot proceed.")
        return False

def test_path_writable(path):
    """Tests if a given path is writable on Android/Termux."""
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, ".perm_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True, path
    except Exception as e:
        return False, str(e)

def ensure_directory_exists(path):
    """Utility to safely create directory and fallback to internal if Android permission is denied."""
    ok, err = test_path_writable(path)
    if ok:
        return path
    
    print(f"[-] Warning: Cannot write to '{path}': {err}")
    fallback = os.path.expanduser("~/Feed2ebook_Articles")
    print(f"[!] Falling back to internal storage directory: '{fallback}'")
    test_path_writable(fallback)
    return fallback

def load_config():
    """Load configuration with default fallback."""
    default_config = {
        "download_path": "/sdcard/Download/Feed2ebook_Articles",
        "max_days": 7,
        "max_articles_per_feed": 20,
        "export_format": "epub",  # Options: 'epub', 'xml', 'html', 'md', 'all'
        "include_images": True,
        "toc_style": "auto"       # Default: 'auto'
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                default_config.update(cfg)
        except Exception:
            pass

    if default_config["export_format"] not in VALID_FORMATS:
        default_config["export_format"] = "epub"

    if default_config.get("toc_style") not in TOC_MODES:
        default_config["toc_style"] = "auto"

    default_config["download_path"] = ensure_directory_exists(default_config["download_path"])
    return default_config

def save_config(config):
    """Saves current configuration and persists choices."""
    config["download_path"] = ensure_directory_exists(config["download_path"])
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def choose_export_path_cli(config):
    """Interactive path selection menu."""
    print("\n=========================================")
    print("      Choose Export Output Path          ")
    print("=========================================")
    print(f"Current Path: {config['download_path']}\n")
    print("Available Presets:")
    for key, (path, desc) in PRESET_PATHS.items():
        writable, _ = test_path_writable(path)
        status = "[Writable]" if writable else "[Access Denied/Not Setup]"
        print(f"  {key}. {desc} {status}")
        print(f"     Path: {path}")
    print("  4. Enter Custom Path Manually")
    
    choice = input("\nSelect location option (1-4) or press Enter to keep current: ").strip()
    
    selected_path = None
    if choice in PRESET_PATHS:
        selected_path = PRESET_PATHS[choice][0]
    elif choice == "4":
        custom = input("Enter full custom directory path: ").strip()
        if custom:
            selected_path = custom

    if selected_path:
        writable, err = test_path_writable(selected_path)
        if writable:
            config["download_path"] = selected_path
            save_config(config)
            print(f"\n[+] Export path updated successfully to:\n    {selected_path}")
        else:
            print(f"\n[-] Error: Unable to write to '{selected_path}'. Permission denied.")
            print("[-] If choosing phone downloads, run 'termux-setup-storage' in Termux first.")

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

def run_diagnostics():
    """Auto-checks environment, write permissions, and tests EPUB export."""
    print("\n=========================================")
    print("   Feed2ebook System Diagnostics Check   ")
    print("=========================================")
    config = load_config()
    target_path = config["download_path"]

    print(f"\n[1/4] Checking Core Python Libraries...")
    libs = ["requests", "bs4", "feedparser", "readability", "ebooklib"]
    for lib in libs:
        try:
            __import__(lib)
            print(f"  [+] {lib}: Installed")
        except ImportError:
            print(f"  [-] {lib}: MISSING! (Install using: pip install {lib})")

    print(f"\n[2/4] Checking Markdown Support Library...")
    installed = importlib.util.find_spec("markdownify") is not None
    status = "Installed" if installed else "Not Installed (Can auto-install on export)"
    print(f"  [*] markdownify: {status}")

    print(f"\n[3/4] Checking Output Storage Path: '{target_path}'...")
    writable, err = test_path_writable(target_path)
    if writable:
        print("  [+] Write Permission Test: PASSED")
    else:
        print(f"  [-] Write Permission Test: FAILED ({err})")
        print("  [!] FIX: Run 'termux-setup-storage' in Termux terminal and allow storage access.")

    print(f"\n[4/4] Testing EPUB Generator Engine...")
    try:
        dummy_book = epub.EpubBook()
        dummy_book.set_identifier("diag_123")
        dummy_book.set_title("Test Document")
        dummy_book.set_language("en")
        
        chap = epub.EpubHtml(title="Test", file_name="test.xhtml", lang="en")
        chap.content = "<html><body><h1>Diagnostic Test</h1></body></html>"
        dummy_book.add_item(chap)
        dummy_book.toc = (chap,)
        dummy_book.add_item(epub.EpubNcx())
        dummy_book.add_item(epub.EpubNav())
        dummy_book.spine = ['nav', chap]

        diag_epub_path = os.path.join(target_path, "_diagnostic_test.epub")
        epub.write_epub(diag_epub_path, dummy_book, {})
        if os.path.exists(diag_epub_path):
            os.remove(diag_epub_path)
            print("  [+] EPUB Creation Test: PASSED")
        else:
            print("  [-] EPUB Creation Test: FAILED (File not created)")
    except Exception as e:
        print(f"  [-] EPUB Creation Test Error: {e}")
        print(f"  [!] Traceback: {traceback.format_exc()}")

    print("=========================================\n")

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

def extract_full_html_readability(url, include_images=True):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    
    doc = Document(response.text)
    clean_html = doc.summary()
    
    soup = BeautifulSoup(clean_html, "html.parser")
    
    for tag in soup.find_all(True):
        if tag.name in ["script", "style", "iframe", "form", "button", "nav", "footer"]:
            tag.decompose()
        elif tag.name == "img" and not include_images:
            tag.decompose()
        elif getattr(tag, 'attrs', None):
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in ["href", "src", "alt", "title"]}
            
    return doc.title(), str(soup)

def process_and_embed_images(html_content, book, base_url=""):
    """Downloads images in HTML and embeds them inside EPUB document structure."""
    soup = BeautifulSoup(html_content, "html.parser")
    images = soup.find_all("img")
    
    for idx, img in enumerate(images):
        src = img.get("src")
        if not src:
            continue
        
        full_img_url = urllib.parse.urljoin(base_url, src)
        try:
            img_res = requests.get(full_img_url, headers=HEADERS, timeout=10)
            if img_res.status_code == 200:
                ext = full_img_url.split(".")[-1].lower().split("?")[0]
                if ext not in ["jpg", "jpeg", "png", "gif", "webp"]:
                    ext = "jpg"
                    
                media_type = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
                image_filename = f"images/img_{int(time.time())}_{idx}.{ext}"
                
                epub_img = epub.EpubItem(
                    uid=f"img_{int(time.time())}_{idx}",
                    file_name=image_filename,
                    media_type=media_type,
                    content=img_res.content
                )
                book.add_item(epub_img)
                img["src"] = image_filename
        except Exception:
            pass

    return str(soup)

def group_articles_by_feed(articles_data):
    """Groups flat article list into a dict: {feed_title: [article_dict, ...]} preserving order."""
    grouped = defaultdict(list)
    for article in articles_data:
        grouped[article['feed_title']].append(article)
    return grouped

def generate_toc_html(grouped_articles, is_epub=False, mode="auto"):
    """
    Generates Table of Contents HTML based on chosen mode:
    'auto' / 'disabled': Returns empty string (letting e-reader handle nav or disabling)
    'simple'  : Bulleted list grouped by feed with direct headline links
    'advanced': Detailed structured table with article #, headline, and original source links
    """
    if mode in ["disabled", "auto"]:
        return ""

    toc_html = """
    <div class="toc-container" style="font-family: sans-serif; margin-bottom: 20px; width: 100%; box-sizing: border-box;">
        <h1 style="border-bottom: 2px solid #333; padding-bottom: 5px; font-size: 1.5em;">Table of Contents</h1>
    """

    if mode == "simple":
        for feed_title, articles in grouped_articles.items():
            toc_html += f"""
            <h3 style="color: #2c3e50; margin-top: 15px; font-size: 1.1em;">Feed: {feed_title}</h3>
            <ul style="line-height: 1.6; margin-left: 20px; padding-left: 0;">
            """
            for item in articles:
                href_target = f"{item['epub_filename']}#art_{id(item)}" if is_epub else f"#art_{id(item)}"
                toc_html += f"""
                <li>
                    <a href="{href_target}">{item['title']}</a> 
                    <span style="font-size: 0.85em; color: #666;">(<a href="{item['url']}" target="_blank">Source</a>)</span>
                </li>
                """
            toc_html += "</ul>"

    if mode == "advanced":
        for feed_title, articles in grouped_articles.items():
            toc_html += f"""
            <h3 style="color: #2c3e50; margin-top: 15px; font-size: 1.1em;">RSS Feed: {feed_title}</h3>
            <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; table-layout: auto; margin-bottom: 15px; box-sizing: border-box;">
                <thead>
                    <tr style="background-color: #f2f2f2;">
                        <th style="width: 8%; text-align: center;">#</th>
                        <th>Article Headline / Title</th>
                        <th style="width: 25%; text-align: center;">Original Link</th>
                    </tr>
                </thead>
                <tbody>
            """
            for idx, item in enumerate(articles, 1):
                href_target = f"{item['epub_filename']}#art_{id(item)}" if is_epub else f"#art_{id(item)}"
                toc_html += f"""
                    <tr>
                        <td style="text-align: center;">{idx}</td>
                        <td style="word-break: break-word;"><b><a href="{href_target}">{item['title']}</a></b></td>
                        <td style="word-break: break-all; text-align: center;"><a href="{item['url']}" target="_blank">Source</a></td>
                    </tr>
                """
            toc_html += """
                </tbody>
            </table>
            """
        
    toc_html += "</div><hr style='margin: 20px 0;'/>"
    return toc_html

def build_epub(articles_data, output_dir, base_filename, include_images=True, toc_style="auto"):
    print(f"[+] Building EPUB file with {len(articles_data)} article(s) (TOC Style: {toc_style.upper()})...")
    try:
        output_dir = ensure_directory_exists(output_dir)
        book = epub.EpubBook()
        book.set_identifier(str(time.time()))
        book.set_title(base_filename)
        book.set_language('en')
        book.add_author("Feed2ebook")

        chapters = []
        spine = []

        if toc_style == "auto":
            spine.append('nav')

        global_idx = 0
        for item in articles_data:
            global_idx += 1
            item['epub_filename'] = f"chap_{global_idx}.xhtml"

        grouped = group_articles_by_feed(articles_data)

        if toc_style not in ["disabled", "auto"]:
            toc_content = generate_toc_html(grouped, is_epub=True, mode=toc_style)
            toc_chap = epub.EpubHtml(title="Table of Contents", file_name="toc.xhtml", lang="en")
            toc_chap.content = f"<html><body>{toc_content}</body></html>"
            book.add_item(toc_chap)
            spine.append(toc_chap)

        for feed_title, items in grouped.items():
            for item in items:
                html = item['html_content']
                if include_images:
                    html = process_and_embed_images(html, book, base_url=item['url'])

                c = epub.EpubHtml(title=item['title'], file_name=item['epub_filename'], lang='en')
                c.content = f"""
                <html>
                <head><title>{item['title']}</title></head>
                <body>
                    <div id="art_{id(item)}">
                        <p style="color: #777; font-size: 0.9em;"><b>RSS Feed:</b> {feed_title}</p>
                        <h2>{item['title']}</h2>
                        <p><a href='{item['url']}'>Original Source</a></p>
                        <hr/>
                        <div class="article-body">{html}</div>
                    </div>
                </body>
                </html>
                """
                book.add_item(c)
                chapters.append(c)
                spine.append(c)

        book.toc = tuple(chapters)
        book.add_item(epub.EpubNcx())
        
        nav_item = epub.EpubNav()
        book.add_item(nav_item)
        
        book.spine = spine

        clean_name = sanitize_filename(base_filename)
        epub_filepath = os.path.join(output_dir, f"{clean_name}.epub")
        epub.write_epub(epub_filepath, book, {})
        print(f"[+] EPUB successfully saved: {epub_filepath}")
    except Exception as e:
        print(f"[-] Failed to generate EPUB file: {e}")

def build_html(articles_data, output_dir, base_filename, toc_style="auto"):
    print(f"[+] Building KOReader-compatible HTML file with {len(articles_data)} article(s)...")
    try:
        output_dir = ensure_directory_exists(output_dir)
        grouped = group_articles_by_feed(articles_data)
        
        toc_html = generate_toc_html(grouped, is_epub=False, mode=toc_style)

        body_content = ""
        for feed_title, items in grouped.items():
            body_content += f"<h1 style='background:#2c3e50; color:#fff; padding:8px; margin-top:30px; font-size:1.4em;'>Feed: {feed_title}</h1>"
            for item in items:
                body_content += f"""
                <article id="art_{id(item)}" style="margin-bottom: 30px; padding-bottom:15px; border-bottom:1px solid #ccc; width:100%; box-sizing:border-box;">
                    <h2 style="font-size:1.25em;">{item['title']}</h2>
                    <p style="font-size:0.9em; color:#555;"><b>Feed:</b> {feed_title} | <a href="{item['url']}">Original Source</a></p>
                    <hr/>
                    <div class="article-body">{item['html_content']}</div>
                </article>
                """

        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{base_filename}</title>
            <style>
                * {{ box-sizing: border-box; max-width: 100% !important; }}
                html, body {{
                    margin: 0; padding: 8px; width: 100%;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    line-height: 1.5; color: #000; background-color: #fff;
                    word-wrap: break-word; overflow-x: hidden;
                }}
                img {{ max-width: 100% !important; height: auto !important; display: block; margin: 10px auto; }}
                table {{ border-collapse: collapse; width: 100% !important; table-layout: auto; }}
                pre, code {{ white-space: pre-wrap; word-break: break-all; }}
            </style>
        </head>
        <body>
            {toc_html}
            {body_content}
        </body>
        </html>
        """

        clean_name = sanitize_filename(base_filename)
        html_filepath = os.path.join(output_dir, f"{clean_name}.html")
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(full_html)
        print(f"[+] E-reader ready HTML saved: {html_filepath}")
    except Exception as e:
        print(f"[-] Error generating HTML export: {e}")

def build_markdown(articles_data, output_dir, base_filename, toc_style="auto"):
    if not check_and_install_package("markdownify"):
        return

    from markdownify import markdownify as md

    print(f"[+] Building Markdown (.md) file...")
    try:
        output_dir = ensure_directory_exists(output_dir)
        grouped = group_articles_by_feed(articles_data)

        md_output = f"# {base_filename}\n\n"

        if toc_style not in ["disabled", "auto"]:
            md_output += "## Table of Contents\n\n"
            for feed_title, items in grouped.items():
                md_output += f"### Feed: {feed_title}\n\n"
                if toc_style == "simple":
                    for item in items:
                        md_output += f"- [{item['title']}]({item['url']})\n"
                    md_output += "\n"
                if toc_style == "advanced":
                    md_output += "| # | Title | Link |\n|---|---|---|\n"
                    for idx, item in enumerate(items, 1):
                        clean_title = item['title'].replace("|", "-")
                        md_output += f"| {idx} | {clean_title} | [Source]({item['url']}) |\n"
                    md_output += "\n"
            md_output += "---\n\n"

        for feed_title, items in grouped.items():
            md_output += f"# Feed: {feed_title}\n\n"
            for item in items:
                md_output += f"## {item['title']}\n"
                md_output += f"**Source:** [{item['url']}]({item['url']})\n\n"
                markdown_article = md(item['html_content'], heading_style="ATX")
                md_output += f"{markdown_article}\n\n---\n\n"

        clean_name = sanitize_filename(base_filename)
        md_filepath = os.path.join(output_dir, f"{clean_name}.md")
        with open(md_filepath, "w", encoding="utf-8") as f:
            f.write(md_output)
        print(f"[+] Markdown export saved: {md_filepath}")
    except Exception as e:
        print(f"[-] Error generating Markdown export: {e}")

def export_rss_xml(articles_data, output_filepath, bundle_title):
    try:
        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")
        
        ET.SubElement(channel, "title").text = bundle_title
        ET.SubElement(channel, "link").text = "https://github.com"
        ET.SubElement(channel, "description").text = "Generated Full-Text RSS Stream by Feed2ebook"
        
        for item_data in articles_data:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = item_data['title']
            ET.SubElement(item, "link").text = item_data['url']
            ET.SubElement(item, "description").text = f"[Feed: {item_data['feed_title']}] " + item_data['html_content']
            
        tree = ET.ElementTree(rss)
        target_dir = ensure_directory_exists(os.path.dirname(output_filepath))
        final_path = os.path.join(target_dir, os.path.basename(output_filepath))
        tree.write(final_path, encoding="utf-8", xml_declaration=True)
        print(f"[+] Full-text RSS XML saved: {final_path}")
    except Exception as e:
        print(f"[-] Error generating XML export: {e}")

def process_feeds():
    config = load_config()
    feeds = load_feeds()
    
    if not feeds:
        print("[-] No RSS feeds found. Add them manually or import via OPML first.")
        return

    print(f"\n[+] Processing {len(feeds)} feed(s) in custom order with Feed2ebook Readability...")
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=config["max_days"])
    all_collected_articles = []

    # Respects the exact list order saved by the user
    for feed_url in feeds:
        print(f"\nFetching Feed: {feed_url}")
        try:
            parsed_feed = feedparser.parse(feed_url)
            feed_title = parsed_feed.feed.get("title", feed_url)
            
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
                    title, html_content = extract_full_html_readability(article_url, include_images=config.get("include_images", True))
                    
                    all_collected_articles.append({
                        "title": title or entry.get("title", "Untitled"),
                        "url": article_url,
                        "feed_title": feed_title,
                        "html_content": html_content
                    })
                    count += 1
                except Exception as e:
                    print(f"    [-] Error extracting article HTML: {e}")
        except Exception as e:
            print(f"[-] Error parsing feed URL '{feed_url}': {e}")

    if not all_collected_articles:
        print("[-] No matching articles found to compile.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    base_title = f"Feed2ebook_Digest_{timestamp}"
    fmt = config["export_format"].lower()
    inc_img = config.get("include_images", True)
    toc_style = config.get("toc_style", "auto")

    if fmt == "epub":
        build_epub(all_collected_articles, config["download_path"], base_title, include_images=inc_img, toc_style=toc_style)
    elif fmt == "html":
        build_html(all_collected_articles, config["download_path"], base_title, toc_style=toc_style)
    elif fmt == "md":
        build_markdown(all_collected_articles, config["download_path"], base_title, toc_style=toc_style)
    elif fmt == "xml":
        xml_filepath = os.path.join(config["download_path"], f"{sanitize_filename(base_title)}.xml")
        export_rss_xml(all_collected_articles, xml_filepath, base_title)
    elif fmt == "all":
        build_epub(all_collected_articles, config["download_path"], base_title, include_images=inc_img, toc_style=toc_style)
        build_html(all_collected_articles, config["download_path"], base_title, toc_style=toc_style)
        build_markdown(all_collected_articles, config["download_path"], base_title, toc_style=toc_style)
        xml_filepath = os.path.join(config["download_path"], f"{sanitize_filename(base_title)}.xml")
        export_rss_xml(all_collected_articles, xml_filepath, base_title)

    print("\n[+] Feed2ebook processing completed!")

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)     
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN) 
    curses.init_pair(3, curses.COLOR_GREEN, -1)    
    curses.init_pair(4, curses.COLOR_YELLOW, -1)   
    curses.init_pair(5, curses.COLOR_RED, -1)      
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)  

def draw_tui_menu(stdscr, selected_row, options, title="=== Feed2ebook Manager v0.2.1 ==="):
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

def select_toc_style_cli(config):
    print("\n=========================================")
    print("      Select Table of Contents Style     ")
    print("=========================================")
    print(f"Current TOC Style: {config.get('toc_style', 'auto').upper()}\n")
    print("Options:")
    print("  1. Auto     (Default e-reader native nav list)")
    print("  2. Disable  (No custom TOC generated)")
    print("  3. Simple   (Bulleted custom HTML list)")
    print("  4. Advanced (Detailed custom HTML table)")
    
    choice = input("\nSelect option (1-4): ").strip()
    mapping = {"1": "auto", "2": "disabled", "3": "simple", "4": "advanced"}
    if choice in mapping:
        config["toc_style"] = mapping[choice]
        save_config(config)
        print(f"\n[+] Table of Contents style set to: {config['toc_style'].upper()}")

def curses_tui_loop(stdscr):
    curses.curs_set(0)
    init_colors()
    current_row = 0
    
    while True:
        config = load_config()
        feeds = load_feeds()
        img_status = "ENABLED" if config.get("include_images", True) else "DISABLED"
        toc_mode = config.get("toc_style", "auto").upper()
        
        menu_items = [
            (f"Run Processing Pipeline (Target: {config['export_format'].upper()})", 3),
            (f"Manage & Reorder Feeds ({len(feeds)} active)", 1),
            (f"Import OPML Subscriptions", 6),
            (f"Export OPML Subscriptions", 6),
            (f"Select Export Directory Path", 4),
            (f"Toggle Article Images (Current: {img_status})", 4),
            (f"Change Table of Contents Mode (Current: {toc_mode})", 4),
            (f"Configure Settings (Format: {config['export_format'].upper()}, Days: {config['max_days']})", 4),
            ("Run System Diagnostics & Health Check", 4),
            ("Switch to Classic CLI Menu", 1),
            ("Exit Program", 5)
        ]
        
        current_row = max(0, min(current_row, len(menu_items) - 1))
        draw_tui_menu(stdscr, current_row, menu_items)
        key = stdscr.getch()

        if key in [curses.KEY_UP, ord('k')]:
            current_row = max(0, current_row - 1)
        elif key in [curses.KEY_DOWN, ord('j')]:
            current_row = min(len(menu_items) - 1, current_row + 1)
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
                choose_export_path_cli(config)
            elif current_row == 5:
                config["include_images"] = not config.get("include_images", True)
                save_config(config)
                print(f"\n[+] Image fetching option is now: {'ENABLED' if config['include_images'] else 'DISABLED'}")
            elif current_row == 6:
                select_toc_style_cli(config)
            elif current_row == 7:
                settings_cli()
            elif current_row == 8:
                run_diagnostics()
            elif current_row == 9:
                return "cli"
            elif current_row == 10:
                return "exit"
            
            input("\nPress Enter to return to Feed2ebook TUI...")
            stdscr = curses.initscr()
            curses.curs_set(0)
        elif key in [ord('q'), ord('Q')]:
            return "cli"

def manage_feeds_cli():
    """Interactive feed manager allowing addition, deletion, and reordering (move up/down)."""
    while True:
        feeds = load_feeds()
        print("\n=========================================")
        print("          Manage & Reorder Feeds         ")
        print("=========================================")
        if not feeds:
            print("[-] No feeds currently saved.")
        else:
            for idx, f in enumerate(feeds, 1):
                print(f"  {idx}. {f}")
        
        print("\nCommands:")
        print("  [URL]           -> Add a new feed URL")
        print("  [del <number>]  -> Delete feed by number (e.g., del 2)")
        print("  [u <number>]    -> Move feed UP (e.g., u 3)")
        print("  [d <number>]    -> Move feed DOWN (e.g., d 1)")
        print("  [clear all]     -> Delete all feeds (requires confirmation)")
        print("  [Press Enter]   -> Return to main menu")
        
        choice = input("\nEnter command: ").strip()
        if not choice:
            break
            
        parts = choice.split()
        cmd = parts[0].lower()
        
        if cmd == "del" and len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(feeds):
                removed = feeds.pop(idx)
                save_feeds(feeds)
                print(f"[+] Removed feed: {removed}")
            else:
                print("[-] Invalid feed number.")
        elif cmd == "clear" and len(parts) > 1 and parts[1].lower() == "all":
            confirm = input("Are you sure you want to delete ALL feeds? Type 'yes' to confirm: ").strip().lower()
            if confirm == "yes":
                save_feeds([])
                print("[+] All feeds have been deleted.")
            else:
                print("[-] Action cancelled.")
        elif cmd == "u" and len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 < idx < len(feeds):
                # Swap with previous element
                feeds[idx], feeds[idx - 1] = feeds[idx - 1], feeds[idx]
                save_feeds(feeds)
                print(f"[+] Moved feed #{idx + 1} UP.")
            else:
                print("[-] Feed is already at the top or invalid index.")
        elif cmd == "d" and len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(feeds) - 1:
                # Swap with next element
                feeds[idx], feeds[idx + 1] = feeds[idx + 1], feeds[idx]
                save_feeds(feeds)
                print(f"[+] Moved feed #{idx + 1} DOWN.")
            else:
                print("[-] Feed is already at the bottom or invalid index.")
        elif choice.startswith("http"):
            feeds.append(choice)
            save_feeds(feeds)
            print("[+] New feed added successfully.")
        else:
            print("[-] Unknown command format. Try again.")

def import_opml_cli():
    path = input("Enter path to OPML file (e.g., /sdcard/Download/subscriptions.opml): ").strip()
    new_feeds = import_opml(path)
    if new_feeds:
        existing = load_feeds()
        merged = existing + [f for f in new_feeds if f not in existing]
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
    img_status = "ENABLED" if config.get("include_images", True) else "DISABLED"
    toc_mode = config.get("toc_style", "auto").upper()
    
    print(f"\nCurrent Settings:")
    print(f"A. Max Article Age (Days): {config['max_days']}")
    print(f"B. Max Articles Per Feed: {config['max_articles_per_feed']}")
    print(f"C. Export Format ({', '.join(VALID_FORMATS)}): {config['export_format']}")
    print(f"D. Download Path: {config['download_path']}")
    print(f"E. Include Article Images: {img_status}")
    print(f"F. Choose Output Path (Presets Menu)")
    print(f"G. Table of Contents Mode: {toc_mode}")
    
    field = input("Choose setting to modify (A/B/C/D/E/F/G) or press Enter to return: ").strip().upper()
    if field == "A":
        config["max_days"] = int(input("Enter max days: ").strip())
        save_config(config)
    elif field == "B":
        config["max_articles_per_feed"] = int(input("Enter max articles per feed: ").strip())
        save_config(config)
    elif field == "C":
        print(f"Available formats: {', '.join(VALID_FORMATS)}")
        fmt = input("Enter format choice: ").strip().lower()
        if fmt in VALID_FORMATS:
            if fmt == "md":
                check_and_install_package("markdownify")
            config["export_format"] = fmt
            save_config(config)
        else:
            print("[-] Invalid format option.")
    elif field == "D":
        new_path = input("Enter new path: ").strip()
        if new_path:
            config["download_path"] = new_path
            save_config(config)
    elif field == "E":
        config["include_images"] = not config.get("include_images", True)
        save_config(config)
        print(f"[+] Images setting updated to: {config['include_images']}")
    elif field == "F":
        choose_export_path_cli(config)
    elif field == "G":
        select_toc_style_cli(config)

def main_cli_menu():
    while True:
        config = load_config()
        img_status = "ENABLED" if config.get("include_images", True) else "DISABLED"
        toc_mode = config.get("toc_style", "auto").upper()
        
        print("\n=== Feed2ebook Manager v0.2.1 ===")
        print(f"1. Run Downloader (Format: {config['export_format'].upper()})")
        print(f"2. Manage & Reorder Feeds ({len(load_feeds())} currently saved)")
        print("3. Import OPML File")
        print("4. Export OPML File")
        print("5. Choose Export Path Location")
        print(f"6. Toggle Article Images (Current: {img_status})")
        print(f"7. Select TOC Mode (Current: {toc_mode})")
        print(f"8. Settings (Format: {config['export_format'].upper()}, Days limit: {config['max_days']})")
        print("9. Run System Diagnostics & Health Check")
        print("10. Launch TUI Graphical Menu")
        print("11. Exit")
        
        choice = input("Select an option (1-11): ").strip()
        
        if choice == "1":
            process_feeds()
        elif choice == "2":
            manage_feeds_cli()
        elif choice == "3":
            import_opml_cli()
        elif choice == "4":
            export_opml_cli()
        elif choice == "5":
            choose_export_path_cli(config)
        elif choice == "6":
            config["include_images"] = not config.get("include_images", True)
            save_config(config)
            print(f"[+] Image fetching setting updated to: {'ENABLED' if config['include_images'] else 'DISABLED'}")
        elif choice == "7":
            select_toc_style_cli(config)
        elif choice == "8":
            settings_cli()
        elif choice == "9":
            run_diagnostics()
        elif choice == "10":
            res = curses.wrapper(curses_tui_loop)
            if res == "exit":
                break
        elif choice == "11":
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
