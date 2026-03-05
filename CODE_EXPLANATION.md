# SEC AI Agent — Code Explanation

---

## 1. downloader.ipynb

### What it does
Downloads every 10-K (annual) and 10-Q (quarterly) SEC filing for all S&P 500 companies and uploads the raw HTML directly to an AWS S3 bucket.

---

### Step-by-step breakdown

#### Identity & Configuration
```python
set_identity("Ashish juttua@clarkson.edu")
BUCKET_NAME = "sec-filings-raw-data-ashish-v1"
MAX_REQ_PER_SEC = 10
MAX_WORKERS = 8
```
- `set_identity` is **required by SEC EDGAR** — they mandate a name/email in requests so they can contact you if you overload their servers.
- `MAX_REQ_PER_SEC = 10` respects SEC's rate limit of 10 requests/second.
- `MAX_WORKERS = 8` means 8 companies are processed in parallel.

---

#### RateLimiter class
```python
class RateLimiter:
    def wait_for_token(self):
        ...
```
A token-bucket rate limiter. It keeps a counter of available tokens (requests). Every second it refills to `rate_limit`. Each request consumes one token. If no tokens are available, it waits 50ms and tries again. This ensures we never exceed 10 req/sec across all 8 threads simultaneously.

---

#### create_s3_bucket()
Creates the S3 bucket if it doesn't already exist. Uses `head_bucket` to check existence first (avoids an error if the bucket is already there). Special handling for `us-east-1` — AWS doesn't accept a `LocationConstraint` for that region.

---

#### get_sp500_tickers()
Scrapes the S&P 500 ticker list from Wikipedia's table. Replaces `.` with `-` in tickers (e.g., `BRK.B` → `BRK-B`) because EDGAR uses hyphens, not dots.

---

#### check_file_exists_s3(key)
Before downloading anything, checks if the file already exists in S3 using `head_object`. This is a cheap metadata call — it avoids re-downloading files on repeated runs, saving both time and SEC bandwidth.

---

#### process_company(ticker)
The main worker function — one call per company:
1. Fetches all 10-K and 10-Q filings metadata for the ticker using `edgar` library.
2. For each filing, builds an S3 key like: `raw_html/AAPL/AAPL_10-K_2023-10-30.html`
3. Checks S3 — skips if already uploaded.
4. Downloads the HTML content via `filing.html()`.
5. Uploads directly to S3 as UTF-8 encoded bytes.

---

#### Main Execution
```python
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_to_ticker = {executor.submit(process_company, t): t for t in tickers}
```
Submits all 500 companies to a thread pool. `as_completed()` yields results as each thread finishes, printing live progress. Uses **threads** (not processes) because the work is I/O-bound (network calls), not CPU-bound.

**Result:** 38,183 HTML files uploaded to S3.

---
---

## 2. convert_to_md.py  (originally convert_to_md.ipynb)

### What it does
Converts every raw HTML SEC filing into clean plain text (`.md` files), stripping out HTML tags, JavaScript, styles, and XBRL/iXBRL metadata that would otherwise produce garbage output.

---

### Step-by-step breakdown

#### Configuration
```python
CPU_WORKERS    = 16
MIN_OUTPUT_CHARS = 200
MAX_FILE_SIZE_MB = 20
```
- Uses **16 CPU processes** (multiprocessing, not threads) because this is CPU-bound work (HTML parsing + regex).
- Files under 200 characters after conversion are considered empty/useless.
- Files over 20MB are skipped — they are likely malformed or contain embedded binary data.

---

#### strip_ixbrl_header(html)
```python
for tag in ('ix:header', 'ix:hidden'):
    # find and remove the tag block using string search
```
Modern SEC filings (2017+) embed **iXBRL** (inline XBRL) data inside hidden `<ix:header>` and `<ix:hidden>` blocks. These blocks contain thousands of XBRL dimension entries (financial taxonomy codes) that look like pure gibberish when extracted as text.

