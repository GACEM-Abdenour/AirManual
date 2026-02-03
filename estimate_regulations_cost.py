"""
Estimate Unstructured API cost for HTML files in assets/regulations.

Parsing only (Unstructured): bills HTML as pages = file_size / 100 KB (integer part).
Indexing (embeddings + Qdrant) is separate — OpenAI charges per token; use the
OpenAI usage dashboard for total embedding/LLM cost. This script answers:
"How much did parsing the scraped regulations HTMLs cost?"
"""
from pathlib import Path

# 100 KB in bytes (Unstructured's "page" unit for HTML)
BYTES_PER_PAGE = 100 * 1024

REGULATIONS_DIR = Path(__file__).resolve().parent / "assets" / "regulations"


def main():
    if not REGULATIONS_DIR.exists():
        print(f"Directory not found: {REGULATIONS_DIR}")
        return

    total_pages = 0
    total_bytes = 0
    file_count = 0

    for path in REGULATIONS_DIR.rglob("*.html"):
        size = path.stat().st_size
        pages = size // BYTES_PER_PAGE  # natural (integer) part
        total_pages += pages
        total_bytes += size
        file_count += 1

    print("=" * 60)
    print("Regulations HTML – Unstructured page estimate")
    print("=" * 60)
    print(f"Directory:     {REGULATIONS_DIR}")
    print(f"HTML files:    {file_count:,}")
    print(f"Total size:    {total_bytes:,} bytes  ({total_bytes / (1024*1024):.2f} MB)")
    print(f"Total pages:   {total_pages:,}  (size ÷ 100 KB, integer part)")
    print()
    # Free tier: 15,000 pages; then $0.03/page
    free_tier = 15_000
    paid_pages = max(0, total_pages - free_tier)
    cost = paid_pages * 0.03
    print(f"Free tier:     {free_tier:,} pages")
    print(f"Paid pages:    {paid_pages:,}")
    print(f"Est. cost:     ${cost:,.2f}  (at $0.03/page after free tier)")
    print("=" * 60)


if __name__ == "__main__":
    main()
