import time
import requests
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

EDGAR_HEADERS = {
    "User-Agent": "FinSightAI/1.0 (financial-research; contact@finsight.ai)",
    "Accept-Encoding": "gzip, deflate",
}

REQUEST_DELAY = 0.15   # ~6–7 req/sec (EDGAR cap: 10/sec)


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def fetch_cik_map():
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=EDGAR_HEADERS, timeout=30
    )
    resp.raise_for_status()
    return {
        entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
        for entry in resp.json().values()
    }


def fetch_submissions(cik: str):
    """Download EDGAR submissions JSON (company metadata) for a CIK."""
    url  = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def parse_submission(ticker: str, cik: str, data: dict) -> dict:
    exchanges = data.get("exchanges", [])
    return {
        "ticker":                 ticker,
        "cik":                    cik,
        "name":                   data.get("name"),
        "sic_code":               data.get("sic"),
        "sic_description":        data.get("sicDescription"),
        "state_of_incorporation": data.get("stateOfIncorporation"),
        "fiscal_year_end":        data.get("fiscalYearEnd"),
        "exchange":               exchanges[0] if exchanges else None,
        "category":               data.get("category"),
        "ein":                    data.get("ein"),
    }


def upsert_rows(conn, rows):
    if not rows:
        return 0
    cur = conn.cursor()
    execute_values(cur, """
        INSERT INTO company_info (
            ticker, cik, name, sic_code, sic_description,
            state_of_incorporation, fiscal_year_end,
            exchange, category, ein, updated_at
        ) VALUES %s
        ON CONFLICT (ticker) DO UPDATE SET
            cik                    = EXCLUDED.cik,
            name                   = EXCLUDED.name,
            sic_code               = EXCLUDED.sic_code,
            sic_description        = EXCLUDED.sic_description,
            state_of_incorporation = EXCLUDED.state_of_incorporation,
            fiscal_year_end        = EXCLUDED.fiscal_year_end,
            exchange               = EXCLUDED.exchange,
            category               = EXCLUDED.category,
            ein                    = EXCLUDED.ein,
            updated_at             = CURRENT_TIMESTAMP;
    """, [
        (
            r["ticker"], r["cik"], r["name"], r["sic_code"], r["sic_description"],
            r["state_of_incorporation"], r["fiscal_year_end"],
            r["exchange"], r["category"], r["ein"], "NOW()"
        )
        for r in rows
    ])
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def main():
    print("=" * 60)
    print("Step 2 — Ingest Company Info (EDGAR Submissions API)")
    print("=" * 60)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT DISTINCT ticker FROM stock_prices ORDER BY ticker;")
    tickers = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"\nTickers: {len(tickers)}")

    cik_map   = fetch_cik_map()
    time.sleep(REQUEST_DELAY)

    matched   = [(t, cik_map[t]) for t in tickers if t in cik_map]
    unmatched = [t for t in tickers if t not in cik_map]
    print(f"CIK matched: {len(matched)} / {len(tickers)}")
    if unmatched:
        print(f"No CIK: {unmatched}")

    total   = 0
    errors  = []
    conn    = get_conn()
    batch   = []

    for ticker, cik in tqdm(matched, desc="Company info", unit="ticker"):
        try:
            data = fetch_submissions(cik)
            time.sleep(REQUEST_DELAY)
            if not data:
                continue
            batch.append(parse_submission(ticker, cik, data))
            if len(batch) >= 50:
                total += upsert_rows(conn, batch)
                batch = []
        except Exception as e:
            errors.append((ticker, str(e)))

    if batch:
        total += upsert_rows(conn, batch)

    conn.close()

    print(f"\nRows upserted: {total:,}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for ticker, err in errors:
            print(f"  {ticker}: {err}")

    print('=' * 60)
    print("Next step: python create_earnings_table.py && python ingest_earnings.py")
    print('=' * 60)


if __name__ == "__main__":
    main()
