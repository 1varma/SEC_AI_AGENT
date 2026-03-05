import os
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
BUCKET        = "sec-filings-raw-data-ashish-v1"
S3_PREFIX     = "raw_8k/"
LOCAL_OUT     = os.path.expanduser("~/Desktop/SEC_AI_AGENT/data/raw_html")
MAX_WORKERS   = 16    # parallel S3 downloads (I/O bound)

# Priority order when selecting which file to download per filing folder
PRIMARY_NAMES = {"primary-document.html", "primary-document.htm", "primary-document.txt"}
SKIP_NAMES    = {"full-submission.txt"}
KEEP_EXTS     = {".html", ".htm", ".txt"}


# ─── Select the best document from a filing folder ────────────────────────────
def pick_best_file(files):
    """
    Priority:
      1. primary-document.html or .htm
      2. primary-document.txt
      3. first .html / .htm file (not full-submission.txt)
      4. first .txt file (not full-submission.txt)
    Returns the chosen filename or None.
    """
    named   = {f.lower(): f for f in files}
    skip    = {f.lower() for f in files if f.lower() in SKIP_NAMES}

    # 1. primary-document.html / .htm
    for name in ("primary-document.html", "primary-document.htm"):
        if name in named:
            return named[name]

    # 2. primary-document.txt
    if "primary-document.txt" in named:
        return named["primary-document.txt"]

    # 3. any .html / .htm (not skipped)
    for f in files:
        if f.lower() not in skip and f.lower().endswith((".html", ".htm")):
            return f

    # 4. any .txt (not skipped)
    for f in files:
        if f.lower() not in skip and f.lower().endswith(".txt"):
            return f

    return None


# ─── Download one filing to local disk ────────────────────────────────────────
def download_filing(s3_client, ticker, accession, s3_key, local_path):
    """Download a single S3 object. Returns (local_path, status)."""
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path, "skipped"

    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        s3_client.download_file(BUCKET, s3_key, local_path)
        return local_path, "downloaded"
    except Exception as e:
        return local_path, f"error: {e}"


def main():
    print('=' * 60)
    print('SEC AI — Download 8-K Filings from S3')
    print('=' * 60)

    s3 = boto3.client("s3")

    # ─── 1. List all objects and group by filing folder ───────────────────────
    print(f"\nListing s3://{BUCKET}/{S3_PREFIX} (this may take a minute)...")
    folders = {}   # { (ticker, accession): [filenames] }

    paginator = s3.get_paginator("list_objects_v2")
    total_objects = 0

    for page in paginator.paginate(Bucket=BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            key   = obj["Key"]
            parts = key.split("/")
            # expected: raw_8k / TICKER / ACCESSION / filename
            if len(parts) < 4:
                continue
            ticker    = parts[1].upper()
            accession = parts[2]
            filename  = parts[3]
            ext       = os.path.splitext(filename)[1].lower()
            if ext not in KEEP_EXTS:
                continue
            folders.setdefault((ticker, accession), []).append(filename)
            total_objects += 1

    print(f"Total relevant objects: {total_objects:,}")
    print(f"Unique 8-K filings:     {len(folders):,}\n")

    # ─── 2. Build download tasks ──────────────────────────────────────────────
    tasks = []
    skipped_no_doc = 0

    for (ticker, accession), files in folders.items():
        chosen = pick_best_file(files)
        if not chosen:
            skipped_no_doc += 1
            continue

        s3_key     = f"{S3_PREFIX}{ticker.upper()}/{accession}/{chosen}"
        local_dir  = os.path.join(LOCAL_OUT, ticker)
        # filename: TICKER_8-K_ACCESSION.ext  (parse_filename will read ticker + type)
        ext        = os.path.splitext(chosen)[1]
        local_name = f"{ticker}_8-K_{accession}{ext}"
        local_path = os.path.join(local_dir, local_name)
        tasks.append((ticker, accession, s3_key, local_path))

    print(f"Download tasks:         {len(tasks):,}")
    if skipped_no_doc:
        print(f"Skipped (no usable doc): {skipped_no_doc:,}")
    print()

    # ─── 3. Parallel download ─────────────────────────────────────────────────
    results = {"downloaded": 0, "skipped": 0, "error": 0}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_filing, s3, ticker, accession, s3_key, local_path): local_path
            for ticker, accession, s3_key, local_path in tasks
        }

        for future in tqdm(as_completed(futures), total=len(tasks), desc="Downloading"):
            _, status = future.result()
            if status == "downloaded":
                results["downloaded"] += 1
            elif status == "skipped":
                results["skipped"] += 1
            else:
                results["error"] += 1

    # ─── 4. Summary ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Downloaded:  {results['downloaded']:,}")
    print(f"Skipped:     {results['skipped']:,}  (already on disk)")
    print(f"Errors:      {results['error']:,}")
    print(f"\nFiles saved to: {LOCAL_OUT}/TICKER/TICKER_8-K_ACCESSION.html")
    print("\nNext steps:")
    print("  python convert_to_md.py    (resumable — skips already converted)")
    print("  python chunk.py            (incremental mode — no TRUNCATE)")
    print("  python embed.py            (resumable — WHERE embedding IS NULL)")
    print('=' * 60)


if __name__ == '__main__':
    main()
