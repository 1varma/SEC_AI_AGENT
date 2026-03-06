import numpy as np
import psycopg2
from sentence_transformers import SentenceTransformer

# ─── Configuration ────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "database": "sec_filings",
    "user":     "ashish",
    "password": "ashish"
}

# Model loaded once at module level — reused across all requests
_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2', device='cuda')
    return _model


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


# ─── Tool 1: SEC Filing Search (Hybrid BM25 + Dense + RRF) ────────────────────
def search_filings(query: str, ticker: str = None, filing_type: str = None, top_k: int = 5):
    """
    Hybrid retrieval over filing_chunks:
      - Dense path  : cosine similarity via pgvector (all-MiniLM-L6-v2)
      - BM25 path   : PostgreSQL full-text search (tsvector / GIN index)
      - Fusion      : Reciprocal Rank Fusion (RRF, k=60)
    Falls back to dense-only if the fts column is not yet populated.
    """
    top_k       = min(top_k, 10)
    candidate_k = min(top_k * 10, 100)  # candidates per path before fusion

    model = get_model()
    vec   = model.encode(query, convert_to_numpy=True).tolist()

    # Build shared filter conditions
    filter_clauses = []
    filter_params  = []
    if ticker:
        filter_clauses.append("ticker = %s")
        filter_params.append(ticker.upper())
    if filing_type:
        filter_clauses.append("filing_type = %s")
        filter_params.append(filing_type)

    filter_sql = (" AND " + " AND ".join(filter_clauses)) if filter_clauses else ""

    conn = get_conn()
    cur  = conn.cursor()

    sql = f"""
    WITH dense_raw AS (
        SELECT id, ticker, filing_type, filing_date, section, chunk_text,
               1 - (embedding <=> %s::vector) AS sim
        FROM   filing_chunks
        WHERE  embedding IS NOT NULL {filter_sql}
        ORDER  BY sim DESC
        LIMIT  %s
    ),
    dense AS (
        SELECT *, ROW_NUMBER() OVER (ORDER BY sim DESC) AS rk
        FROM   dense_raw
    ),
    bm25_raw AS (
        SELECT id, ticker, filing_type, filing_date, section, chunk_text,
               ts_rank_cd(fts, q) AS bm25_score
        FROM   filing_chunks,
               websearch_to_tsquery('english', %s) AS q
        WHERE  fts @@ q {filter_sql}
        ORDER  BY bm25_score DESC
        LIMIT  %s
    ),
    bm25 AS (
        SELECT *, ROW_NUMBER() OVER (ORDER BY bm25_score DESC) AS rk
        FROM   bm25_raw
    ),
    fused AS (
        SELECT
            COALESCE(d.id,           b.id)           AS id,
            COALESCE(d.ticker,       b.ticker)       AS ticker,
            COALESCE(d.filing_type,  b.filing_type)  AS filing_type,
            COALESCE(d.filing_date,  b.filing_date)  AS filing_date,
            COALESCE(d.section,      b.section)      AS section,
            COALESCE(d.chunk_text,   b.chunk_text)   AS chunk_text,
            COALESCE(1.0 / (60.0 + d.rk), 0.0) +
            COALESCE(1.0 / (60.0 + b.rk), 0.0)      AS rrf_score
        FROM  dense d
        FULL OUTER JOIN bm25 b ON d.id = b.id
    )
    SELECT id, ticker, filing_type, filing_date, section, chunk_text, rrf_score
    FROM   fused
    ORDER  BY rrf_score DESC
    LIMIT  %s;
    """

    # params: vec, filter_params (dense), candidate_k, query, filter_params (bm25), candidate_k, top_k
    params = (
        [vec] + filter_params + [candidate_k,
        query] + filter_params + [candidate_k,
        top_k]
    )

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "ticker":      r[1],
            "filing_type": r[2],
            "filing_date": str(r[3]) if r[3] else None,
            "section":     r[4],
            "text":        r[5],
            "rrf_score":   round(float(r[6]), 6),
        }
        for r in rows
    ]


