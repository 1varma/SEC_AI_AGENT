import psycopg2

DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}


def main():
    print('=' * 60)
    print('Step 4 — Create Earnings Calls Table')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS earnings_calls (
            id              SERIAL PRIMARY KEY,
            ticker          VARCHAR(10)  NOT NULL,
            source_file     TEXT         NOT NULL,
            accession_num   VARCHAR(60),
            filing_date     DATE,
            fiscal_year     INTEGER,
            fiscal_quarter  VARCHAR(5),   -- 'Q1' | 'Q2' | 'Q3' | 'Q4' | 'FY'
            full_text       TEXT,         -- concatenated chunks (ordered by chunk_index)
            chunk_count     INTEGER,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (ticker, source_file)
        );

        CREATE INDEX IF NOT EXISTS idx_ec_ticker ON earnings_calls(ticker);
        CREATE INDEX IF NOT EXISTS idx_ec_fy     ON earnings_calls(ticker, fiscal_year);
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("\nTable 'earnings_calls' created.")
    print("Next step: python ingest_earnings.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
