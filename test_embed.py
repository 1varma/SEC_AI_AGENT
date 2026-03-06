import psycopg2
from sentence_transformers import SentenceTransformer

DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

QUERY = "Apple revenue growth and iPhone sales performance"

def main():
    print("=" * 60)
    print("Embedding Test")
    print("=" * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    # 1. Row counts
    cur.execute("SELECT COUNT(*) FROM filing_chunks;")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM filing_chunks WHERE embedding IS NULL;")
    null_count = cur.fetchone()[0]
    embedded = total - null_count

    print(f"\nTotal chunks:    {total:,}")
    print(f"Embedded:        {embedded:,}")
    print(f"Still NULL:      {null_count:,}")
    print(f"Coverage:        {embedded/total*100:.2f}%" if total else "N/A")

    # 2. Index check
    cur.execute("""
        SELECT indexname, indexdef
        FROM   pg_indexes
        WHERE  tablename = 'filing_chunks'
          AND  indexname = 'idx_embedding';
    """)
    row = cur.fetchone()
    print(f"\nIVFFlat index:   {'EXISTS' if row else 'MISSING'}")
    if row:
        print(f"  {row[1]}")

    # 3. Sample a random embedded row
    cur.execute("""
        SELECT id, ticker, filing_type, filing_date, chunk_text
        FROM   filing_chunks
        WHERE  embedding IS NOT NULL
        ORDER  BY RANDOM()
        LIMIT  1;
    """)
    sample = cur.fetchone()
    if sample:
        print(f"\nSample embedded row:")
        print(f"  id={sample[0]}  ticker={sample[1]}  type={sample[2]}  date={sample[3]}")
        print(f"  text preview: {sample[4][:200]!r}")

    # 4. Semantic similarity search
    print(f"\nSemantic search: '{QUERY}'")
    model = SentenceTransformer('all-MiniLM-L6-v2', device='cuda')
    vec = model.encode(QUERY, convert_to_numpy=True).tolist()

    cur.execute("""
        SELECT ticker, filing_type, filing_date,
               1 - (embedding <=> %s::vector) AS cosine_similarity,
               LEFT(chunk_text, 300)
        FROM   filing_chunks
        WHERE  embedding IS NOT NULL
        ORDER  BY embedding <=> %s::vector
        LIMIT  5;
    """, (vec, vec))

    results = cur.fetchall()
    print(f"\nTop 5 results:")
    for i, (ticker, ftype, fdate, sim, text) in enumerate(results, 1):
        print(f"\n  [{i}] {ticker} | {ftype} | {fdate} | similarity={sim:.4f}")
        print(f"      {text.strip()[:200]!r}")

    cur.close()
    conn.close()
    print("\n" + "=" * 60)
    print("Test complete.")
    print("=" * 60)


if __name__ == '__main__':
    main()