# ─── Tool 2: Stock Price Data ──────────────────────────────────────────────────
def get_stock_data(ticker: str, days: int = 30):
    """Fetch recent OHLCV stock prices for a ticker."""
    days = min(days, 365)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT date, open, high, low, close, volume
        FROM   stock_prices
        WHERE  ticker = %s
        ORDER  BY date DESC
        LIMIT  %s;
    """, (ticker.upper(), days))

    rows = cur.fetchall()

    # Summary stats
    cur.execute("""
        SELECT
            MIN(close)                                          AS low_52w,
            MAX(close)                                          AS high_52w,
            ROUND(AVG(close)::numeric, 2)                       AS avg_close,
            (SELECT close FROM stock_prices
             WHERE ticker = %s ORDER BY date DESC LIMIT 1)      AS latest_close,
            (SELECT date  FROM stock_prices
             WHERE ticker = %s ORDER BY date DESC LIMIT 1)      AS latest_date
        FROM stock_prices
        WHERE ticker = %s
          AND date >= CURRENT_DATE - INTERVAL '252 days';
    """, (ticker.upper(), ticker.upper(), ticker.upper()))

    stats = cur.fetchone()
    cur.close()
    conn.close()

    prices = [
        {
            "date":   str(r[0]),
            "open":   float(r[1]) if r[1] else None,
            "high":   float(r[2]) if r[2] else None,
            "low":    float(r[3]) if r[3] else None,
            "close":  float(r[4]) if r[4] else None,
            "volume": int(r[5])   if r[5] else None
        }
        for r in rows
    ]

    return {
        "ticker":       ticker.upper(),
        "latest_close": float(stats[3]) if stats[3] else None,
        "latest_date":  str(stats[4])   if stats[4] else None,
        "52w_low":      float(stats[0]) if stats[0] else None,
        "52w_high":     float(stats[1]) if stats[1] else None,
        "avg_close":    float(stats[2]) if stats[2] else None,
        "prices":       prices
    }


# ─── Tool 3: News + Sentiment ──────────────────────────────────────────────────
def get_news_sentiment(ticker: str, limit: int = 10):
    """Fetch recent news articles with FinBERT sentiment for a ticker."""
    limit = min(limit, 20)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT headline, source, published_at, sentiment_label, sentiment_score, url
        FROM   news_articles
        WHERE  ticker = %s
        ORDER  BY published_at DESC NULLS LAST
        LIMIT  %s;
    """, (ticker.upper(), limit))

    rows = cur.fetchall()

    # Aggregate sentiment
    cur.execute("""
        SELECT sentiment_label, COUNT(*) AS cnt
        FROM   news_articles
        WHERE  ticker = %s AND sentiment_label IS NOT NULL
        GROUP  BY sentiment_label
        ORDER  BY cnt DESC;
    """, (ticker.upper(),))

    sentiment_summary = {r[0]: r[1] for r in cur.fetchall()}
    cur.close()
    conn.close()

    articles = [
        {
            "headline":        r[0],
            "source":          r[1],
            "published_at":    str(r[2]) if r[2] else None,
            "sentiment_label": r[3],
            "sentiment_score": float(r[4]) if r[4] else None,
            "url":             r[5]
        }
        for r in rows
    ]

    return {
        "ticker":            ticker.upper(),
        "sentiment_summary": sentiment_summary,
        "articles":          articles
    }


