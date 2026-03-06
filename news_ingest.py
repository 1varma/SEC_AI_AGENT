import time
import psycopg2
import feedparser
import requests
from psycopg2.extras import execute_values
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

REQUEST_DELAY   = 1.0    # seconds between RSS requests (be polite)
INSERT_BATCH    = 200    # rows per PostgreSQL INSERT
MAX_PER_TICKER  = 50     # max articles per ticker per run (RSS is recent only)

HEADERS = {
    "User-Agent": "FinSightAI/1.0 (financial research; contact@finsight.ai)"
}


def get_tickers(conn):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ticker FROM stock_prices ORDER BY ticker;")
    tickers = [row[0] for row in cur.fetchall()]
    cur.close()
    return tickers


def parse_date(entry):
    """Try multiple date fields from RSS entry."""
    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            try:
                return parsedate_to_datetime(val).astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass
    return None


def fetch_yahoo_rss(ticker):
    """Yahoo Finance RSS for a ticker."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        articles = []
        for entry in feed.entries[:MAX_PER_TICKER]:
            articles.append({
                "ticker":       ticker,
                "headline":     entry.get("title", "").strip(),
                "summary":      entry.get("summary", "").strip()[:2000],
                "source":       "Yahoo Finance",
                "url":          entry.get("link", "").strip(),
                "published_at": parse_date(entry),
            })
        return articles
    except Exception:
        return []


def fetch_google_news_rss(ticker):
    """Google News RSS for a ticker company name."""
    url = f"https://news.google.com/rss/search?q={ticker}+stock+earnings&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        articles = []
        for entry in feed.entries[:MAX_PER_TICKER]:
            articles.append({
                "ticker":       ticker,
                "headline":     entry.get("title", "").strip(),
                "summary":      entry.get("summary", "").strip()[:2000],
                "source":       "Google News",
                "url":          entry.get("link", "").strip(),
                "published_at": parse_date(entry),
            })
        return articles
    except Exception:
        return []


def insert_articles(cur, articles):
    if not articles:
        return 0
    rows = [
        (
            a["ticker"], a["headline"], a["summary"],
            a["source"], a["url"], a["published_at"]
        )
        for a in articles
        if a["headline"] and a["url"]
    ]
    if not rows:
        return 0
    execute_values(
        cur,
        """
        INSERT INTO news_articles (ticker, headline, summary, source, url, published_at)
        VALUES %s
        ON CONFLICT (ticker, url) DO NOTHING
        """,
        rows
    )
    return len(rows)


def main():
    print('=' * 60)
    print('SEC AI — News Ingestion (RSS)')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    tickers = get_tickers(conn)
    print(f"\nTickers to fetch: {len(tickers):,}")
    print(f"Sources: Yahoo Finance RSS + Google News RSS")
    print(f"Max articles per ticker per source: {MAX_PER_TICKER}\n")

    cur = conn.cursor()
    total_inserted = 0
    total_skipped  = 0

    for ticker in tqdm(tickers, desc="Fetching news", unit="ticker"):
        articles = []
        articles.extend(fetch_yahoo_rss(ticker))
        time.sleep(REQUEST_DELAY)
        articles.extend(fetch_google_news_rss(ticker))
        time.sleep(REQUEST_DELAY)

        inserted = insert_articles(cur, articles)
        skipped  = len(articles) - inserted
        total_inserted += inserted
        total_skipped  += skipped

        if (tickers.index(ticker) + 1) % 50 == 0:
            conn.commit()

    conn.commit()

    # ─── Final counts ─────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM news_articles;")
    total_rows = cur.fetchone()[0]

    cur.execute("""
        SELECT source, COUNT(*) FROM news_articles
        GROUP BY source ORDER BY COUNT(*) DESC;
    """)
    source_counts = cur.fetchall()

    cur.close()
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"Articles inserted this run: {total_inserted:,}")
    print(f"Duplicates skipped:         {total_skipped:,}")
    print(f"Total in DB:                {total_rows:,}")
    print(f"\nBreakdown by source:")
    for source, count in source_counts:
        print(f"  {source:20s}  {count:,}")
    print(f"\nNext step: python sentiment.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
