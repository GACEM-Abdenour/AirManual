"""Crawler for aviation regulations. Downloads HTML from target sites to assets/regulations/."""
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Ensure project root on path when run as script
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import tldextract
except ImportError:
    tldextract = None

# Where to save downloaded HTML
REGULATIONS_DIR = _root / "assets" / "regulations"

# Target URLs for aviation regulations (placeholders + Canada Aviation)
TARGET_URLS = [
    "https://tc.canada.ca/en/corporate-services/acts-regulations/list-regulations/canadian-aviation-regulations-sor-96-433",
        
"https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/phak",
"https://tc.canada.ca/en/corporate-services/acts-regulations/list-regulations/canadian-aviation-regulations-sor-96-433/standards/standard-625-aircraft-equipment-maintenance-standard-canadian-aviation-regulations-cars",
"https://tc.canada.ca/en/corporate-services/acts-regulations/list-regulations/canadian-aviation-regulations-sor-96-433/standards/standard-573-approved-maintenance-organizations-canadian-aviation-regulations-cars",
"https://publications.aws.tpsgc-pwgsc.cloud-nuage.canada.ca/site/eng/9.620125/publication.html",
"https://www.esa.int/",
"https://www.robinsonheli.com/publications",
"https://robinsonstrapistorprod.blob.core.windows.net/uploads/assets/US_Airworthiness_Directives_07_15_25_2937fb70cc.pdf",
"https://ad.easa.europa.eu/search/simple/result/",
"https://www.faa.gov/aircraft",
"https://tc.canada.ca/fr/services-generaux/lois-reglements/liste-reglements/reglement-aviation-canadien-dors-96-433",
"https://www.robinsonheli.com/",
]

# Extensions to ignore when following links (non-HTML / binary)
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".mp3", ".mp4", ".avi",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}


def _extract_domain(url: str) -> str:
    """Return registered domain (e.g. 'tc.canada.ca') for same-domain filtering."""
    if tldextract:
        ext = tldextract.extract(url)
        return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain
    return urlparse(url).netloc or "unknown"


def _domain_folder(domain: str) -> Path:
    """Safe subfolder name from domain (e.g. tc.canada.ca -> tc_canada_ca)."""
    safe = re.sub(r"[^\w.-]", "_", domain.lower()).strip("_") or "unknown"
    return REGULATIONS_DIR / safe


def _clean_filename(url: str, title: str | None) -> str:
    """Produce a filesystem-safe HTML filename from URL and optional title."""
    stem = None
    if title and title.strip():
        stem = re.sub(r"[^\w\s.-]", "", title)[:120].strip()
        stem = re.sub(r"\s+", "_", stem) or None
    if not stem:
        parsed = urlparse(url)
        stem = (parsed.path or parsed.netloc or "page").strip("/")
        stem = re.sub(r"[^\w./-]", "_", stem)[:120].strip("/") or "page"
    return (stem[:100] + ".html") if stem.endswith(".html") else (stem[:100] + ".html")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "AircraftRegulationsCrawler/1.0 (aviation regulations research)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-CA,en;q=0.9",
    })
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s


def _same_domain(url: str, start_domain: str) -> bool:
    return _extract_domain(url) == start_domain


def _should_skip_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    if path.endswith("/"):
        path = path.rstrip("/")
    if "#" in url:
        url = url.split("#")[0]
    for ext in SKIP_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def crawl(start_url: str, max_pages: int = 500) -> None:
    """
    Crawl from start_url, follow same-domain links, save HTML to assets/regulations/{domain}/.
    """
    REGULATIONS_DIR.mkdir(parents=True, exist_ok=True)
    start_domain = _extract_domain(start_url)
    folder = _domain_folder(start_domain)
    folder.mkdir(parents=True, exist_ok=True)

    visited: set[str] = set()
    to_visit: list[str] = [start_url]
    session = _session()
    count = 0

    while to_visit and count < max_pages:
        url = to_visit.pop(0)
        # Normalize: no fragment, strip trailing slash for dedup
        base = url.split("#")[0].rstrip("/") or url
        if base in visited:
            continue
        visited.add(base)

        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            raw = resp.content
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in content_type and not raw.strip().startswith(b"<!") and not raw.strip().startswith(b"<html"):
                continue
        except requests.RequestException as e:
            print(f"  Error fetching {url}: {e}")
            continue

        try:
            soup = BeautifulSoup(raw, "html.parser")
        except Exception as e:
            print(f"  Error parsing {url}: {e}")
            continue

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None
        filename = _clean_filename(url, title)
        # Avoid overwriting: add short hash if file exists
        out_path = folder / filename
        if out_path.exists():
            extra = str(abs(hash(url)) % 10000)
            out_path = folder / filename.replace(".html", f"_{extra}.html")
        out_path.write_bytes(raw)
        count += 1
        print(f"Scraped {count}/{max_pages}: {url}")

        if count >= max_pages:
            break

        for a in soup.find_all("a", href=True):
            href = (a["href"] or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(url, href)
            full_base = full.split("#")[0].rstrip("/") or full
            if full_base in visited:
                continue
            if _should_skip_url(full):
                continue
            if _same_domain(full, start_domain):
                to_visit.append(full)

        time.sleep(0.5)

    print(f"Done. Saved {count} pages under {folder}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl aviation regulation sites into assets/regulations/")
    parser.add_argument("--url", type=str, help="Single URL to crawl (overrides TARGET_URLS)")
    parser.add_argument("--max-pages", type=int, default=500, help="Max pages per site (default 500)")
    parser.add_argument("--all", action="store_true", help="Crawl all TARGET_URLS in sequence")
    args = parser.parse_args()

    if not TARGET_URLS and not args.url:
        print("Add TARGET_URLS in src/crawl.py or pass --url <starting_url>")
        return

    if args.url:
        urls = [args.url]
    elif args.all:
        urls = TARGET_URLS
    else:
        urls = [TARGET_URLS[0]]

    for u in urls:
        u = u.strip()
        if u:
            print(f"\nCrawling from {u} (max_pages={args.max_pages})")
            crawl(u, max_pages=args.max_pages)


if __name__ == "__main__":
    main()
