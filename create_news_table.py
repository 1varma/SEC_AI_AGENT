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
    print('SEC AI — Create News Articles Table')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    print("\nCreating news_articles table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            id               SERIAL PRIMARY KEY,
            ticker           VARCHAR(10)   NOT NULL,
            headline         TEXT          NOT NULL,
            summary          TEXT,
            source           VARCHAR(100),
            url              TEXT,
            published_at     TIMESTAMP,
            sentiment_label  VARCHAR(10),     -- positive / negative / neutral
            sentiment_score  NUMERIC(6,4),    -- FinBERT confidence score
            is_earnings      BOOLEAN          DEFAULT FALSE,
            created_at       TIMESTAMP        DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (ticker, url)
        );

        CREATE INDEX IF NOT EXISTS idx_news_ticker      ON news_articles(ticker);
        CREATE INDEX IF NOT EXISTS idx_news_published   ON news_articles(published_at);
        CREATE INDEX IF NOT EXISTS idx_news_sentiment   ON news_articles(sentiment_label);
        CREATE INDEX IF NOT EXISTS idx_news_ticker_date ON news_articles(ticker, published_at);
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("\nTable 'news_articles' created successfully!")
    print("\nSchema:")
    print("  id               SERIAL PRIMARY KEY")
    print("  ticker           VARCHAR(10)   NOT NULL")
    print("  headline         TEXT          NOT NULL")
    print("  summary          TEXT")
    print("  source           VARCHAR(100)")
    print("  url              TEXT")
    print("  published_at     TIMESTAMP")
    print("  sentiment_label  VARCHAR(10)   -- positive / negative / neutral")
    print("  sentiment_score  NUMERIC(6,4)  -- FinBERT confidence")
    print("  is_earnings      BOOLEAN       -- True for 8-K Item 2.02 earnings releases")
    print("  created_at       TIMESTAMP")
    print("\nIndexes: idx_news_ticker, idx_news_published, idx_news_sentiment, idx_news_ticker_date")
    print("\nNext step: python news_ingest.py")
    print('=' * 60)


if __name__ == '__main__':
    main()
