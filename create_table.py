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
    print('SEC Filing — Create Table')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    print("\nDropping existing table (if any) and creating fresh schema...")
    cur.execute("""
        DROP TABLE IF EXISTS filing_chunks;

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

        -- B-tree indexes for fast metadata filtering
        CREATE INDEX idx_ticker      ON filing_chunks(ticker);
        CREATE INDEX idx_filing_type ON filing_chunks(filing_type);
        CREATE INDEX idx_filing_date ON filing_chunks(filing_date);

        -- Note: IVFFlat vector index (idx_embedding) is created by embed.py
        -- AFTER bulk insert — building it during insertion is orders of magnitude slower.
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("\nTable 'filing_chunks' created successfully!")
    print("\nSchema:")
    print("  id           SERIAL PRIMARY KEY")
    print("  ticker       VARCHAR(10)  NOT NULL")
    print("  filing_type  VARCHAR(10)  NOT NULL")
    print("  filing_date  DATE")
    print("  section      TEXT")
    print("  chunk_index  INTEGER")
    print("  chunk_text   TEXT         NOT NULL")
    print("  embedding    vector(384)  (NULL until embed.py runs)")
    print("  source_file  TEXT")
    print("  created_at   TIMESTAMP")
    print("\nIndexes created: idx_ticker, idx_filing_type, idx_filing_date")
    print("\nNext step: python chunk.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
