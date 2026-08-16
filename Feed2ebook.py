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
import io

import feedparser
import requests
from readability import Document
from bs4 import BeautifulSoup
from ebooklib import epub

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
FEEDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feeds.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
}

PRESET_PATHS = {
    "1": ("/sdcard/Download/Feed2ebook_Articles", "Phone Downloads Folder (/sdcard/Download)"),
    "2": (os.path.expanduser("~/storage/downloads/Feed2ebook_Articles"), "Termux Shared Downloads (~/storage/downloads)"),
    "3": (os.path.expanduser("~/Feed2ebook_Articles"), "Termux Internal Storage (~/Feed2ebook_Articles)"),
}

VALID_FORMATS = ["epub", "xml", "html", "md", "all"]
TOC_MODES = ["auto", "disabled", "simple", "advanced"]

def check_and_install_package(package_name, import_name=None):
    """Checks if a module is installed; prompts user to install via pkg (Termux) or pip if missing."""
    import_module = import_name or package_name
    if importlib.util.find_spec(import_module) is not None:
        return True

    print(f"\n[!] Required package '{package_name}' is not installed.")
    choice = input(f"Would you like to install '{package_name}' now? (y/n): ").strip().lower()
    
    if choice == 'y':
        print(f"[+] Installing '{package_name}'...")
        is_termux = "com.termux" in sys.executable or os.path.exists("/data/data/com.termux")

        if is_termux and package_name.lower() == "pillow":
            try:
                print("[+] Termux detected. Installing pre-compiled 'python-pillow' via pkg...")
                subprocess.check_call(["pkg", "install", "python-pillow", "-y"])
                print(f"[+] Package '{package_name}' installed successfully!")
                return True
            except Exception as e:
                print(f"[-] 'pkg install python-pillow' failed: {e}")
                print("[+] Attempting to install build tools and run pip...")
                try:
                    subprocess.check_call(["pkg", "install", "libjpeg-turbo", "zlib", "clang", "make", "-y"])
                    subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
                    print(f"[+] Package '{package_name}' installed successfully!")
                    return True
                except Exception as pip_err:
                    print(f"[-] Failed to install '{package_name}': {pip_err}")
                    return False

        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            print(f"[+] Package '{package_name}' installed successfully!")
            return True
        except Exception as e:
            print(f"[-] Failed to install '{package_name}': {e}")
            return False
    else:
        print(f"[-] Skipped installation of '{package_name}'.")
        return False

def check_image_dependencies():
    """Verifies that Pillow (PIL) is available for image processing."""
    return check_and_install_package("Pillow", import_name="PIL")

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
        "max_days": 7,                    # 0 or None means unlimited days
        "max_articles_per_day": 20,       # Number of feeds per day
        "total_articles_limit": 0,        # unlimited feed as default , per rss feed
        "export_format": "epub",          # Options: 'epub', 'xml', 'html', 'md', 'all'
        "include_images": True,
        "toc_style": "simple",            # Default: 'simple'
        "image_quality": 60,              # Compression quality (1-95)
        "max_image_width": 800            # Maximum width in pixels
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
    """Loads feeds from JSON file (supports string URLs and dict structures)."""
    if os.path.exists(FEEDS_FILE):
        try:
            with open(FEEDS_FILE, "r") as f:
                data = json.load(f)
                normalized = []
                for item in data:
                    if isinstance(item, str):
                        normalized.append({"url": item})
                    elif isinstance(item, dict) and "url" in item:
                        normalized.append(item)
                return normalized
        except Exception:
            pass
    return []

def save_feeds(feeds):
    """Saves feeds list to JSON file."""
    with open(FEEDS_FILE, "w") as f:
        json.dump(feeds, f, indent=4)

def get_feed_url(feed_item):
    """Safely extracts feed URL string."""
    if isinstance(feed_item, dict):
        return feed_item.get("url", "")
    return str(feed_item)

