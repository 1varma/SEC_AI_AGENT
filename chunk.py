import os
import re
import gc
import glob
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from multiprocessing import Pool
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
MD_FILES_PATH  = os.path.expanduser("~/Desktop/SEC_AI_AGENT/data/md_files")
DB_CONFIG      = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}
MAX_TOKENS     = 1024   # words per chunk
OVERLAP_TOKENS = 200    # word overlap between consecutive chunks
INSERT_BATCH   = 500    # rows per PostgreSQL INSERT batch
CPU_WORKERS    = 24     # parallel processes for chunking
FILE_BATCH     = 2000   # files per pool instance (keeps memory flat)
INCREMENTAL    = True   # True = skip TRUNCATE, only insert new files (for 8-K top-ups)


# ─── Parse metadata from filename ─────────────────────────────────────────────
def parse_filename(filepath):
    """Extract ticker, filing_type, date from filename like AAPL_10-K_2024-01-15.md"""
    filename = os.path.basename(filepath).replace(".md", "")
    parts    = filename.split("_")

    if len(parts) >= 3:
        ticker      = parts[0]
        filing_type = parts[1]
        date_str    = parts[2]
        try:
            filing_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            filing_date = None
    elif len(parts) == 2:
        ticker      = parts[0]
        filing_type = parts[1]
        filing_date = None
    else:
        ticker      = filename
        filing_type = "unknown"
        filing_date = None

    return ticker, filing_type, filing_date


# ─── Split text by markdown headers ───────────────────────────────────────────
def split_by_sections(text):
    """Split on # / ## / ### headers. Returns list of (section_name, text)."""
    pattern = r'(^#{1,3}\s+.+$)'
    parts   = re.split(pattern, text, flags=re.MULTILINE)

    sections        = []
    current_section = "Introduction"
    current_text    = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(r'^#{1,3}\s+', part):
            if current_text.strip():
                sections.append((current_section, current_text.strip()))
            current_section = re.sub(r'^#{1,3}\s+', '', part).strip()
            current_text    = ""
        else:
            current_text += part + "\n"

    if current_text.strip():
        sections.append((current_section, current_text.strip()))

    if not sections:
        sections = [("Full Document", text.strip())]

    return sections


# ─── Sliding word-window chunker ───────────────────────────────────────────────
def chunk_text(text):
    """Split text into overlapping word-based windows."""
    words = text.split()
    if not words:
        return []

    chunks = []
    start  = 0
    while start < len(words):
        end = min(start + MAX_TOKENS, len(words))
        chunks.append(' '.join(words[start:end]))
        if end >= len(words):
            break
        start += MAX_TOKENS - OVERLAP_TOKENS

    return chunks


# ─── Process a single file (runs in parallel) ─────────────────────────────────
def process_file(filepath):
    """Read, section-split, chunk one .md file. Returns list of chunk dicts."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        if not text.strip():
            return []

        ticker, filing_type, filing_date = parse_filename(filepath)
        sections = split_by_sections(text)

        chunks = []
        for section_name, section_text in sections:
            for idx, chunk in enumerate(chunk_text(section_text)):
                if len(chunk.strip()) < 50:
                    continue
                chunks.append({
                    "ticker":      ticker,
                    "filing_type": filing_type,
                    "filing_date": filing_date,
                    "section":     section_name[:500],
                    "chunk_index": idx,
                    "chunk_text":  chunk,
                    "source_file": os.path.basename(filepath)
                })
        return chunks

    except Exception as e:
        print(f"ERROR processing {filepath}: {e}")
        return []


def main():
    print('=' * 60)
    print('SEC Filing Chunker')
    print('=' * 60)

    # ─── 1. Scan markdown files ───────────────────────────────────────────────
    print(f"\nScanning {MD_FILES_PATH} ...")
    all_files = glob.glob(os.path.join(MD_FILES_PATH, "**", "*.md"), recursive=True)
    print(f"Found {len(all_files):,} files\n")

    # ─── 2. Connect to DB ─────────────────────────────────────────────────────
    print("Connecting to PostgreSQL...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    if INCREMENTAL:
        # Fetch already-chunked source files so we skip them
        cur.execute("SELECT DISTINCT source_file FROM filing_chunks;")
        already_done = {row[0] for row in cur.fetchall()}
        all_files = [f for f in all_files if os.path.basename(f) not in already_done]
        print(f"Incremental mode: {len(all_files):,} new files to chunk "
              f"({len(already_done):,} already in DB)\n")
    else:
        cur.execute("TRUNCATE TABLE filing_chunks RESTART IDENTITY;")
        conn.commit()
        print("Table truncated.\n")

    insert_sql = """
        INSERT INTO filing_chunks
            (ticker, filing_type, filing_date, section, chunk_index, chunk_text, source_file)
        VALUES %s
        ON CONFLICT DO NOTHING
    """

    # ─── 3. Chunk + insert per file batch (memory stays flat) ─────────────────
    # Each batch of FILE_BATCH files is chunked, immediately inserted into DB,
    # then freed. At no point is more than one batch of chunks held in RAM.
    print(f"Chunking with {CPU_WORKERS} workers and inserting per batch ({FILE_BATCH} files)...")
    total_chunks = 0
    total_batches = (len(all_files) - 1) // FILE_BATCH + 1

    for batch_start in range(0, len(all_files), FILE_BATCH):
        batch     = all_files[batch_start:batch_start + FILE_BATCH]
        batch_num = batch_start // FILE_BATCH + 1

        # Chunk this batch in parallel
        batch_chunks = []
        with Pool(processes=CPU_WORKERS, maxtasksperchild=20) as pool:
            for file_chunks in tqdm(
                pool.imap_unordered(process_file, batch, chunksize=5),
                total=len(batch),
                desc=f"Chunking batch {batch_num}/{total_batches}"
            ):
                batch_chunks.extend(file_chunks)

        # Insert this batch immediately
        rows = [
            (
                c["ticker"], c["filing_type"], c["filing_date"],
                c["section"], c["chunk_index"], c["chunk_text"],
                c["source_file"]
            )
            for c in batch_chunks
        ]
        for i in range(0, len(rows), INSERT_BATCH):
            execute_values(cur, insert_sql, rows[i:i + INSERT_BATCH])
        conn.commit()

        total_chunks += len(rows)
        print(f"  Batch {batch_num}/{total_batches}: {len(rows):,} chunks inserted "
              f"(running total: {total_chunks:,})\n")

        # Free this batch from RAM before moving to the next
        del batch_chunks, rows
        gc.collect()

    cur.close()
    conn.close()

    # ─── 4. Verify ────────────────────────────────────────────────────────────
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM filing_chunks;")
    total = cur.fetchone()[0]
    print(f"\nTotal rows inserted: {total:,}")

    cur.execute("""
        SELECT ticker, filing_type, COUNT(*) AS chunks
        FROM filing_chunks
        GROUP BY ticker, filing_type
        ORDER BY chunks DESC
        LIMIT 10;
    """)
    print("\nTop 10 tickers by chunk count:")
    for row in cur.fetchall():
        print(f"  {row[0]:6s}  {row[1]:6s}  {row[2]:,} chunks")

    cur.close()
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"Chunking complete. {total_chunks:,} rows inserted. All embeddings are NULL.")
    print("Next step: python embed.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
