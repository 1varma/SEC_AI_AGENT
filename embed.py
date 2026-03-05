import psycopg2
from psycopg2.extras import execute_batch
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG        = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}
EMBED_BATCH_SIZE = 256    # chunks per GPU encode + UPDATE round-trip
IVFFLAT_LISTS   = 100    # IVFFlat Voronoi cells (tune: sqrt(n_rows) for large tables)


def main():
    print('=' * 60)
    print('SEC Filing Embedder')
    print('=' * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur  = conn.cursor()

    # ─── 1. Count pending rows ────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM filing_chunks WHERE embedding IS NULL;")
    total = cur.fetchone()[0]
    print(f"\nChunks pending embedding: {total:,}")

    if total == 0:
        print("Nothing to embed. Run chunk.py first, or all rows already embedded.")
        cur.close()
        conn.close()
        return

    # ─── 2. Load model ────────────────────────────────────────────────────────
    print("\nLoading embedding model (all-MiniLM-L6-v2) on CUDA...")
    model = SentenceTransformer('all-MiniLM-L6-v2', device='cuda')
    print("Model loaded.\n")

    # ─── 3. Stream: read batch → embed → UPDATE → commit ─────────────────────
    # Fully resumable: always queries WHERE embedding IS NULL, so if the process
    # crashes mid-way, re-running picks up exactly where it left off.
    processed = 0
    with tqdm(total=total, desc="Embedding", unit="chunk") as pbar:
        while True:
            cur.execute("""
                SELECT id, chunk_text
                FROM   filing_chunks
                WHERE  embedding IS NULL
                ORDER  BY id
                LIMIT  %s;
            """, (EMBED_BATCH_SIZE,))
            rows = cur.fetchall()

            if not rows:
                break

            ids        = [r[0] for r in rows]
            texts      = [r[1] for r in rows]
            embeddings = model.encode(
                texts,
                show_progress_bar=False,
                convert_to_numpy=True
            )

            execute_batch(
                cur,
                "UPDATE filing_chunks SET embedding = %s WHERE id = %s;",
                [(emb.tolist(), row_id) for emb, row_id in zip(embeddings, ids)]
            )
            conn.commit()

            processed += len(rows)
            pbar.update(len(rows))

    print(f"\nEmbedded {processed:,} chunks.\n")

    # ─── 4. Build IVFFlat vector index ───────────────────────────────────────
    # Built after all embeddings are populated — maintaining the index during
    # millions of individual UPDATEs would be far slower.
    print("Creating IVFFlat vector index (may take a few minutes)...")
    cur.execute(f"""
        DROP INDEX IF EXISTS idx_embedding;
        CREATE INDEX idx_embedding ON filing_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = {IVFFLAT_LISTS});
    """)
    conn.commit()
    print(f"Index created with lists = {IVFFLAT_LISTS}.")

    # ─── 5. Verify ────────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM filing_chunks WHERE embedding IS NULL;")
    remaining = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM filing_chunks;")
    total_rows = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"\n{'=' * 60}")
    print(f"Total rows:          {total_rows:,}")
    print(f"Embedded:            {total_rows - remaining:,}")
    print(f"Still NULL:          {remaining:,}")
    print("\nQuery example:")
    print("  SELECT ticker, filing_type, section, chunk_text")
    print("  FROM   filing_chunks")
    print("  ORDER  BY embedding <=> '[your_vector]'::vector")
    print("  LIMIT  10;")
    print('=' * 60)


if __name__ == '__main__':
    main()
