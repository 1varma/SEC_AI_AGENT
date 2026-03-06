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
    print('Phase 7 — Create Financials Table (EDGAR XBRL)')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    print("\nCreating financials table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS financials (
            id                   SERIAL PRIMARY KEY,
            ticker               VARCHAR(10)   NOT NULL,
            cik                  VARCHAR(10),
            period_end           DATE          NOT NULL,
            period_type          VARCHAR(9)    NOT NULL,    -- 'annual' | 'quarterly'
            fiscal_year          INTEGER,
            fiscal_quarter       INTEGER,                   -- NULL for annual

            -- Income Statement (USD)
            revenue              BIGINT,
            gross_profit         BIGINT,
            operating_income     BIGINT,
            net_income           BIGINT,
            eps_basic            NUMERIC(14, 4),
            eps_diluted          NUMERIC(14, 4),
            rd_expense           BIGINT,

            -- Balance Sheet (USD, point-in-time at period_end)
            total_assets         BIGINT,
            total_liabilities    BIGINT,
            stockholders_equity  BIGINT,
            cash                 BIGINT,
            long_term_debt       BIGINT,

            -- Cash Flow Statement (USD)
            operating_cash_flow  BIGINT,
            capex                BIGINT,
            free_cash_flow       BIGINT,     -- computed: operating_cash_flow - |capex|

            -- Computed Margins (ratio, e.g. 0.4321 = 43.21%)
            gross_margin         NUMERIC(10, 4),
            operating_margin     NUMERIC(10, 4),
            net_margin           NUMERIC(10, 4),

            -- Metadata
            form_type            VARCHAR(10),
            created_at           TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (ticker, period_end, period_type)
        );

        CREATE INDEX IF NOT EXISTS idx_fin_ticker      ON financials(ticker);
        CREATE INDEX IF NOT EXISTS idx_fin_period_end  ON financials(period_end);
        CREATE INDEX IF NOT EXISTS idx_fin_ticker_year ON financials(ticker, fiscal_year);
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("\nTable 'financials' created successfully!")
    print("\nSchema:")
    print("  ticker, cik, period_end, period_type, fiscal_year, fiscal_quarter")
    print("  Income: revenue, gross_profit, operating_income, net_income, eps_basic/diluted, rd_expense")
    print("  Balance: total_assets, total_liabilities, stockholders_equity, cash, long_term_debt")
    print("  CashFlow: operating_cash_flow, capex, free_cash_flow")
    print("  Margins: gross_margin, operating_margin, net_margin")
    print("\nNext step: python ingest_xbrl.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