**Why not use regex?**
The original notebook used `re.sub(r'<ix:header\b[^>]*>[\s\S]*?</ix:header\s*>', ...)` which can cause **catastrophic backtracking** on large files (4MB+), freezing or crashing the process. The replacement uses `str.find()` to locate tag boundaries directly — much faster and safe.

---

#### extract_text(html_content)
1. Calls `strip_ixbrl_header` first.
2. Parses HTML with `selectolax.HTMLParser` — much faster than BeautifulSoup.
3. Removes all `<script>`, `<style>`, `<noscript>`, `<iframe>`, `<meta>`, `<link>` tags.
4. Extracts all text from `<body>` with newline separators.
5. Cleans up the output:
   - Strips blank/whitespace-only lines.
   - Removes lines that are just decorative characters (`---`, `===`, etc.).
   - Removes lines shorter than 3 characters.
   - Collapses 3+ consecutive blank lines into 2.

---

#### is_junk(text)
Detects two types of bad output that slip past `extract_text`:

1. **XBRL namespace leakage** — checks for patterns like `xbrli:`, `us-gaap:`, `fasb.org`, `xmlns:` in the first 1000 chars. If 2+ patterns are found, it's XBRL junk.

2. **Concatenated XBRL identifiers** — XBRL tags like `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` have very long "words". Checks the average length of the first 30 words — if > 20 characters, it's identifier soup.

3. **Low English word ratio** — counts words matching normal English characters. If less than 15% of words look like English, it's junk.

---

#### convert_file(filepath)
The main worker function — one call per HTML file:
1. **Size check** — skips files over 20MB.
2. **Resume check** — if the output `.md` file already exists and is clean, skip it. If it exists but is junk, delete and reprocess.
3. Reads HTML, extracts text, checks for junk, checks minimum length.
4. Writes the clean text to the mirrored path under `data/md_files/`.
   - e.g., `data/raw_html/AAPL/AAPL_10-K_2023.html` → `data/md_files/AAPL/AAPL_10-K_2023.md`

---

#### main() — Batch Processing
```python
for batch_start in range(0, len(all_files), BATCH):
    with Pool(processes=CPU_WORKERS, maxtasksperchild=20) as pool:
        ...
    gc.collect()
```
Processes all 38,183 files in **batches of 2,000**. After each batch:
- The Pool is fully shut down (releases all worker memory).
- `gc.collect()` forces Python's garbage collector to free memory.

This prevents memory from slowly accumulating across tens of thousands of files, which was the cause of crashes in the notebook version.

`maxtasksperchild=20` means each worker process is restarted after handling 20 files — keeps individual worker memory footprint small.

---

#### Why run as a script, not a notebook?
`multiprocessing.Pool` in Jupyter has a known issue: the notebook kernel shares state with child processes in ways that cause **deadlocks and kernel crashes**. Running as a plain Python script with `if __name__ == '__main__':` guard avoids this entirely.

Run with:
```bash
source agent/bin/activate
python convert_to_md.py
```
It is **fully resumable** — already-converted files are detected and skipped automatically.

---
---

## 3. create_table.py  (originally create_table.ipynb)

