import re
import psycopg2
from psycopg2.extras import execute_values
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

# Keywords that indicate a 8-K is an earnings call / results announcement
EARNINGS_KEYWORDS = [
    "earnings call",
    "conference call",
    "earnings per share",
    "question-and-answer",
    "q&a session",
    "results of operations",
    "quarterly results",
    "fourth quarter",
    "third quarter",
    "second quarter",
    "first quarter",
    "full year results",
    "fiscal year results",
]

# Build SQL ANY array
KEYWORD_SQL = " OR ".join(
    [f"lower(chunk_text) LIKE '%%{kw}%%'" for kw in EARNINGS_KEYWORDS]
)

# Max characters to store per transcript (keep context window manageable)
MAX_TEXT_CHARS = 80_000

# Accession pattern: 0000320193-24-000123
ACCESSION_RE = re.compile(r"(\d{10}-\d{2}-\d{6})")

# Quarter inference from filing month
MONTH_TO_QUARTER = {1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2",
                    7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4"}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def find_earnings_source_files(cur):
    """
    Find 8-K source files that contain earnings-related content.
    Returns list of (ticker, source_file, filing_date) tuples.
    """
    cur.execute(f"""
        SELECT DISTINCT ticker, source_file, filing_date
        FROM   filing_chunks
        WHERE  filing_type = '8-K'
          AND  ({KEYWORD_SQL})
        ORDER  BY ticker, source_file;
    """)
    return cur.fetchall()


def get_chunks_for_source(cur, ticker: str, source_file: str):
    """Fetch all chunks for a source file, ordered by chunk_index."""
    cur.execute("""
        SELECT chunk_text, chunk_index
        FROM   filing_chunks
        WHERE  ticker = %s AND source_file = %s
        ORDER  BY chunk_index;
    """, (ticker, source_file))
    return cur.fetchall()


def parse_accession(source_file: str):
    m = ACCESSION_RE.search(source_file or "")
    return m.group(1) if m else None


def infer_quarter(filing_date):
    if filing_date is None:
        return None
    return MONTH_TO_QUARTER.get(filing_date.month)


def build_row(ticker, source_file, filing_date, chunks):
    texts       = [c[0] for c in chunks if c[0]]
    full_text   = "\n\n".join(texts)[:MAX_TEXT_CHARS]
    accession   = parse_accession(source_file)
    fiscal_year = filing_date.year if filing_date else None
    fq          = infer_quarter(filing_date)

    return {
        "ticker":         ticker,
        "source_file":    source_file,
        "accession_num":  accession,
        "filing_date":    filing_date,
        "fiscal_year":    fiscal_year,
        "fiscal_quarter": fq,
        "full_text":      full_text,
        "chunk_count":    len(chunks),
    }


def insert_batch(conn, rows):
    if not rows:
        return 0
    cur = conn.cursor()
    execute_values(cur, """
        INSERT INTO earnings_calls (
            ticker, source_file, accession_num, filing_date,
            fiscal_year, fiscal_quarter, full_text, chunk_count
        ) VALUES %s
        ON CONFLICT (ticker, source_file) DO NOTHING;
    """, [
        (
            r["ticker"], r["source_file"], r["accession_num"], r["filing_date"],
            r["fiscal_year"], r["fiscal_quarter"], r["full_text"], r["chunk_count"],
        )
        for r in rows
    ])
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def main():
    print("=" * 60)
    print("Step 4 — Ingest Earnings Call Transcripts from 8-K Chunks")
    print("=" * 60)

    conn     = get_conn()
    read_cur = conn.cursor()

    print("\nFinding earnings-related 8-K filings...")
    sources = find_earnings_source_files(read_cur)
    print(f"Found {len(sources):,} earnings call filings")

    total   = 0
    batch   = []
    errors  = []

    for ticker, source_file, filing_date in tqdm(sources, desc="Ingesting", unit="filing"):
        try:
            chunks = get_chunks_for_source(read_cur, ticker, source_file)
            if not chunks:
                continue
            row = build_row(ticker, source_file, filing_date, chunks)
            batch.append(row)

            if len(batch) >= 100:
                total += insert_batch(conn, batch)
                batch = []

        except Exception as e:
            errors.append((ticker, source_file, str(e)))

    if batch:
        total += insert_batch(conn, batch)

    read_cur.close()
    conn.close()

    print(f"\nRows inserted: {total:,}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for ticker, sf, err in errors[:20]:
            print(f"  {ticker} {sf}: {err}")

    print('=' * 60)
    print("Next step: python refresh_stocks.py")
    print('=' * 60)


if __name__ == "__main__":
    main()