# ─── Tool 4: Structured Financials (XBRL) ─────────────────────────────────────
def get_financials(ticker: str, period_type: str = "annual", limit: int = 5):
    """
    Fetch structured financial data from the EDGAR XBRL financials table.
    Covers income statement, balance sheet, cash flow, and computed margins.
    """
    ticker      = ticker.upper()
    limit       = min(limit, 20)
    period_type = period_type if period_type in ("annual", "quarterly") else "annual"

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT period_end, fiscal_year, fiscal_quarter,
               revenue, gross_profit, operating_income, net_income,
               eps_basic, eps_diluted, rd_expense,
               total_assets, total_liabilities, stockholders_equity,
               cash, long_term_debt,
               operating_cash_flow, capex, free_cash_flow,
               gross_margin, operating_margin, net_margin,
               form_type
        FROM   financials
        WHERE  ticker = %s AND period_type = %s
        ORDER  BY period_end DESC
        LIMIT  %s;
    """, (ticker, period_type, limit))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    cols = [
        "period_end", "fiscal_year", "fiscal_quarter",
        "revenue", "gross_profit", "operating_income", "net_income",
        "eps_basic", "eps_diluted", "rd_expense",
        "total_assets", "total_liabilities", "stockholders_equity",
        "cash", "long_term_debt",
        "operating_cash_flow", "capex", "free_cash_flow",
        "gross_margin", "operating_margin", "net_margin",
        "form_type",
    ]

    periods = []
    for row in rows:
        p = {}
        for col, val in zip(cols, row):
            if val is None:
                p[col] = None
            elif hasattr(val, "year"):        # date object
                p[col] = str(val)
            elif hasattr(val, "__float__"):   # Decimal / float
                p[col] = float(val)
            else:
                p[col] = val
        periods.append(p)

    return {
        "ticker":      ticker,
        "period_type": period_type,
        "count":       len(periods),
        "periods":     periods,
    }


# ─── Tool 5: Company Info ─────────────────────────────────────────────────────
def get_company_info(ticker: str):
    """Fetch company metadata: name, SIC, exchange, fiscal year end, state of incorporation."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT ticker, cik, name, sic_code, sic_description,
               state_of_incorporation, fiscal_year_end, exchange, category, ein
        FROM   company_info
        WHERE  ticker = %s;
    """, (ticker.upper(),))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return {"error": f"No company info found for {ticker.upper()}"}

    cols = ["ticker", "cik", "name", "sic_code", "sic_description",
            "state_of_incorporation", "fiscal_year_end", "exchange", "category", "ein"]
    return dict(zip(cols, row))


# ─── Tool 6: Earnings Call Transcripts ────────────────────────────────────────
def get_earnings_call(ticker: str, fiscal_year: int = None, fiscal_quarter: str = None, limit: int = 3):
    """Fetch earnings call transcripts from the earnings_calls table."""
    ticker = ticker.upper()
    limit  = min(limit, 5)

    conditions = ["ticker = %s"]
    params     = [ticker]

    if fiscal_year:
        conditions.append("fiscal_year = %s")
        params.append(fiscal_year)
    if fiscal_quarter:
        conditions.append("fiscal_quarter = %s")
        params.append(fiscal_quarter.upper())

    where = " AND ".join(conditions)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(f"""
        SELECT ticker, fiscal_year, fiscal_quarter, filing_date,
               accession_num, chunk_count, full_text
        FROM   earnings_calls
        WHERE  {where}
        ORDER  BY filing_date DESC NULLS LAST
        LIMIT  %s;
    """, params + [limit])

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return {"error": f"No earnings calls found for {ticker}"}

    return {
        "ticker": ticker,
        "count":  len(rows),
        "calls": [
            {
                "fiscal_year":    r[1],
                "fiscal_quarter": r[2],
                "filing_date":    str(r[3]) if r[3] else None,
                "accession_num":  r[4],
                "chunk_count":    r[5],
                "transcript":     r[6],
            }
            for r in rows
        ],
    }


# ─── Tool 7: Filing Price Impact (Temporal Correlation) ───────────────────────
def get_filing_price_impact(ticker: str, filing_date: str, window_days: int = 10):
    """
    Fetch stock price in a window around a filing date to measure market reaction.
    Returns pre-filing price, filing-day close, post-filing price, and % returns.
    """
    window_days = min(window_days, 30)
    ticker      = ticker.upper()

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT date, open, close, volume
        FROM   stock_prices
        WHERE  ticker = %s
          AND  date BETWEEN %s::date - (%s || ' days')::interval
                        AND %s::date + (%s || ' days')::interval
        ORDER  BY date;
    """, (ticker, filing_date, window_days, filing_date, window_days))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return {"error": f"No price data for {ticker} around {filing_date}"}

    prices = [
        {
            "date":   str(r[0]),
            "open":   float(r[1]) if r[1] else None,
            "close":  float(r[2]) if r[2] else None,
            "volume": int(r[3])   if r[3] else None,
        }
        for r in rows
    ]

    before = [p for p in prices if p["date"] <= filing_date]
    after  = [p for p in prices if p["date"] >  filing_date]

    filing_day_close = before[-1]["close"] if before else None
    pre_close        = before[0]["close"]  if before else None
    post_close       = after[-1]["close"]  if after  else None

    pre_return  = (
        round((filing_day_close - pre_close) / pre_close * 100, 2)
        if (filing_day_close and pre_close) else None
    )
    post_return = (
        round((post_close - filing_day_close) / filing_day_close * 100, 2)
        if (post_close and filing_day_close) else None
    )

    return {
        "ticker":              ticker,
        "filing_date":         filing_date,
        "window_days":         window_days,
        "pre_filing_close":    pre_close,
        "filing_day_close":    filing_day_close,
        "post_filing_close":   post_close,
        "pre_filing_return_pct":  pre_return,
        "post_filing_return_pct": post_return,
        "prices":              prices,
    }