### What it does
Creates the PostgreSQL `filing_chunks` table with the [pgvector](https://github.com/pgvector/pgvector) extension enabled. Defines the full schema — including a 384-dimensional `vector` column that starts as `NULL` and is populated later by `embed.py` — and adds B-tree indexes for fast metadata filtering.

---

### Step-by-step breakdown

#### Table Schema
```sql
CREATE TABLE filing_chunks (
    id           SERIAL PRIMARY KEY,
    ticker       VARCHAR(10)  NOT NULL,
    filing_type  VARCHAR(10)  NOT NULL,
    filing_date  DATE,
    section      TEXT,
    chunk_index  INTEGER,
    chunk_text   TEXT         NOT NULL,
    embedding    vector(384),
    source_file  TEXT,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
```
- `ticker`, `filing_type`, `filing_date` — metadata parsed from the filename (e.g. `AAPL_10-K_2024-01-15.md`).
- `section` — the markdown header the chunk was extracted from (e.g. "Risk Factors").
- `chunk_index` — position of the chunk within its section (0-based).
- `chunk_text` — raw text content of the chunk.
- `embedding vector(384)` — pgvector column for the 384-dimensional float array. Starts as `NULL`; populated by `embed.py`. Enables cosine-distance similarity search via the `<=>` operator.
- `source_file` — original filename for traceability.

---

#### Indexes
```sql
CREATE INDEX idx_ticker      ON filing_chunks(ticker);
CREATE INDEX idx_filing_type ON filing_chunks(filing_type);
CREATE INDEX idx_filing_date ON filing_chunks(filing_date);
```
Three B-tree indexes for fast metadata filtering. The IVFFlat vector index (`idx_embedding`) is **not** created here — it is built by `embed.py` after all embeddings are populated, which is orders of magnitude faster than maintaining it during bulk updates.

Run with:
```bash
source agent/bin/activate
python create_table.py
```

---
---

## 4. chunk.py  (originally chunk.ipynb)

### What it does
Reads every clean `.md` file from `data/md_files/`, splits each document into section-aware overlapping text chunks, and bulk-inserts the text rows into PostgreSQL with `embedding = NULL`. No GPU work happens here — embedding is fully delegated to `embed.py`.

**Why separate?** Chunking is CPU-bound (multiprocessing, regex, string ops). Embedding is GPU-bound (single-process, CUDA). Keeping them in one script forces you to hold all chunk text **and** all embedding arrays in RAM simultaneously — potentially 5–8 GB for 1.9M chunks. Separating them means `chunk.py` uses only CPU RAM for text, and `embed.py` streams from the database one batch at a time.

---

### Step-by-step breakdown

#### Configuration
```python
MAX_TOKENS     = 1024   # words per chunk
OVERLAP_TOKENS = 200    # word overlap between consecutive chunks
INSERT_BATCH   = 500    # rows per PostgreSQL INSERT batch
CPU_WORKERS    = 24     # parallel processes for chunking
FILE_BATCH     = 2000   # files per pool instance (keeps memory flat)
```
- `MAX_TOKENS / OVERLAP_TOKENS` implement a **sliding window**. With 1024-word windows and 200-word overlap, each consecutive chunk pair shares ~200 words — context straddling a boundary is captured by both sides.
- `CPU_WORKERS = 24` uses all available cores; this stage is CPU-bound (regex + string splitting).
- `FILE_BATCH = 2000` — the Pool is restarted every 2,000 files and `gc.collect()` is called, preventing memory accumulation across tens of thousands of files.

---

#### parse_filename(filepath)
Extracts `ticker`, `filing_type`, `filing_date` from the filename convention `TICKER_FILINGTYPE_DATE.md`. Handles 3-part, 2-part, and 1-part filenames gracefully, falling back to `None` for missing fields.

---

#### split_by_sections(text)
```python
pattern = r'(^#{1,3}\s+.+$)'
parts = re.split(pattern, text, flags=re.MULTILINE)
```
Splits on markdown headers (`#`, `##`, `###`). Each `(section_name, text)` pair is chunked independently — a chunk tagged with "Risk Factors" carries more retrieval signal than one that spans two sections. Files with no headers are treated as `"Full Document"`.

---

#### chunk_text(text)
Pure word-based sliding window. Word splitting is used (not a tokeniser) because: approximate word counts are sufficient for boundary placement, and it is ~10× faster than running a tokeniser inside a multiprocessing worker.

---

#### process_file(filepath)
The multiprocessing worker — one call per `.md` file. Reads, section-splits, chunks, and drops any chunk shorter than 50 characters (stray headers / decorators). Returns a flat list of dicts.

---

#### Main Execution — 3 Stages

**Stage 1 — Scan**
Recursively globs all `.md` files under `data/md_files/`.

**Stage 2 — Connect + Truncate**
Opens the DB connection and `TRUNCATE`s the table at the very start, before any chunking begins — so the table is always in a clean state even if a previous run was interrupted.

**Stage 3 — Chunk → Insert → Free (per file batch)**
```python
for batch_start in range(0, len(all_files), FILE_BATCH):
    batch_chunks = []

    with Pool(...) as pool:
        for file_chunks in pool.imap_unordered(process_file, batch):
            batch_chunks.extend(file_chunks)

    # insert immediately
    execute_values(cur, insert_sql, rows)
    conn.commit()

    del batch_chunks, rows
    gc.collect()
```
Each file batch is chunked, **immediately inserted into PostgreSQL**, then explicitly deleted and garbage-collected before the next batch starts. At no point is more than one batch of chunks in RAM. For 38k files with `FILE_BATCH = 2000`, peak RAM usage is ~1/19th of what loading everything at once would require.

`embedding` is not included in the `INSERT` — it defaults to `NULL` and is filled by `embed.py`.

---

#### Why run as a script, not a notebook?
`multiprocessing.Pool` inside Jupyter causes deadlocks. The `if __name__ == '__main__':` guard in `chunk.py` prevents workers from re-executing `main()` on import.

Run with:
```bash
source agent/bin/activate
python chunk.py
```

---
---

## 5. embed.py

### What it does
Reads all rows where `embedding IS NULL` from PostgreSQL in streaming batches, generates 384-dimensional embeddings on the GPU, and updates each row in place. After all rows are embedded, it builds the IVFFlat approximate nearest-neighbour index. The process is **fully resumable** — if it crashes, re-running picks up exactly where it left off.

---

### Step-by-step breakdown

#### Configuration
```python
EMBED_BATCH_SIZE = 256    # chunks per GPU encode + UPDATE round-trip
IVFFLAT_LISTS   = 100    # IVFFlat Voronoi cells
```
`EMBED_BATCH_SIZE = 256` balances GPU utilisation vs. VRAM usage. Tune down if you hit CUDA OOM errors.

---

#### Streaming embed loop
```python
while True:
    cur.execute("""
        SELECT id, chunk_text FROM filing_chunks
        WHERE  embedding IS NULL
        ORDER  BY id
        LIMIT  %s;
    """, (EMBED_BATCH_SIZE,))
    rows = cur.fetchall()
    if not rows:
        break

    embeddings = model.encode(texts, convert_to_numpy=True)

    execute_batch(
        cur,
        "UPDATE filing_chunks SET embedding = %s WHERE id = %s;",
        [(emb.tolist(), row_id) for emb, row_id in zip(embeddings, ids)]
    )
    conn.commit()
```
**Why streaming instead of load-all-then-embed?**
Loading all 1.9M chunk texts into RAM and then holding all 1.9M embedding arrays simultaneously would require ~5–8 GB of RAM just for the arrays. Streaming reads one batch from the DB, embeds it, writes it back, and discards it — memory usage stays flat at `EMBED_BATCH_SIZE` rows at a time.

**Resumability:** The `WHERE embedding IS NULL` condition means the loop always processes only unfinished rows. If the process is killed, restarting it continues from the last uncommitted batch with no data loss.

`execute_batch` (from `psycopg2.extras`) sends multiple `UPDATE` statements in fewer round-trips — more efficient than one round-trip per row.

`emb.tolist()` converts the `float32` numpy array to a Python list, which psycopg2 serialises into pgvector's wire format automatically.

---

#### IVFFlat Index
```sql
CREATE INDEX idx_embedding ON filing_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```
Built **after** all embeddings are populated. Building it during millions of `UPDATE`s would be far slower — every update would trigger an index modification. With `lists = 100`, pgvector partitions the embedding space into 100 Voronoi cells. At query time only the nearest cells are scanned, giving millisecond ANN search across millions of vectors.

For tables larger than ~1M rows, a better heuristic is `lists = sqrt(total_rows)`.

---

#### Verification
After the index is built, the script reports total rows, how many were embedded in this run, and how many (if any) are still `NULL`. A sample cosine-distance query is printed for immediate use:
```sql
SELECT ticker, filing_type, section, chunk_text
FROM   filing_chunks
ORDER  BY embedding <=> '[your_vector]'::vector
LIMIT  10;
```

Run with:
```bash
source agent/bin/activate
python embed.py
```