def get_feed_setting(feed_item, key, global_config):
    """Retrieves feed-specific setting override, fallback to global config if unset."""
    if isinstance(feed_item, dict) and key in feed_item and feed_item[key] is not None:
        return feed_item[key]
    return global_config.get(key)

def run_diagnostics():
    """Auto-checks environment, write permissions, and tests EPUB export."""
    print("\n=========================================")
    print("   Feed2ebook System Diagnostics Check   ")
    print("=========================================")
    config = load_config()
    target_path = config["download_path"]

    print(f"\n[1/4] Checking Core Python Libraries...")
    libs = [
        ("requests", "requests"),
        ("bs4", "bs4"),
        ("feedparser", "feedparser"),
        ("readability", "readability"),
        ("ebooklib", "ebooklib"),
        ("Pillow", "PIL")
    ]
    for pkg_name, import_name in libs:
        if importlib.util.find_spec(import_name) is not None:
            print(f"  [+] {pkg_name} ({import_name}): Installed")
        else:
            print(f"  [-] {pkg_name}: MISSING! (Install using: pip install {pkg_name})")

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
    
    for item in feeds:
        url = get_feed_url(item)
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

def extract_media_urls_from_entry(entry):
    """Extracts explicit media/image URLs directly from RSS feed item entries."""
    urls = []
    if not entry:
        return urls

    if hasattr(entry, 'enclosures'):
        for enc in entry.enclosures:
            if getattr(enc, 'type', '').startswith('image/') or getattr(enc, 'href', '').split('?')[0].lower().endswith(('jpg', 'jpeg', 'png', 'gif', 'webp', 'avif')):
                if 'href' in enc and enc.href not in urls:
                    urls.append(enc.href)
    if hasattr(entry, 'media_content'):
        for media in entry.media_content:
            if 'url' in media and (media.get('medium') == 'image' or media.get('type', '').startswith('image/')):
                if media['url'] not in urls:
                    urls.append(media['url'])
    if hasattr(entry, 'media_thumbnail'):
        for thumb in entry.media_thumbnail:
            if 'url' in thumb and thumb['url'] not in urls:
                urls.append(thumb['url'])
    return urls

def parse_srcset(srcset_str):
    """Parses srcset attribute string and returns the URL with highest resolution descriptor."""
    candidates = []
    for item in srcset_str.split(','):
        parts = item.strip().split()
        if not parts:
            continue
        url = parts[0]
        size = 0
        if len(parts) > 1:
            descriptor = parts[1].lower()
            if descriptor.endswith('w'):
                try: size = int(descriptor[:-1])
                except ValueError: pass
            elif descriptor.endswith('x'):
                try: size = int(float(descriptor[:-1]) * 1000)
                except ValueError: pass
        candidates.append((size, url))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None

def extract_full_html_readability(url, include_images=True, entry=None):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    
    doc = Document(response.text)
    clean_html = doc.summary()
    
    soup = BeautifulSoup(clean_html, "html.parser")

    if include_images and entry:
        rss_images = extract_media_urls_from_entry(entry)
        for img_url in rss_images:
            if not soup.find("img", src=img_url):
                img_tag = soup.new_tag("img", src=img_url)
                if soup.body:
                    soup.body.insert(0, img_tag)
                else:
                    soup.insert(0, img_tag)
    
    for tag in soup.find_all(True):
        if tag.name in ["script", "style", "iframe", "form", "button", "nav", "footer"]:
            tag.decompose()
        elif tag.name == "img" and not include_images:
            tag.decompose()
        elif getattr(tag, 'attrs', None):
            allowed_attrs = ["href", "src", "alt", "title", "data-src", "data-original", "data-lazy-src", "data-url", "data-orig-file", "srcset"]
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed_attrs}
            
    return doc.title(), str(soup)

