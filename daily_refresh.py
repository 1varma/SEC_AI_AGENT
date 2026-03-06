"""
FinSight AI — Daily Refresh Orchestrator
=========================================
Runs all daily data refresh jobs in sequence:
  1. Stock prices      (yfinance incremental)
  2. News ingestion    (RSS feeds, 473 tickers)
  3. News sentiment    (FinBERT GPU scoring)

Usage:
  python daily_refresh.py

Cron (weekdays at 5:00 PM — after US market close):
  0 17 * * 1-5  cd /home/ashish-varma-j/Desktop/SEC_AI_AGENT && \
                /home/ashish-varma-j/Desktop/SEC_AI_AGENT/agent/bin/python \
                daily_refresh.py >> /tmp/finsight_refresh.log 2>&1
"""

import sys
import traceback
from datetime import datetime


def run_step(name: str, fn):
    print(f"\n{'=' * 60}")
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]  Starting: {name}")
    print('=' * 60)
    try:
        fn()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]  Done: {name}")
    except Exception:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]  FAILED: {name}")
        traceback.print_exc()


def main():
    print("=" * 60)
    print(f"FinSight AI — Daily Refresh  [{datetime.now():%Y-%m-%d %H:%M:%S}]")
    print("=" * 60)

    from refresh_stocks import main as refresh_stocks
    from news_ingest    import main as ingest_news
    from sentiment      import main as run_sentiment

    run_step("Stock Price Refresh",  refresh_stocks)
    run_step("News Ingestion (RSS)", ingest_news)
    run_step("Sentiment Scoring",    run_sentiment)

    print(f"\n{'=' * 60}")
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]  All refresh jobs complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
