import psycopg2
from psycopg2.extras import execute_batch
from transformers import pipeline
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

BATCH_SIZE  = 256    # articles per GPU inference batch
MAX_LENGTH  = 512    # FinBERT max token length


def main():
    print('=' * 60)
    print('SEC AI — Sentiment Scoring (FinBERT)')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    # ─── 1. Count pending rows ────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM news_articles WHERE sentiment_label IS NULL;")
    total = cur.fetchone()[0]
    print(f"\nArticles pending sentiment scoring: {total:,}")

    if total == 0:
        print("Nothing to score. Run news_ingest.py first, or all rows already scored.")
        cur.close()
        conn.close()
        return

    # ─── 2. Load FinBERT ──────────────────────────────────────────────────────
    # ProsusAI/finbert: finance-specific BERT trained on financial phrasebank
    # Labels: positive / negative / neutral
    print("\nLoading FinBERT model on CUDA...")
    finbert = pipeline(
        "text-classification",
        model="ProsusAI/finbert",
        device=0,                   # CUDA GPU 0
        truncation=True,
        max_length=MAX_LENGTH
    )
    print("Model loaded.\n")

    # ─── 3. Stream: read batch → score → UPDATE → commit ─────────────────────
    processed = 0
    with tqdm(total=total, desc="Scoring", unit="article") as pbar:
        while True:
            cur.execute("""
                SELECT id, headline, summary
                FROM   news_articles
                WHERE  sentiment_label IS NULL
                ORDER  BY id
                LIMIT  %s;
            """, (BATCH_SIZE,))
            rows = cur.fetchall()

            if not rows:
                break

            ids   = [r[0] for r in rows]
            texts = [
                # Use headline + summary together for richer signal
                f"{r[1]}. {r[2]}" if r[2] else r[1]
                for r in rows
            ]

            results = finbert(texts, batch_size=BATCH_SIZE)

            execute_batch(
                cur,
                """
                UPDATE news_articles
                SET sentiment_label = %s,
                    sentiment_score = %s
                WHERE id = %s;
                """,
                [
                    (res["label"].lower(), round(res["score"], 4), row_id)
                    for res, row_id in zip(results, ids)
                ]
            )
            conn.commit()

            processed += len(rows)
            pbar.update(len(rows))

    print(f"\nScored {processed:,} articles.\n")

    # ─── 4. Verify ────────────────────────────────────────────────────────────
    cur.execute("""
        SELECT sentiment_label, COUNT(*), ROUND(AVG(sentiment_score), 4)
        FROM   news_articles
        WHERE  sentiment_label IS NOT NULL
        GROUP  BY sentiment_label
        ORDER  BY COUNT(*) DESC;
    """)
    print(f"{'Label':<12} {'Count':>10} {'Avg Score':>12}")
    print('-' * 36)
    for label, count, avg in cur.fetchall():
        print(f"{label:<12} {count:>10,} {avg:>12.4f}")

    cur.execute("SELECT COUNT(*) FROM news_articles WHERE sentiment_label IS NULL;")
    remaining = cur.fetchone()[0]
    print(f"\nStill NULL: {remaining:,}")

    cur.close()
    conn.close()

    print(f"\n{'=' * 60}")
    print("Sentiment scoring complete.")
    print('=' * 60)


if __name__ == '__main__':
    main()
