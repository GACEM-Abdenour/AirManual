"""Document ingestion script using Unstructured API. PDFs and HTML use hi_res."""
import sys
import time
from pathlib import Path

# Ensure project root is on path when run as script (e.g. python src/ingest.py)
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import argparse
import json
import os
from typing import List, Dict, Any, Optional
from unstructured_client import UnstructuredClient
from unstructured_client.models import operations, shared
from llama_index.core import Document
from src.config import Config

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# Simple ingest state: avoid re-parsing and re-indexing already processed files
STATE_PATH = _root / "data" / "ingest_state.json"
PARSED_DIR = _root / "data" / "parsed"


def _rel_path(path: Path) -> str:
    """Path relative to project root, normalizable for state keys."""
    try:
        return str(path.resolve().relative_to(_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _cache_key(rel: str) -> str:
    """Safe filename for parsed cache (no path separators)."""
    return rel.replace("/", "_").replace("\\", "_") + ".json"


def _load_state() -> Dict[str, Dict[str, bool]]:
    if not STATE_PATH.exists():
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(state: Dict[str, Dict[str, bool]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _load_cached_docs(rel: str) -> Optional[List[Document]]:
    path = PARSED_DIR / _cache_key(rel)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [Document(text=o["text"], metadata=o["metadata"]) for o in raw]


def _save_cached_docs(rel: str, documents: List[Document]) -> None:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PARSED_DIR / _cache_key(rel)
    raw = [{"text": d.text, "metadata": d.metadata} for d in documents]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=0)


def format_table_as_markdown(element: Dict[str, Any]) -> str:
    """Convert a table element to clean Markdown format for indexing.
    
    This is critical for aircraft part number retrieval - tables must be
    searchable as text so part numbers can be found via keyword matching.
    
    Args:
        element: Dictionary containing table element from Unstructured API
        
    Returns:
        Clean Markdown-formatted table string
    """
    # Priority 1: Use text_as_markdown if available (best format)
    if "text_as_markdown" in element and element["text_as_markdown"]:
        markdown_text = element["text_as_markdown"].strip()
        if markdown_text:
            return f"\n{markdown_text}\n"
    
    # Priority 2: Use text field if it contains pipe characters (likely markdown)
    text = element.get("text", "")
    if text and "|" in text:
        # Clean up the text - ensure it's proper markdown table format
        cleaned_text = text.strip()
        return f"\n{cleaned_text}\n"
    
    # Priority 3: Use text field directly (Unstructured often provides formatted text)
    if text and text.strip():
        cleaned_text = text.strip()
        return f"\n{cleaned_text}\n"
    
    # Priority 4: Try to extract from text_as_html (fallback)
    if "text_as_html" in element:
        html_table = element["text_as_html"]
        # For now, use the text field if available, otherwise note HTML presence
        if text:
            return f"\n{text.strip()}\n"
        # Last resort: indicate table presence
        return f"\n[Table content - HTML format available]\n"
    
    # Final fallback: return string representation
    return f"\n[Table content]\n"


def process_unstructured_elements(
    elements: List[Dict[str, Any]],
    file_name: str,
    document_title: Optional[str] = None,
) -> List[Document]:
    """Process Unstructured API elements into LlamaIndex Documents.

    Args:
        elements: List of element dictionaries from Unstructured API
        file_name: Name of the source file
        document_title: Optional title (e.g. from HTML <title>) to add to metadata

    Returns:
        List of LlamaIndex Document objects with metadata
    """
    documents = []

    for element in elements:
        # Handle both dict and object responses
        if hasattr(element, "type"):
            element_type = element.type.lower() if element.type else ""
            text = element.text if hasattr(element, "text") else ""
            metadata = element.metadata if hasattr(element, "metadata") else {}
            # Convert to dict for easier handling
            element_dict = {
                "type": element_type,
                "text": text,
                "metadata": metadata.__dict__ if hasattr(metadata, "__dict__") else metadata,
            }
            # Add any additional attributes
            if hasattr(element, "text_as_html"):
                element_dict["text_as_html"] = element.text_as_html
            if hasattr(element, "text_as_markdown"):
                element_dict["text_as_markdown"] = element.text_as_markdown
        else:
            element_dict = element
            element_type = element_dict.get("type", "").lower()
            text = element_dict.get("text", "")
            metadata = element_dict.get("metadata", {})
        
        page_number = metadata.get("page_number", 0) if isinstance(metadata, dict) else getattr(metadata, "page_number", 0)
        
        # Process tables: convert to Markdown
        if element_type == "table":
            text = format_table_as_markdown(element_dict)
        
        # Skip empty elements
        if not text or not text.strip():
            continue
        
        # Create Document with metadata
        meta: Dict[str, Any] = {
            "file_name": file_name,
            "page_number": page_number,
            "element_type": element_type,
        }
        if document_title:
            meta["document_title"] = document_title
        doc = Document(text=text, metadata=meta)
        documents.append(doc)

    return documents


def _html_title(file_path: str) -> Optional[str]:
    """Extract <title> from an HTML file for use as document_title."""
    if not BeautifulSoup:
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else None
    except Exception:
        return None


def _parse_html_local(file_path: str, file_name: str) -> List[Document]:
    """Parse HTML locally with BeautifulSoup. Fast, no API calls, no hang."""
    if not BeautifulSoup:
        raise RuntimeError("BeautifulSoup is required for HTML; install beautifulsoup4")
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    title_tag = soup.find("title")
    document_title = title_tag.get_text(strip=True) if title_tag else None
    # Remove scripts/styles so we only index main content
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.find("body") or soup
    text = body.get_text(separator="\n", strip=True) if body else ""
    if not text:
        text = soup.get_text(separator="\n", strip=True)
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not text:
        return []
    meta: Dict[str, Any] = {
        "file_name": file_name,
        "page_number": 0,
        "element_type": "html",
    }
    if document_title:
        meta["document_title"] = document_title
    return [Document(text=text, metadata=meta)]


def ingest_file(file_path: str) -> List[Document]:
    """Ingest a file (PDF or HTML).
    
    Both PDF and HTML use Unstructured API with strategy=hi_res for richer structure
    and table detection. For HTML, <title> is extracted and stored as document_title.
    
    Args:
        file_path: Path to the PDF or HTML file
        
    Returns:
        List of processed Document objects
    """
    ext = os.path.splitext(file_path)[1].lower()
    file_name = os.path.basename(file_path)

    if ext not in (".pdf", ".html"):
        raise ValueError(f"Unsupported extension: {ext}")

    client = UnstructuredClient(
        api_key_auth=Config.UNSTRUCTURED_API_KEY,
        server_url=Config.UNSTRUCTURED_API_URL,
    )
    with open(file_path, "rb") as f:
        file_content = f.read()
    files = shared.Files(content=file_content, file_name=file_name)
    
    if ext == ".pdf":
        partition_params = shared.PartitionParameters(
            files=files,
            strategy=shared.Strategy.HI_RES,
            hi_res_model_name="yolox",
        )
        strategy_name = "hi_res"
    else:  # HTML
        partition_params = shared.PartitionParameters(
            files=files,
            strategy=shared.Strategy.FAST,
        )
        strategy_name = "fast"
    
    UNSTRUCTURED_TIMEOUT_MS = 300_000  # 5 minutes per request
    print(f"Processing {file_name} with {strategy_name} strategy...")
    request = operations.PartitionRequest(partition_parameters=partition_params)

    last_err = None
    for attempt in range(3):
        try:
            response = client.general.partition(
                request=request, timeout_ms=UNSTRUCTURED_TIMEOUT_MS
            )
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                backoff = 30 * (attempt + 1)
                print(f"  Retry in {backoff}s after: {e}")
                time.sleep(backoff)
            else:
                raise last_err

    if hasattr(response, "elements"):
        elements = response.elements
    elif isinstance(response, list):
        elements = response
    else:
        raise ValueError(f"Failed to process {file_name}: Unexpected response format")
    if not elements:
        raise ValueError(f"Failed to process {file_name}: No elements returned")

    document_title = _html_title(file_path) if ext == ".html" else None
    documents = process_unstructured_elements(
        elements, file_name, document_title=document_title
    )
    print(f"Processed {len(documents)} documents from {file_name}")
    return documents


def main():
    """Main ingestion function."""
    parser = argparse.ArgumentParser(description="Ingest PDFs and HTML from assets/ and index in Qdrant.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing Qdrant collection and rebuild from scratch (use after schema errors or to avoid duplicates).",
    )
    args = parser.parse_args()

    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        print(f"Configuration error: {e}")
        return

    # Recursively find PDF and HTML files under assets/
    data_dir = _root / "assets"
    if not data_dir.exists():
        print(f"Error: {data_dir} directory does not exist.")
        print("Please create an 'assets' folder and add PDF or HTML files to process.")
        return

    pdf_files = sorted(data_dir.rglob("*.pdf"))
    html_files = sorted(data_dir.rglob("*.html"))
    all_files = sorted(set(pdf_files) | set(html_files))
    if not all_files:
        print(f"No PDF or HTML files found under {data_dir}")
        return

    state = _load_state()
    if args.reset:
        for v in state.values():
            v["indexed"] = False
        _save_state(state)
        print("Reset: cleared 'indexed' for all files (Qdrant collection will be wiped on index).")

    # Process all files. Not in state = new file → init parsed/indexed false.
    all_docs_to_index: List[Document] = []
    indexed_rels: List[str] = []
    print("\nProcessing PDFs and HTML (cache used when parsed=true):")

    for file_path in all_files:
        file_path = Path(file_path)
        rel = _rel_path(file_path)
        if rel not in state:
            state[rel] = {"parsed": False, "indexed": False}

        try:
            cached = _load_cached_docs(rel)
            if state[rel]["parsed"] and cached is not None:
                documents = cached
                print(f"  {file_path.name}: cached ({len(documents)} nodes)")
            else:
                documents = ingest_file(str(file_path))
                _save_cached_docs(rel, documents)
                state[rel]["parsed"] = True
                _save_state(state)
                print(f"  {file_path.name}: parsed ({len(documents)} nodes)")
        except Exception as e:
            print(f"  {file_path.name}: FAILED — {e}")
            import traceback
            traceback.print_exc()
            continue

        if state[rel]["indexed"] and not args.reset:
            continue
        all_docs_to_index.extend(documents)
        indexed_rels.append(rel)

    total = len(all_docs_to_index)
    print(f"\nTotal nodes to index: {total}")

    if total == 0:
        print("Already indexed (skip). Use --reset to rebuild.")
        return

    # First 5 nodes preview
    print("\n" + "="*80)
    print("First 5 Processed Nodes:")
    print("="*80)
    for i, doc in enumerate(all_docs_to_index[:5], 1):
        print(f"\n--- Node {i} ---")
        print(f"File: {doc.metadata.get('file_name', 'N/A')}")
        print(f"Page: {doc.metadata.get('page_number', 'N/A')}")
        print(f"Type: {doc.metadata.get('element_type', 'N/A')}")
        print(f"Text Preview (first 200 chars):")
        print("-" * 80)
        preview = doc.text[:200] + "..." if len(doc.text) > 200 else doc.text
        print(preview)
        print("-" * 80)

    print("\n" + "="*80)
    print("Indexing documents in Qdrant...")
    print("="*80)
    try:
        from src.index_store import create_index
        create_index(documents=all_docs_to_index, reset=args.reset)
        for r in indexed_rels:
            state[r]["indexed"] = True
        _save_state(state)
        print(f"\nSuccessfully indexed {total} documents!")
    except Exception as e:
        print(f"Indexing failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
