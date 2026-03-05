import io
import boto3
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
BUCKET      = "sec-filings-raw-data-ashish-v1"
S3_PREFIX   = "stocks/"
DB_CONFIG   = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}
MAX_WORKERS  = 8     # parallel S3 downloads (I/O bound)
INSERT_BATCH = 2000  # rows per PostgreSQL INSERT


# ─── Download + parse one ticker CSV from S3 ──────────────────────────────────
def fetch_ticker(s3_client, key):
    """Download one CSV from S3, parse it, return list of row tuples."""
    ticker = key.replace(S3_PREFIX, "").replace(".csv", "").upper()
    try:
        obj  = s3_client.get_object(Bucket=BUCKET, Key=key)
        data = obj["Body"].read()

        df = pd.read_csv(
            io.BytesIO(data),
            skiprows=2,
            header=None,
            names=["date", "close", "high", "low", "open", "volume"]
        )

        # drop any residual header rows
        df = df[pd.to_datetime(df["date"], errors="coerce").notna()].copy()
        df["date"]   = pd.to_datetime(df["date"]).dt.date
        df["ticker"] = ticker

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") \
                         .astype("Int64")

        df = df.dropna(subset=["date", "close"])

        rows = [
            (
                row.ticker,
                row.date,
                None if pd.isna(row.open)   else float(row.open),
                None if pd.isna(row.high)   else float(row.high),
                None if pd.isna(row.low)    else float(row.low),
                float(row.close),
                None if pd.isna(row.volume) else int(row.volume),
            )
            for row in df.itertuples(index=False)
        ]
        return ticker, rows, None

    except Exception as e:
        return ticker, [], str(e)


def main():
    print('=' * 60)
    print('SEC AI — Ingest Stock Prices from S3')
    print('=' * 60)

    s3 = boto3.client("s3")

    # ─── 1. List all ticker CSVs ──────────────────────────────────────────────
    print(f"\nListing s3://{BUCKET}/{S3_PREFIX} ...")
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".csv"):
                keys.append(obj["Key"])
    print(f"Found {len(keys)} ticker files\n")

    # ─── 2. Connect to DB ─────────────────────────────────────────────────────
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    insert_sql = """
        INSERT INTO stock_prices (ticker, date, open, high, low, close, volume)
        VALUES %s
        ON CONFLICT (ticker, date) DO NOTHING
    """

    # ─── 3. Parallel download + sequential insert ─────────────────────────────
    # Downloads are I/O bound → ThreadPoolExecutor
    # Inserts are sequential to avoid DB connection contention
    total_rows    = 0
    failed        = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_ticker, s3, key): key
            for key in keys
        }

        for future in tqdm(as_completed(futures), total=len(keys), desc="Downloading & inserting"):
            ticker, rows, error = future.result()

            if error:
                failed.append((ticker, error))
                continue

            if not rows:
                continue

            # Insert in batches
            for i in range(0, len(rows), INSERT_BATCH):
                execute_values(cur, insert_sql, rows[i:i + INSERT_BATCH])
            conn.commit()
            total_rows += len(rows)

    cur.close()
    conn.close()

    # ─── 4. Summary ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Total rows inserted:  {total_rows:,}")
    print(f"Tickers processed:    {len(keys) - len(failed)}")
    print(f"Failed:               {len(failed)}")
    if failed:
        for ticker, err in failed:
            print(f"  {ticker}: {err}")

    # ─── 5. Verify ────────────────────────────────────────────────────────────
    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM stock_prices;")
    print(f"\nTotal rows in DB:     {cur.fetchone()[0]:,}")

    cur.execute("""
        SELECT ticker, MIN(date), MAX(date), COUNT(*) AS trading_days
        FROM stock_prices
        GROUP BY ticker
        ORDER BY trading_days DESC
        LIMIT 10;
    """)
    print("\nTop 10 tickers by history length:")
    print(f"  {'Ticker':<8} {'From':<12} {'To':<12} {'Days':>6}")
    print(f"  {'-'*8} {'-'*12} {'-'*12} {'-'*6}")
    for row in cur.fetchall():
        print(f"  {row[0]:<8} {str(row[1]):<12} {str(row[2]):<12} {row[3]:>6,}")

    cur.close()
    conn.close()
    print('=' * 60)


if __name__ == '__main__':
    main()
