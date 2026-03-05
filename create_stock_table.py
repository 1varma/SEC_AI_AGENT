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
    print('SEC AI — Create Stock Prices Table')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    print("\nCreating stock_prices table...")
    cur.execute("""
        DROP TABLE IF EXISTS stock_prices;

        CREATE TABLE stock_prices (
            id        SERIAL PRIMARY KEY,
            ticker    VARCHAR(10)   NOT NULL,
            date      DATE          NOT NULL,
            open      NUMERIC(15,6),
            high      NUMERIC(15,6),
            low       NUMERIC(15,6),
            close     NUMERIC(15,6),
            volume    BIGINT,
            UNIQUE (ticker, date)
        );

        CREATE INDEX idx_sp_ticker ON stock_prices(ticker);
        CREATE INDEX idx_sp_date   ON stock_prices(date);
        CREATE INDEX idx_sp_ticker_date ON stock_prices(ticker, date);
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("\nTable 'stock_prices' created successfully!")
    print("\nSchema:")
    print("  id        SERIAL PRIMARY KEY")
    print("  ticker    VARCHAR(10)   NOT NULL")
    print("  date      DATE          NOT NULL")
    print("  open      NUMERIC(15,6)")
    print("  high      NUMERIC(15,6)")
    print("  low       NUMERIC(15,6)")
    print("  close     NUMERIC(15,6)")
    print("  volume    BIGINT")
    print("  UNIQUE (ticker, date)")
    print("\nIndexes: idx_sp_ticker, idx_sp_date, idx_sp_ticker_date")
    print("\nNext step: python ingest_stocks.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
