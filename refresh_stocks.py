import yfinance as yf
import psycopg2
from psycopg2.extras import execute_values
from datetime import date, timedelta
import pandas as pd
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

BATCH_SIZE   = 20   # tickers per yfinance bulk download
BATCH_INSERT = 500  # rows per PostgreSQL INSERT


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def get_last_dates(conn):
    """Return {ticker: last_date} for all tickers in stock_prices."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, MAX(date) AS last_date
        FROM   stock_prices
        GROUP  BY ticker;
    """)
    result = {row[0]: row[1] for row in cur.fetchall()}
    cur.close()
    return result


def get_all_tickers(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ticker FROM stock_prices ORDER BY ticker;")
    tickers = [row[0] for row in cur.fetchall()]
    cur.close()
    return tickers


def download_batch(tickers: list, start: date, end: date) -> pd.DataFrame:
    """Download OHLCV for a batch of tickers using yfinance."""
    ticker_str = " ".join(tickers)
    df = yf.download(
        ticker_str,
        start=str(start),
        end=str(end),
        auto_adjust=True,
        progress=False,
    )
    return df


def parse_batch_df(df: pd.DataFrame, tickers: list, start: date) -> list:
    """Convert yfinance multi-ticker DataFrame → list of row dicts."""
    rows = []
    if df.empty:
        return rows

    # Single ticker: flat columns. Multiple: MultiIndex (field, ticker)
    if isinstance(df.columns, pd.MultiIndex):
        for ticker in tickers:
            try:
                sub = df.xs(ticker, axis=1, level=1).dropna(how="all")
                sub = sub[sub.index.date >= start]
                for idx, row in sub.iterrows():
                    rows.append({
                        "ticker": ticker,
                        "date":   idx.date(),
                        "open":   float(row.get("Open",   row.get("open",   None)) or 0) or None,
                        "high":   float(row.get("High",   row.get("high",   None)) or 0) or None,
                        "low":    float(row.get("Low",    row.get("low",    None)) or 0) or None,
                        "close":  float(row.get("Close",  row.get("close",  None)) or 0) or None,
                        "volume": int(row.get("Volume",  row.get("volume",  0)) or 0),
                    })
            except (KeyError, Exception):
                continue
    else:
        # Single ticker
        ticker = tickers[0]
        df = df.dropna(how="all")
        df = df[df.index.date >= start]
        for idx, row in df.iterrows():
            rows.append({
                "ticker": ticker,
                "date":   idx.date(),
                "open":   float(row.get("Open",   row.get("open",   None)) or 0) or None,
                "high":   float(row.get("High",   row.get("high",   None)) or 0) or None,
                "low":    float(row.get("Low",    row.get("low",    None)) or 0) or None,
                "close":  float(row.get("Close",  row.get("close",  None)) or 0) or None,
                "volume": int(row.get("Volume",  row.get("volume",  0)) or 0),
            })

    return rows


def insert_rows(conn, rows: list) -> int:
    if not rows:
        return 0
    cur = conn.cursor()
    execute_values(cur, """
        INSERT INTO stock_prices (ticker, date, open, high, low, close, volume)
        VALUES %s
        ON CONFLICT (ticker, date) DO NOTHING;
    """, [
        (r["ticker"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"])
        for r in rows
    ])
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def main():
    print("=" * 60)
    print("Step 5 — Refresh Stock Prices (yfinance incremental)")
    print("=" * 60)

    conn       = get_conn()
    tickers    = get_all_tickers(conn)
    last_dates = get_last_dates(conn)

    today      = date.today()
    yesterday  = today - timedelta(days=1)

    print(f"\nTickers: {len(tickers)}")
    print(f"Fetching up to: {yesterday}")

    total   = 0
    errors  = []

    # Group tickers into batches; each batch shares the same start date
    # (earliest last_date in the batch — ensures no gaps)
    batches = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for batch in tqdm(batches, desc="Downloading", unit="batch"):
        try:
            # Start from the earliest last_date in this batch + 1 day
            starts  = [last_dates.get(t, date(2020, 1, 1)) for t in batch]
            start   = min(starts) + timedelta(days=1)

            if start > yesterday:
                continue  # already up-to-date

            df   = download_batch(batch, start, today)
            rows = parse_batch_df(df, batch, start)

            for i in range(0, len(rows), BATCH_INSERT):
                total += insert_rows(conn, rows[i:i + BATCH_INSERT])

        except Exception as e:
            errors.append((batch, str(e)))

    conn.close()

    print(f"\nNew rows inserted: {total:,}")
    if errors:
        print(f"\nErrors ({len(errors)} batches):")
        for batch, err in errors[:10]:
            print(f"  {batch[0]}…: {err}")

    print('=' * 60)


if __name__ == "__main__":
    main()
