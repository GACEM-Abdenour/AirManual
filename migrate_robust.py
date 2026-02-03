"""
Resumable Qdrant migration: Local (disk) -> Qdrant Cloud.
Saves checkpoint after each batch. On crash/restart, resumes from last checkpoint.
"""
import json
import sys
import time
import uuid
import warnings
from pathlib import Path

# Unbuffered output
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, "reconfigure") else None

# Add project root to path for config
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

# No longer using _recreate_collection; we create collection with quantization below

# Config
COLLECTION_NAME = "aircraft_maintenance_docs"
LOCAL_QDRANT_PATH = "./qdrant_db"
CHECKPOINT_PATH = _root / "migration_checkpoint.json"
BATCH_SIZE = 100  # Balance speed vs reliability over consumer internet; retries per batch
RETRY_PAUSE = 15
MAX_RETRIES = 10  # Per batch


def load_env() -> tuple[str, str | None]:
    """Load Qdrant destination. Supports Docker (no API key) or Cloud."""
    import os
    url = os.getenv("QDRANT_URL", "").strip()
    key = os.getenv("QDRANT_API_KEY", "").strip() or None
    # Fallback to hardcoded Cloud values
    if not url:
        url = "https://a1090179-06b0-4722-b521-2f9d92407c4d.europe-west3-0.gcp.cloud.qdrant.io:6333"
        key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIn0.Utttua3acDkvQSYwUxrz5FITwsrVHBIJakR56x95kyY"
    return url, key


def serialize_offset(offset) -> str | int | None:
    """Serialize PointId for JSON (UUID -> str, int -> int)"""
    if offset is None:
        return None
    if isinstance(offset, uuid.UUID):
        return str(offset)
    if isinstance(offset, int):
        return offset
    return str(offset)


def deserialize_offset(val) -> object | None:
    """Deserialize PointId from JSON"""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return uuid.UUID(val)
        except ValueError:
            return val
    return val


def load_checkpoint() -> dict | None:
    if not CHECKPOINT_PATH.exists():
        return None
    with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(next_offset, points_uploaded: int):
    data = {
        "next_offset": serialize_offset(next_offset),
        "points_uploaded": points_uploaded,
        "collection_name": COLLECTION_NAME,
    }
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    sys.stdout.flush()


def _dense_vector_for_point(record) -> object:
    """Extract dense vector for single-vector cloud collection (local may be hybrid)."""
    v = record.vector
    if not isinstance(v, dict):
        return v
    return v.get("default") or next((x for x in v.values() if isinstance(x, list)), v)


def is_retryable_error(e: Exception) -> bool:
    """True if we should retry (network/timeout/transient)"""
    # Check cause for wrapped exceptions (e.g. SSL read hang)
    to_check = [e]
    if getattr(e, "__cause__", None):
        to_check.append(e.__cause__)
    for exc in to_check:
        err_str = str(exc).lower()
        err_type = type(exc).__name__
        retry_keywords = [
            "timeout", "timed out", "ssl", "connection", "reset", "refused",
            "unreachable", "network", "read", "write", "broken pipe", "hang"
        ]
        if any(kw in err_str for kw in retry_keywords):
            return True
        if err_type in ("ReadTimeout", "ConnectTimeout", "WriteTimeout", "TimeoutException"):
            return True
        if isinstance(exc, (ConnectionError, OSError)):
            return True
    if isinstance(e, UnexpectedResponse) and getattr(e, "status_code", 0) >= 500:
        return True
    return False


