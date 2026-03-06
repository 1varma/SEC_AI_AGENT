import psycopg2

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}


def main():
    print('=' * 60)
    print('Phase 7 — Add Hybrid Search (BM25 tsvector + GIN index)')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    # ── Step 1: Add generated tsvector column ─────────────────────────────────
    print("\nAdding fts column (GENERATED tsvector)...")
    cur.execute("""
        ALTER TABLE filing_chunks
        ADD COLUMN IF NOT EXISTS fts tsvector
            GENERATED ALWAYS AS (
                to_tsvector('english',
                    coalesce(chunk_text,  '') || ' ' ||
                    coalesce(section,     '') || ' ' ||
                    coalesce(ticker,      '') || ' ' ||
                    coalesce(filing_type, '')
                )
            ) STORED;
    """)
    conn.commit()
    print("  Done — fts column added and auto-populated for all 2.8M rows.")

    # ── Step 2: GIN index for fast full-text search ────────────────────────────
    print("\nCreating GIN index on fts (may take a few minutes)...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_fts ON filing_chunks USING GIN(fts);
    """)
    conn.commit()
    print("  Done — GIN index created.")

    cur.close()
    conn.close()

    print("\nHybrid search ready:")
    print("  Dense  : IVFFlat cosine similarity (all-MiniLM-L6-v2, existing)")
    print("  BM25   : GIN tsvector full-text search (new)")
    print("  Fusion : Reciprocal Rank Fusion (RRF, k=60)")
    print('=' * 60)


if __name__ == '__main__':
    main()