def process_and_embed_images(html_content, book, base_url="", quality=60, max_width=800):
    """Downloads images in HTML, resizes/compresses them, and embeds inside EPUB."""
    try:
        from PIL import Image
    except ImportError:
        if not check_image_dependencies():
            return html_content
        from PIL import Image

    soup = BeautifulSoup(html_content, "html.parser")
    images = soup.find_all("img")
    
    req_headers = HEADERS.copy()
    if base_url:
        req_headers["Referer"] = base_url

    url_hash = abs(hash(base_url)) % 100000

    for idx, img in enumerate(images):
        src = None

        for attr in ["data-src", "data-original", "data-lazy-src", "data-url", "data-orig-file"]:
            if img.get(attr):
                src = img.get(attr)
                break

        if not src and img.get("srcset"):
            src = parse_srcset(img.get("srcset"))

        if not src and img.parent and img.parent.name == "picture":
            for source in img.parent.find_all("source"):
                if source.get("srcset"):
                    src = parse_srcset(source.get("srcset"))
                    if src: break
                elif source.get("src"):
                    src = source.get("src")
                    if src: break

        if not src:
            src = img.get("src")
        
        if not src or src.startswith("data:"):
            continue

        full_img_url = urllib.parse.urljoin(base_url, src)
        try:
            img_res = requests.get(full_img_url, headers=req_headers, timeout=10)
            if img_res.status_code == 200:
                raw_bytes = img_res.content
                
                try:
                    with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                        if pil_img.mode in ("RGBA", "P"):
                            pil_img = pil_img.convert("RGB")
                        
                        if pil_img.width > max_width:
                            w_percent = max_width / float(pil_img.width)
                            h_size = int(float(pil_img.height) * float(w_percent))
                            pil_img = pil_img.resize((max_width, h_size), Image.Resampling.LANCZOS)

                        out_buffer = io.BytesIO()
                        pil_img.save(out_buffer, format="JPEG", quality=quality, optimize=True)
                        processed_bytes = out_buffer.getvalue()
                        ext = "jpg"
                        media_type = "image/jpeg"
                except Exception:
                    processed_bytes = raw_bytes
                    ext = "jpg"
                    media_type = "image/jpeg"

                image_filename = f"images/img_{url_hash}_{idx}_{int(time.time())}.{ext}"
                
                epub_img = epub.EpubItem(
                    uid=f"img_{url_hash}_{idx}_{int(time.time())}",
                    file_name=image_filename,
                    media_type=media_type,
                    content=processed_bytes
                )
                book.add_item(epub_img)
                img["src"] = image_filename
                
                for attr in ["data-src", "data-original", "data-lazy-src", "data-url", "data-orig-file", "srcset"]:
                    if attr in img.attrs:
                        del img.attrs[attr]
        except Exception:
            pass

    return str(soup)

def group_articles_by_feed(articles_data):
    grouped = defaultdict(list)
    for article in articles_data:
        grouped[article['feed_title']].append(article)
    return grouped

def generate_toc_html(grouped_articles, is_epub=False, mode="auto"):
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

