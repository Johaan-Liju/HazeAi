"""
Website crawler that builds a knowledge base for the chatbot.

Give it a company's website. It visits the pages on that site, pulls out the
readable text, removes menus/footers that repeat on every page, and writes
everything into knowledge.txt — the same file chatbot.py reads.

Usage:
    python crawl.py https://coverfirst.in
    python crawl.py coverfirst.in            (https:// is added for you)
    python crawl.py https://example.com 200  (crawl up to 200 pages)

⚠️  This OVERWRITES knowledge.txt. If you've hand-edited that file and want to
    keep it, make a copy first (e.g. copy knowledge.txt knowledge_backup.txt).
"""

import sys
import time
import re
from urllib.parse import urljoin, urlparse, urldefrag
from urllib import robotparser

import requests
from bs4 import BeautifulSoup

# ---- Settings you can tweak -------------------------------------------------
OUTPUT_FILE = "knowledge.txt"   # where the crawled text is saved
MAX_PAGES = 100                 # safety cap so it can't crawl forever
DELAY_SECONDS = 0.5             # pause between requests, to be polite to the site
REQUEST_TIMEOUT = 15            # give up on a slow page after this many seconds
USER_AGENT = "KnowledgeBaseBot/1.0 (+chatbot knowledge crawler)"

# File types that aren't web pages — we skip these.
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".zip", ".mp4", ".mp3", ".woff", ".woff2", ".ttf",
    ".xml", ".json",
)


def normalize(url):
    """Drop the #fragment and trailing slash so /page and /page#top match."""
    return urldefrag(url)[0].rstrip("/")


def domain_of(url):
    """Return the site's domain without a leading 'www.'."""
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def looks_like_page(url):
    """Only crawl real web pages (skip images, PDFs, mailto:, tel:, etc.)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    return not parsed.path.lower().endswith(SKIP_EXTENSIONS)


def fetch_html(url):
    """Download a page; return its HTML, or None if it fails / isn't a web page."""
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as e:
        print(f"    ! skipped ({e.__class__.__name__})")
        return None
    if resp.status_code != 200:
        print(f"    ! skipped (HTTP {resp.status_code})")
        return None
    if "text/html" not in resp.headers.get("Content-Type", ""):
        return None
    return resp.text


def find_links(soup, base_url):
    """All links on the page, turned into full absolute URLs."""
    return [normalize(urljoin(base_url, a["href"])) for a in soup.find_all("a", href=True)]


# Short navigation / button / decoration labels that add noise, not information.
JUNK_LABELS = {
    "home", "products", "why us", "about", "contact", "careers", "retail",
    "corporate", "become an isp", "get a quote", "get a quote →", "get quote",
    "get quote →", "explore products", "explore plans", "talk to an advisor",
    "read more", "learn more", "whatsapp", "plans from", "& more", "ai tools",
    "how it works", "menu", "close",
}


def is_junk(line):
    """True for lines that are navigation, buttons, or decoration — not content."""
    stripped = line.strip()
    if len(stripped) <= 2:                       # single characters like ◆ ★ × ·
        return True
    if not re.search(r"[A-Za-z0-9]", stripped):  # symbols/punctuation only, no words
        return True
    if stripped.lower() in JUNK_LABELS:          # known menu/button labels
        return True
    # Short call-to-action buttons ending in an arrow (e.g. "Get Car Quote →").
    if stripped.endswith(("→", "»", "›")) and len(stripped.split()) <= 4:
        return True
    return False


def extract_lines(soup):
    """Turn a page's HTML into clean, non-empty lines of readable text."""
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()  # remove code/graphics that isn't readable content
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    return [line for line in lines if line and not is_junk(line)]


def main():
    if len(sys.argv) < 2:
        sys.exit(
            "Usage: python crawl.py <website-url> [max-pages] [output-file]\n"
            "Example: python crawl.py https://coverfirst.in 100 coverfirst.txt"
        )

    # Accept a bare domain like "coverfirst.in" by adding the scheme.
    raw = sys.argv[1]
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    start_url = normalize(raw)
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_PAGES
    output_file = sys.argv[3] if len(sys.argv) > 3 else OUTPUT_FILE
    site = domain_of(start_url)

    # Respect the site's robots.txt (the rules it publishes for crawlers).
    robots = robotparser.RobotFileParser()
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    robots.set_url(f"{base}/robots.txt")
    try:
        robots.read()
    except Exception:
        pass  # no robots.txt or unreachable — proceed politely anyway

    queue = [start_url]         # pages waiting to be visited
    visited = set()             # pages we've already handled
    seen_lines = set()          # text we've already saved (kills repeated menus)
    pages_saved = 0

    print(f"Crawling {site} (up to {max_pages} pages)...\n")

    with open(output_file, "w", encoding="utf-8") as out:
        while queue and pages_saved < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            if not robots.can_fetch(USER_AGENT, url):
                continue

            print(f"[{pages_saved + 1}/{max_pages}] {url}")
            html = fetch_html(url)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")

            # Queue up new internal links (same site only).
            for link in find_links(soup, url):
                if (
                    link not in visited
                    and looks_like_page(link)
                    and domain_of(link) == site
                ):
                    queue.append(link)

            # Save only lines we haven't already seen on another page.
            new_lines = [ln for ln in extract_lines(soup) if ln not in seen_lines]
            seen_lines.update(new_lines)

            if new_lines:
                out.write(f"\n===== {url} =====\n")
                out.write("\n".join(new_lines) + "\n")
                pages_saved += 1

            time.sleep(DELAY_SECONDS)

    print(f"\nDone. Saved {pages_saved} pages to {output_file}.")
    print("Skim the file and delete any leftover menu/button/junk text before using it —")
    print("cleaner knowledge means better, cheaper answers.")


if __name__ == "__main__":
    main()
