import psycopg2

DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}


def main():
    print('=' * 60)
    print('Step 2 — Create Company Info Table')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS company_info (
            ticker                 VARCHAR(10)  PRIMARY KEY,
            cik                    VARCHAR(10),
            name                   VARCHAR(300),
            sic_code               VARCHAR(4),
            sic_description        VARCHAR(200),
            state_of_incorporation VARCHAR(5),
            fiscal_year_end        VARCHAR(4),   -- MMDD e.g. "0930" = Sep 30
            exchange               VARCHAR(100),
            category               VARCHAR(100), -- e.g. "Large accelerated filer"
            ein                    VARCHAR(20),  -- employer ID
            created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_ci_cik  ON company_info(cik);
        CREATE INDEX IF NOT EXISTS idx_ci_sic  ON company_info(sic_code);
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("\nTable 'company_info' created.")
    print("Next step: python ingest_company_info.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