def build_epub(articles_data, output_dir, base_filename, include_images=True, toc_style="auto", quality=60, max_width=800):
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
                    html = process_and_embed_images(html, book, base_url=item['url'], quality=quality, max_width=max_width)

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

    if config.get("include_images", True):
        if not check_image_dependencies():
            print("[-] Image dependencies missing. Disabling images for this run.")
            config["include_images"] = False

    print(f"\n[+] Processing {len(feeds)} feed(s) with custom per-feed or global settings...")
    all_collected_articles = []

    for feed_item in feeds:
        feed_url = get_feed_url(feed_item)
        if not feed_url:
            continue

        feed_max_days = get_feed_setting(feed_item, "max_days", config)
        feed_max_per_day = get_feed_setting(feed_item, "max_articles_per_day", config)
        feed_total_limit = get_feed_setting(feed_item, "total_articles_limit", config)
        feed_include_images = get_feed_setting(feed_item, "include_images", config)

        if feed_include_images:
            if not check_image_dependencies():
                feed_include_images = False

        days_display = "Unlimited" if not feed_max_days else f"{feed_max_days} days"
        per_day_display = "Unlimited" if not feed_max_per_day else f"{feed_max_per_day}"
        total_display = "Unlimited" if not feed_total_limit else f"{feed_total_limit}"

        cutoff_date = None
        if feed_max_days and feed_max_days > 0:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=feed_max_days)

        print(f"\nFetching Feed: {feed_url} [Max Days: {days_display}, Feeds/Day: {per_day_display}, Total Limit: {total_display}]")
        
        try:
            parsed_feed = feedparser.parse(feed_url)
            feed_title = parsed_feed.feed.get("title", feed_url)
            
            total_count = 0
            daily_counts = defaultdict(int)

            for entry in parsed_feed.entries:
                if feed_total_limit and feed_total_limit > 0 and total_count >= feed_total_limit:
                    print(f" -> Total articles limit reached ({feed_total_limit}) for this feed.")
                    break
                    
                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub_date = datetime.fromtimestamp(time.mktime(entry.updated_parsed), tz=timezone.utc)
                    
                if cutoff_date and pub_date and pub_date < cutoff_date:
                    continue

                if pub_date and feed_max_per_day and feed_max_per_day > 0:
                    day_key = pub_date.strftime("%Y-%m-%d")
                    if daily_counts[day_key] >= feed_max_per_day:
                        continue
                    daily_counts[day_key] += 1
                    
                article_url = entry.link
                try:
                    print(f" -> Downloading HTML: {entry.get('title', article_url)}")
                    title, html_content = extract_full_html_readability(article_url, include_images=feed_include_images, entry=entry)
                    
                    all_collected_articles.append({
                        "title": title or entry.get("title", "Untitled"),
                        "url": article_url,
                        "feed_title": feed_title,
                        "html_content": html_content
                    })
                    total_count += 1
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
    quality = config.get("image_quality", 60)
    max_width = config.get("max_image_width", 800)

    if fmt == "epub":
        build_epub(all_collected_articles, config["download_path"], base_title, include_images=inc_img, toc_style=toc_style, quality=quality, max_width=max_width)
    elif fmt == "html":
        build_html(all_collected_articles, config["download_path"], base_title, toc_style=toc_style)
    elif fmt == "md":
        build_markdown(all_collected_articles, config["download_path"], base_title, toc_style=toc_style)
    elif fmt == "xml":
        xml_filepath = os.path.join(config["download_path"], f"{sanitize_filename(base_title)}.xml")
        export_rss_xml(all_collected_articles, xml_filepath, base_title)
    elif fmt == "all":
        build_epub(all_collected_articles, config["download_path"], base_title, include_images=inc_img, toc_style=toc_style, quality=quality, max_width=max_width)
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

def draw_tui_menu(stdscr, selected_row, options, title="=== Feed2ebook Manager v0.4.2 ==="):
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

def handle_toggle_images(config):
    """Safely handles toggling image settings by checking dependencies first."""
    target_state = not config.get("include_images", True)
    if target_state:
        if not check_image_dependencies():
            print("[-] Cannot enable article images without Pillow installed. Setting remains DISABLED.")
            return False
    
    config["include_images"] = target_state
    save_config(config)
    print(f"\n[+] Image fetching option is now: {'ENABLED' if target_state else 'DISABLED'}")
    return True