def main():
    print("=" * 60)
    print("Resumable Qdrant Migration (Local -> Cloud)")
    print("=" * 60)

    try:
        cloud_url, cloud_api_key = load_env()
    except ValueError as e:
        print(f"ERROR: {e}")
        return

    print(f"\nSource: {LOCAL_QDRANT_PATH}")
    print(f"Dest:   {cloud_url}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Batch size: {BATCH_SIZE}")
    print("\nREQUIREMENTS: Stop Streamlit and any app using qdrant_db!\n")

    checkpoint = load_checkpoint()
    if checkpoint:
        print(f"[RESUME] Found checkpoint: {checkpoint.get('points_uploaded', 0):,} points already uploaded")
        print(f"         Resuming from saved offset...\n")
    else:
        print("[START] No checkpoint - starting from beginning\n")

    # Retryable exceptions (network/timeout/transient)
    try:
        import httpx
        RETRY_EXCEPTIONS = (
            httpx.TimeoutException,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.WriteTimeout,
            ConnectionError,
            OSError,
            UnexpectedResponse,
        )
    except ImportError:
        RETRY_EXCEPTIONS = (ConnectionError, OSError, UnexpectedResponse)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*not recommended for collections.*")

        print("[Step 1] Connecting to local Qdrant (5-15 min for 372k points)...")
        sys.stdout.flush()
        try:
            local_client = QdrantClient(path=str(_root / LOCAL_QDRANT_PATH))
        except RuntimeError as e:
            if "another instance" in str(e).lower():
                print(f"\nERROR: {e}")
                print("Stop Streamlit and any other app using qdrant_db.")
            raise
        print("        Done.")

        print("[Step 2] Connecting to Qdrant Cloud...")
        cloud_client = QdrantClient(url=cloud_url, api_key=cloud_api_key)
        print("        Done.")

        total_points = local_client.get_collection(COLLECTION_NAME).points_count
        print(f"\nLocal collection: {total_points:,} points\n")

        # Create collection on cloud if no checkpoint (first run)
        if not checkpoint:
            print("[Step 3] Creating collection on Cloud (dense vector + Scalar INT8 quantization)...")
            cloud_client.recreate_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=1536,  # OpenAI text-embedding-3-small
                    distance=models.Distance.COSINE,
                ),
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True,
                    )
                ),
            )
            print("        Done.\n")
            start_offset = None
            points_uploaded = 0
        else:
            start_offset = deserialize_offset(checkpoint.get("next_offset"))
            points_uploaded = checkpoint.get("points_uploaded", 0)
            if start_offset is None:
                print("[DONE] Checkpoint says we're finished. Verifying...")
                cloud_count = cloud_client.get_collection(COLLECTION_NAME).points_count
                if cloud_count == total_points:
                    print(f"\nMigration already complete: {cloud_count:,} points in Cloud.")
                    print("Delete migration_checkpoint.json to re-run from scratch.")
                else:
                    print(f"WARNING: Cloud has {cloud_count:,}, local has {total_points:,}. Delete checkpoint to retry.")
                return

        # Main loop: scroll, upsert, checkpoint
        print("[Step 4] Migrating (scroll -> upsert -> checkpoint)...")
        print("         On crash: just run this script again to resume.\n")

        offset = start_offset
        batch_num = points_uploaded // BATCH_SIZE

        while True:
            # Scroll next batch
            records, next_offset = local_client.scroll(
                collection_name=COLLECTION_NAME,
                offset=offset,
                limit=BATCH_SIZE,
                with_vectors=True,
            )

            if not records:
                break

            # Convert Record (Read) -> PointStruct (Write); use dense vector only (cloud is single-vector)
            points_for_upsert = [
                models.PointStruct(
                    id=r.id,
                    vector=_dense_vector_for_point(r),
                    payload=r.payload,
                )
                for r in records
            ]

            # Upload with retries
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    cloud_client.upsert(
                        collection_name=COLLECTION_NAME,
                        points=points_for_upsert,
                        wait=True,
                    )
                    break
                except RETRY_EXCEPTIONS as e:
                    if attempt < MAX_RETRIES:
                        print(f"\n  [!] Batch failed (attempt {attempt}/{MAX_RETRIES}): {type(e).__name__}: {e}")
                        print(f"      Waiting {RETRY_PAUSE}s before retry...")
                        sys.stdout.flush()
                        time.sleep(RETRY_PAUSE)
                    else:
                        print(f"\n  [X] Batch failed after {MAX_RETRIES} attempts. Checkpoint saved.")
                        print(f"      Run the script again to resume.")
                        raise
                except Exception as e:
                    if is_retryable_error(e) and attempt < MAX_RETRIES:
                        print(f"\n  [!] Batch failed (attempt {attempt}/{MAX_RETRIES}): {e}")
                        print(f"      Waiting {RETRY_PAUSE}s before retry...")
                        sys.stdout.flush()
                        time.sleep(RETRY_PAUSE)
                    else:
                        raise

            points_uploaded += len(records)
            batch_num += 1
            last_id = records[-1].id if records else None

            # Checkpoint
            save_checkpoint(next_offset, points_uploaded)

            # Progress
            pct = 100 * points_uploaded / total_points if total_points else 0
            print(f"  Uploaded {points_uploaded:,} / {total_points:,} ({pct:.1f}%) | Last ID: {last_id}", end="\r")
            sys.stdout.flush()

            if next_offset is None:
                break
            offset = next_offset

        local_client.close()
        local_client = None

    # Done: close cloud client so __del__ doesn't raise on exit
    cloud_count = 0
    try:
        cloud_count = cloud_client.get_collection(COLLECTION_NAME).points_count
    finally:
        try:
            cloud_client.close()
        except Exception:
            pass
        cloud_client = None

    print("\n")
    print(f"Cloud collection: {cloud_count:,} points")

    if cloud_count == total_points:
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETE!")
        print("=" * 60)
        # Remove checkpoint so future runs know we're done
        if CHECKPOINT_PATH.exists():
            CHECKPOINT_PATH.unlink()
            print("Checkpoint file removed.")
        print("\nYour app (.env has QDRANT_URL) will use the cloud database.")
        print("Restart: streamlit run app.py")
    else:
        print(f"\nWARNING: Local {total_points:,} vs Cloud {cloud_count:,}. Re-run to resume.")


if __name__ == "__main__":
    main()