# ─── Tool 5: Risk Drift Detection ─────────────────────────────────────────────
def get_risk_drift(ticker: str, num_filings: int = 3):
    """
    Compare risk factor sections across consecutive 10-K filings for a ticker.
    For each adjacent pair of filings:
      - Computes cosine similarity between the average risk-section embeddings
        (low similarity = high drift = risk language changed significantly)
      - Identifies the top-3 most novel risk chunks in the newer filing
        (chunks most dissimilar to the older filing's average risk embedding)
    Returns drift scores and representative emerging-risk text excerpts.
    """
    num_filings = min(num_filings, 5)
    ticker      = ticker.upper()

    conn = get_conn()
    cur  = conn.cursor()

    # Step 1: Get last N distinct 10-K filing dates (chronological order)
    cur.execute("""
        SELECT DISTINCT filing_date
        FROM   filing_chunks
        WHERE  ticker = %s AND filing_type = '10-K' AND filing_date IS NOT NULL
        ORDER  BY filing_date DESC
        LIMIT  %s;
    """, (ticker, num_filings))

    filing_dates = sorted([row[0] for row in cur.fetchall()])

    if len(filing_dates) < 2:
        cur.close()
        conn.close()
        return {
            "error": (
                f"Need at least 2 10-K filings for {ticker} to compare risk drift. "
                f"Found {len(filing_dates)}."
            )
        }

    results = []

    for i in range(len(filing_dates) - 1):
        date_old = filing_dates[i]
        date_new = filing_dates[i + 1]

        # ── Similarity between average risk embeddings ─────────────────────────
        cur.execute("""
            WITH old_avg AS (
                SELECT AVG(embedding) AS avg_emb
                FROM   filing_chunks
                WHERE  ticker = %s AND filing_date = %s
                  AND  section ILIKE '%%risk%%' AND embedding IS NOT NULL
            ),
            new_avg AS (
                SELECT AVG(embedding) AS avg_emb
                FROM   filing_chunks
                WHERE  ticker = %s AND filing_date = %s
                  AND  section ILIKE '%%risk%%' AND embedding IS NOT NULL
            )
            SELECT 1 - (o.avg_emb <=> n.avg_emb) AS similarity
            FROM   old_avg o, new_avg n
            WHERE  o.avg_emb IS NOT NULL AND n.avg_emb IS NOT NULL;
        """, (ticker, date_old, ticker, date_new))

        sim_row    = cur.fetchone()
        similarity = round(float(sim_row[0]), 4) if sim_row else None

        # ── Most novel chunks in new filing ────────────────────────────────────
        # Novel = least similar to the OLD filing's average risk embedding.
        # This surfaces language that is genuinely new rather than rephrased.
        cur.execute("""
            WITH old_avg AS (
                SELECT AVG(embedding) AS avg_emb
                FROM   filing_chunks
                WHERE  ticker = %s AND filing_date = %s
                  AND  section ILIKE '%%risk%%' AND embedding IS NOT NULL
            )
            SELECT   nc.chunk_text,
                     1 - (nc.embedding <=> o.avg_emb) AS sim_to_old
            FROM     filing_chunks nc, old_avg o
            WHERE    nc.ticker      = %s
              AND    nc.filing_date = %s
              AND    nc.section     ILIKE '%%risk%%'
              AND    nc.embedding   IS NOT NULL
            ORDER BY sim_to_old ASC
            LIMIT    3;
        """, (ticker, date_old, ticker, date_new))

        emerging = [
            {
                "text":          row[0][:400],
                "novelty_score": round(1 - float(row[1]), 4),
            }
            for row in cur.fetchall()
        ]

        results.append({
            "from_filing":    str(date_old),
            "to_filing":      str(date_new),
            "risk_similarity": similarity,
            "drift_score":    round(1 - similarity, 4) if similarity is not None else None,
            "emerging_risks": emerging,
        })

    cur.close()
    conn.close()

    return {
        "ticker":           ticker,
        "filings_compared": len(results),
        "interpretation": (
            "drift_score near 0 = risk language stable; "
            "drift_score near 1 = risk language significantly changed"
        ),
        "drift_analysis":   results,
    }