def curses_tui_loop(stdscr):
    curses.curs_set(0)
    init_colors()
    current_row = 0
    
    while True:
        config = load_config()
        feeds = load_feeds()
        img_status = "ENABLED" if config.get("include_images", True) else "DISABLED"
        toc_mode = config.get("toc_style", "auto").upper()
        days_str = "Unlimited" if not config.get("max_days") else f"{config['max_days']}d"
        
        menu_items = [
            (f"Run Processing Pipeline (Target: {config['export_format'].upper()})", 3),
            (f"Manage & Configure Feeds ({len(feeds)} active)", 1),
            (f"Import OPML Subscriptions", 6),
            (f"Export OPML Subscriptions", 6),
            (f"Select Export Directory Path", 4),
            (f"Toggle Global Article Images (Current: {img_status})", 4),
            (f"Change Table of Contents Mode (Current: {toc_mode})", 4),
            (f"Configure Settings (Format: {config['export_format'].upper()}, Days: {days_str})", 4),
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
                handle_toggle_images(config)
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

def configure_single_feed_cli(feeds, idx, global_config):
    """Submenu to manage individual settings (limits, max_days, include_images) per feed."""
    feed = feeds[idx]
    url = get_feed_url(feed)

    while True:
        days_val = feed.get("max_days")
        if days_val is not None:
            days_str = "Unlimited" if days_val == 0 else f"{days_val} days"
        else:
            g_days = global_config.get('max_days')
            days_str = f"Global Default ({'Unlimited' if not g_days else str(g_days) + ' days'})"

        day_limit_val = feed.get("max_articles_per_day")
        if day_limit_val is not None:
            day_limit_str = "Unlimited" if day_limit_val == 0 else f"{day_limit_val} articles/day"
        else:
            g_dl = global_config.get('max_articles_per_day')
            day_limit_str = f"Global Default ({'Unlimited' if not g_dl else str(g_dl) + ' articles/day'})"

        tot_limit_val = feed.get("total_articles_limit")
        if tot_limit_val is not None:
            tot_limit_str = "Unlimited" if tot_limit_val == 0 else f"{tot_limit_val} total articles"
        else:
            g_tl = global_config.get('total_articles_limit')
            tot_limit_str = f"Global Default ({'Unlimited' if not g_tl else str(g_tl) + ' total articles'})"
        
        if "include_images" in feed and feed["include_images"] is not None:
            img_str = "ENABLED" if feed["include_images"] else "DISABLED"
        else:
            img_str = f"Global Default ({'ENABLED' if global_config.get('include_images', True) else 'DISABLED'})"

        print("\n-----------------------------------------")
        print(f" Config Settings for Feed #{idx + 1}")
        print(f" URL: {url}")
        print("-----------------------------------------")
        print(f"  1. Max Article Age (Days)     : {days_str}")
        print(f"  2. Max Articles Per Day       : {day_limit_str}")
        print(f"  3. Total Articles Limit       : {tot_limit_str}")
        print(f"  4. Include Images Override    : {img_str}")
        print("  5. Reset Feed to Global Defaults")
        print("  0. Save & Return to Feed Manager")

        choice = input("\nChoose setting to modify (0-5): ").strip()
        if choice == "1":
            val = input("Enter max days (0 or 'unlimited' for Unlimited, Enter to reset to global): ").strip().lower()
            if val in ["0", "unlimited", "u"]:
                feed["max_days"] = 0
            elif val.isdigit():
                feed["max_days"] = int(val)
            elif val == "":
                feed.pop("max_days", None)
            save_feeds(feeds)
        elif choice == "2":
            val = input("Enter max articles per day (0 or 'unlimited' for Unlimited, Enter to reset to global): ").strip().lower()
            if val in ["0", "unlimited", "u"]:
                feed["max_articles_per_day"] = 0
            elif val.isdigit():
                feed["max_articles_per_day"] = int(val)
            elif val == "":
                feed.pop("max_articles_per_day", None)
            save_feeds(feeds)
        elif choice == "3":
            val = input("Enter total articles limit (0 or 'unlimited' for Unlimited, Enter to reset to global): ").strip().lower()
            if val in ["0", "unlimited", "u"]:
                feed["total_articles_limit"] = 0
            elif val.isdigit():
                feed["total_articles_limit"] = int(val)
            elif val == "":
                feed.pop("total_articles_limit", None)
            save_feeds(feeds)
        elif choice == "4":
            current = feed.get("include_images")
            if current is None or current is False:
                if check_image_dependencies():
                    feed["include_images"] = True
                else:
                    print("[-] Missing Pillow library. Image override set to DISABLED.")
                    feed["include_images"] = False
            else:
                feed.pop("include_images", None)
            save_feeds(feeds)
        elif choice == "5":
            feeds[idx] = {"url": url}
            feed = feeds[idx]
            save_feeds(feeds)
            print("[+] Reset all custom settings for this feed.")
        elif choice == "0" or choice == "":
            break

def manage_feeds_cli():
    """Interactive feed manager with per-feed settings, addition, deletion, and reordering."""
    config = load_config()
    while True:
        feeds = load_feeds()
        print("\n=========================================")
        print("        Manage & Configure Feeds         ")
        print("=========================================")
        if not feeds:
            print("[-] No feeds currently saved.")
        else:
            for idx, f in enumerate(feeds, 1):
                url = get_feed_url(f)
                opts = []
                if isinstance(f, dict):
                    if "max_days" in f and f["max_days"] is not None:
                        opts.append(f"Days: {'Unlimited' if f['max_days'] == 0 else f['max_days']}")
                    if "max_articles_per_day" in f and f["max_articles_per_day"] is not None:
                        opts.append(f"Per Day: {'Unlimited' if f['max_articles_per_day'] == 0 else f['max_articles_per_day']}")
                    if "total_articles_limit" in f and f["total_articles_limit"] is not None:
                        opts.append(f"Total: {'Unlimited' if f['total_articles_limit'] == 0 else f['total_articles_limit']}")
                    if "include_images" in f and f["include_images"] is not None:
                        opts.append(f"Images: {'ON' if f['include_images'] else 'OFF'}")
                
                opts_str = f" [{', '.join(opts)}]" if opts else " [Global Defaults]"
                print(f"  {idx}. {url}{opts_str}")
        
        print("\nCommands:")
        print("  [URL]           -> Add a new feed URL")
        print("  [s <number>]    -> Configure per-feed settings (limits, days, images)")
        print("  [del <number>]  -> Delete feed by number (e.g., del 2)")
        print("  [u <number>]    -> Move feed UP (e.g., u 3)")
        print("  [d <number>]    -> Move feed DOWN (e.g., d 1)")
        print("  [clear all]     -> Delete all feeds")
        print("  [Press Enter]   -> Return to main menu")
        
        choice = input("\nEnter command: ").strip()
        if not choice:
            break
            
        parts = choice.split()
        cmd = parts[0].lower()
        
        if cmd in ["s", "edit"] and len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(feeds):
                configure_single_feed_cli(feeds, idx, config)
            else:
                print("[-] Invalid feed number.")
        elif cmd == "del" and len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(feeds):
                removed = feeds.pop(idx)
                save_feeds(feeds)
                print(f"[+] Removed feed: {get_feed_url(removed)}")
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
                feeds[idx], feeds[idx - 1] = feeds[idx - 1], feeds[idx]
                save_feeds(feeds)
                print(f"[+] Moved feed #{idx + 1} UP.")
            else:
                print("[-] Feed is already at the top or invalid index.")
        elif cmd == "d" and len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(feeds) - 1:
                feeds[idx], feeds[idx + 1] = feeds[idx + 1], feeds[idx]
                save_feeds(feeds)
                print(f"[+] Moved feed #{idx + 1} DOWN.")
            else:
                print("[-] Feed is already at the bottom or invalid index.")
        elif choice.startswith("http"):
            feeds.append({"url": choice})
            save_feeds(feeds)
            print("[+] New feed added successfully.")
        else:
            print("[-] Unknown command format. Try again.")

def import_opml_cli():
    path = input("Enter path to OPML file (e.g., /sdcard/Download/subscriptions.opml): ").strip()
    new_feeds = import_opml(path)
    if new_feeds:
        existing = load_feeds()
        existing_urls = {get_feed_url(f) for f in existing}
        merged = existing + [{"url": f} for f in new_feeds if f not in existing_urls]
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
    days_str = "Unlimited" if not config.get("max_days") else f"{config['max_days']} days"
    per_day_str = "Unlimited" if not config.get("max_articles_per_day") else f"{config['max_articles_per_day']} articles/day"
    total_str = "Unlimited" if not config.get("total_articles_limit") else f"{config['total_articles_limit']} articles"
    quality_str = f"{config.get('image_quality', 60)}%"
    max_width_str = f"{config.get('max_image_width', 800)}px"
    
    print(f"\nCurrent Global Settings:")
    print(f"A. Max Article Age (Days)    : {days_str}")
    print(f"B. Max Articles Per Day      : {per_day_str}")
    print(f"C. Total Articles Limit      : {total_str}")
    print(f"D. Export Format ({', '.join(VALID_FORMATS)}): {config['export_format']}")
    print(f"E. Download Path             : {config['download_path']}")
    print(f"F. Include Article Images    : {img_status}")
    print(f"G. Choose Output Path (Presets Menu)")
    print(f"H. Table of Contents Mode    : {toc_mode}")
    print(f"I. Image Compression Quality : {quality_str}")
    print(f"J. Max Image Width           : {max_width_str}")
    
    field = input("Choose setting to modify (A-J) or press Enter to return: ").strip().upper()
    if field == "A":
        val = input("Enter max days (type 0 or 'unlimited' for Unlimited): ").strip().lower()
        if val in ["0", "unlimited", "u"]:
            config["max_days"] = 0
        elif val.isdigit():
            config["max_days"] = int(val)
        save_config(config)
    elif field == "B":
        val = input("Enter max articles per day (type 0 or 'unlimited' for Unlimited): ").strip().lower()
        if val in ["0", "unlimited", "u"]:
            config["max_articles_per_day"] = 0
        elif val.isdigit():
            config["max_articles_per_day"] = int(val)
        save_config(config)
    elif field == "C":
        val = input("Enter total articles limit per feed (type 0 or 'unlimited' for Unlimited): ").strip().lower()
        if val in ["0", "unlimited", "u"]:
            config["total_articles_limit"] = 0
        elif val.isdigit():
            config["total_articles_limit"] = int(val)
        save_config(config)
    elif field == "D":
        print(f"Available formats: {', '.join(VALID_FORMATS)}")
        fmt = input("Enter format choice: ").strip().lower()
        if fmt in VALID_FORMATS:
            if fmt == "md":
                check_and_install_package("markdownify")
            config["export_format"] = fmt
            save_config(config)
        else:
            print("[-] Invalid format option.")
    elif field == "E":
        new_path = input("Enter new path: ").strip()
        if new_path:
            config["download_path"] = new_path
            save_config(config)
    elif field == "F":
        handle_toggle_images(config)
    elif field == "G":
        choose_export_path_cli(config)
    elif field == "H":
        select_toc_style_cli(config)
    elif field == "I":
        if not check_image_dependencies():
            print("[-] Cannot modify image quality settings without Pillow installed.")
        else:
            val = input("Enter JPEG Quality (1-95, Default: 60): ").strip()
            if val.isdigit() and 1 <= int(val) <= 95:
                config["image_quality"] = int(val)
                save_config(config)
    elif field == "J":
        if not check_image_dependencies():
            print("[-] Cannot modify image width settings without Pillow installed.")
        else:
            val = input("Enter Max Image Width in pixels (e.g., 800): ").strip()
            if val.isdigit() and int(val) > 0:
                config["max_image_width"] = int(val)
                save_config(config)

def main_cli_menu():
    while True:
        config = load_config()
        img_status = "ENABLED" if config.get("include_images", True) else "DISABLED"
        toc_mode = config.get("toc_style", "auto").upper()
        days_str = "Unlimited" if not config.get("max_days") else f"{config['max_days']}d"
        
        print("\n=== Feed2ebook Manager v0.4.2 ===")
        print(f"1. Run Downloader (Format: {config['export_format'].upper()})")
        print(f"2. Manage & Configure Feeds ({len(load_feeds())} currently saved)")
        print("3. Import OPML File")
        print("4. Export OPML File")
        print("5. Choose Export Path Location")
        print(f"6. Toggle Global Article Images (Current: {img_status})")
        print(f"7. Select TOC Mode (Current: {toc_mode})")
        print(f"8. Settings (Format: {config['export_format'].upper()}, Days: {days_str})")
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
            handle_toggle_images(config)
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
    