# FinSight AI — SEC Filing Intelligence Platform

> A Bloomberg-competitive, open-source financial intelligence platform powered by hybrid semantic search over 2.84 million SEC EDGAR filing chunks, structured XBRL financial data, real-time news sentiment, and earnings call transcripts — all synthesized by Claude via AWS Bedrock through a 9-tool agentic RAG architecture.

---

## Table of Contents

1. [Abstract](#1-abstract)
2. [Introduction](#2-introduction)
3. [System Architecture](#3-system-architecture)
4. [Data Pipeline](#4-data-pipeline)
   - 4.1 [SEC Filing Acquisition](#41-sec-filing-acquisition)
   - 4.2 [Document Preprocessing](#42-document-preprocessing)
   - 4.3 [Schema Design](#43-schema-design)
   - 4.4 [Text Chunking](#44-text-chunking)
   - 4.5 [Semantic Embedding](#45-semantic-embedding)
5. [Database & Vector Store](#5-database--vector-store)
6. [Retrieval-Augmented Generation](#6-retrieval-augmented-generation)
7. [Agentic Architecture](#7-agentic-architecture)
8. [Use Cases](#8-use-cases)
9. [Installation & Setup](#9-installation--setup)
10. [Usage](#10-usage)
11. [Performance Characteristics](#11-performance-characteristics)
12. [Roadmap](#12-roadmap)
13. [References](#13-references)

---

## 1. Abstract

This project presents a complete, production-grade financial intelligence platform that ingests, processes, and semantically indexes the full corpus of SEC EDGAR filings (10-K, 10-Q, 8-K) for all S&P 500 constituents, alongside structured XBRL financial data, historical stock prices, real-time news with FinBERT sentiment, and earnings call transcripts. The system constructs a hybrid retrieval engine over 2,841,255 text chunks — combining dense vector search (pgvector, all-MiniLM-L6-v2, 384-dim) with sparse BM25 full-text search (PostgreSQL tsvector + GIN), fused via Reciprocal Rank Fusion — enabling sub-second retrieval across a multi-year, multi-company corpus. An agentic reasoning layer, powered by Anthropic Claude via AWS Bedrock, orchestrates nine specialised tools to synthesize filing evidence with structured financial data, market prices, sentiment, and temporal analysis into grounded natural language answers. The platform is designed as an open, self-hosted alternative to proprietary terminals such as Bloomberg and FactSet, with no per-seat licensing cost.

---

## 2. Introduction

Financial research has traditionally required either expensive proprietary terminals (Bloomberg Terminal: ~$25,000/seat/year) or significant manual effort to navigate the SEC's EDGAR database. Existing tools offer keyword-based document search, which fails to capture semantic relationships between financial concepts — for example, surfacing filings that discuss supply chain concentration risk without using that exact phrase.

Recent advances in dense retrieval and large language models enable a fundamentally different approach: encode every sentence of every filing into a high-dimensional semantic vector space, then retrieve the most contextually relevant passages for any natural language query. Combined with structured stock and macroeconomic data, this creates a research assistant capable of answering questions that no keyword system can.

**Core contributions of this work:**

- A production-grade, fully resumable ETL pipeline covering 6 heterogeneous financial data sources
- A section-aware, overlap-windowed chunking strategy optimised for long-form financial documents
- A hybrid BM25 + dense retrieval engine with Reciprocal Rank Fusion — the first such system applied to the full SEC EDGAR corpus
- A memory-efficient, GPU-accelerated embedding pipeline (all-MiniLM-L6-v2, 2.84M chunks)
- A 9-tool agentic RAG system using Claude via AWS Bedrock with streaming SSE responses
- Temporal correlation analysis (filing language → stock price reaction) and risk drift detection
- Multi-model support: Claude Sonnet/Opus/Haiku, Amazon Nova, Google Gemma via Bedrock Converse API
- An open-source, self-hosted alternative to commercial financial intelligence platforms

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                              UI Layer                                 │
│              Next.js · TypeScript · Tailwind CSS · Geist              │
│   Chat (SSE streaming) · StockChart · SentimentChart · DynamicChart   │
│              SourcePanel · Sidebar · Multi-model selector             │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ REST + Server-Sent Events (SSE)
┌───────────────────────────────▼──────────────────────────────────────┐
│                        API Layer (FastAPI)                             │
│       /api/query (SSE stream) · /api/query/sync · /api/models         │
│              Redis cache (24h filings / 1h stocks / 30m news)         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│              Claude Agent (AWS Bedrock — Anthropic SDK)                │
│   Agentic tool-use loop · Streaming synthesis · Multi-model support   │
│   Models: Claude Sonnet 4.6 · Opus 4.6 · Haiku 4.5                   │
│            Amazon Nova 2 Lite · Google Gemma 3 27B (Converse API)     │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────────┘
   │      │      │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
search  get_   get_   get_   get_   get_   get_  get_  render
filings finan- company earn-  stock_ news_  filing risk_  chart
(hybrid cials  _info  ings   data  senti- _price drift
BM25+         call          ment  _impact
dense)
   │      │      │      │      │      │      │      │
┌──▼──────▼──────▼──────▼──────▼──────▼──────▼──────▼──────────────┐
│                    Data Layer (PostgreSQL 16 + pgvector)            │
│                                                                     │
│  filing_chunks   — 2,841,255 chunks · vector(384) · BM25 tsvector  │
│  financials      — XBRL income statement / balance sheet / CF       │
│  company_info    — name, SIC, exchange, fiscal year end             │
│  earnings_calls  — transcripts extracted from 8-K filings           │
│  stock_prices    — 4,095,806 rows · 473 tickers · 1962–2026        │
│  news_articles   — RSS headlines + FinBERT sentiment scores         │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Pipeline

The data pipeline is fully decoupled into independent, resumable stages. Each stage can be re-run independently without affecting upstream or downstream stages. Three SEC filing types are ingested — 10-K (annual), 10-Q (quarterly), and 8-K (current reports) — all through the same processing pipeline.

```
 SEC EDGAR (10-K + 10-Q)          AWS S3: raw_8k/               AWS S3: stocks/
         │                        (8-K HTML filings)            (473 ticker CSVs)
         ▼                                │                             │
  downloader.ipynb                  download_8k.py               ingest_stocks.py
  → S3: raw_html/                   → data/raw_html/             → stock_prices table
         │                                │
         └──────────────┬─────────────────┘
                        ▼
               convert_to_md.py ──────► data/md_files/
               (FORCE_RERUN=False        (.md files)
                skips existing)
                        │
                        ▼
               create_table.py ───────► PostgreSQL: filing_chunks schema
                        │
                        ▼
               chunk.py ──────────────► filing_chunks (text, embedding = NULL)
               (INCREMENTAL=True         ON CONFLICT DO NOTHING for top-ups)
                skips existing)
                        │
                        ▼
               embed.py ───────────────► filing_chunks (embeddings + IVFFlat index)
               (WHERE embedding           fully resumable)
                IS NULL)
```

### 4.1 SEC Filing Acquisition

**Scripts:** `downloader.ipynb` (10-K + 10-Q from EDGAR) · `download_8k.py` (8-K from S3)

**10-K + 10-Q — `downloader.ipynb`**

| Parameter | Value |
|---|---|
| Target companies | S&P 500 (505 tickers) |
| Filing types | 10-K (annual), 10-Q (quarterly) |
| Rate limit | 10 requests/second (SEC mandated) |
| Parallelism | 8 threads (ThreadPoolExecutor) |
| Storage | AWS S3 (`raw_html/TICKER/TICKER_TYPE_DATE.html`) |
| Result | 38,183 HTML files |

Key design: token-bucket `RateLimiter` enforces SEC's rate limit across all threads. S3 `head_object` existence check makes it fully idempotent.

**8-K — `download_8k.py`**

8-K is a current report filed within 4 business days of any material corporate event — the highest-signal source for time-sensitive intelligence.

| Event Type | Examples |
|---|---|
| Earnings | Quarterly results, guidance updates |
| Corporate actions | M&A announcements, divestitures, spin-offs |
| Leadership | CEO/CFO changes, board appointments |
| Legal & regulatory | Material litigation, SEC investigations, settlements |
| Financial | Credit rating changes, debt issuances, covenant breaches |
| Operational | Plant closures, product recalls, cybersecurity incidents |

| Parameter | Value |
|---|---|
| Source | `s3://sec-filings-raw-data-ashish-v1/raw_8k/` |
| Total S3 objects | 170,531 |
| Unique 8-K filings | ~56,800 |
| File selection | `primary-document.html` → `.txt` → any `.html/.htm` per filing folder |
| Output | `data/raw_html/TICKER/TICKER_8-K_ACCESSION.html` |
| Parallelism | 16 threads (I/O bound) |
| Resume | Skips files already on disk |

---

### 4.2 Document Preprocessing

**Script:** `convert_to_md.py`

Converts raw SEC HTML filings to clean plain-text markdown, removing HTML structure, JavaScript, CSS, and iXBRL/XBRL financial taxonomy metadata.

| Parameter | Value |
|---|---|
| Workers | 16 CPU processes |
| File size limit | 20 MB (larger files skipped as malformed) |
| Min output length | 200 characters |
| Batch size | 2,000 files per pool instance |
| Result | 38,136 clean `.md` files (10-K + 10-Q); 8-K files appended in Phase 2 |

**`FORCE_RERUN` flag:**
```python
FORCE_RERUN = False  # skip already-converted files (set when adding 8-K on top of existing)
FORCE_RERUN = True   # re-convert everything from scratch (default for first run)
```
When adding 8-K files to an existing corpus, set `FORCE_RERUN = False` — the script checks if a `.md` output already exists and is clean before skipping, so 38k already-converted files are untouched.

**iXBRL stripping:**
Modern SEC filings (2017+) embed XBRL taxonomy data in `<ix:header>` and `<ix:hidden>` blocks. These contain thousands of machine-readable dimension entries that produce unusable text when extracted naively. The stripper uses `str.find()` boundary detection rather than regex to avoid catastrophic backtracking on multi-megabyte files.

**Junk detection (`is_junk`):**
Three-stage filter eliminates XBRL data that escapes tag-level removal:
1. XBRL namespace pattern matching in first 1,000 characters
2. Average word length check (XBRL identifiers average >20 characters per word)
3. English character ratio threshold (<15% English words = junk)

**Section header detection:**
Identifies SEC standard section headers (`Item 1.`, `PART I`, `RISK FACTORS` etc.) and promotes them to markdown `##` headings, preserving document structure for downstream section-aware chunking.

---

### 4.3 Schema Design

**Script:** `create_table.py`

```sql
CREATE TABLE filing_chunks (
    id           SERIAL PRIMARY KEY,
    ticker       VARCHAR(10)  NOT NULL,
    filing_type  VARCHAR(10)  NOT NULL,      -- '10-K', '10-Q', or '8-K'
    filing_date  DATE,
    section      TEXT,                        -- e.g. 'Risk Factors'
    chunk_index  INTEGER,                     -- position within section
    chunk_text   TEXT         NOT NULL,
    embedding    vector(384),                 -- NULL until embed.py runs
    source_file  TEXT,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_ticker      ON filing_chunks(ticker);
CREATE INDEX idx_filing_type ON filing_chunks(filing_type);
CREATE INDEX idx_filing_date ON filing_chunks(filing_date);
-- IVFFlat vector index created by embed.py after bulk population
```

The `embedding` column is `NULL` at insert time and populated in a separate pass by `embed.py`. This decoupling eliminates the memory bottleneck of holding all chunk texts and all embedding arrays simultaneously (which would require 5–8 GB RAM for the full corpus).

---

### 4.4 Text Chunking

**Script:** `chunk.py`

Splits each document into overlapping word-window chunks, inserting text rows into PostgreSQL immediately after each file batch to maintain a flat memory profile throughout.

| Parameter | Value |
|---|---|
| Window size | 1,024 words |
| Overlap | 200 words |
| Min chunk length | 50 characters |
| CPU workers | 24 (multiprocessing.Pool) |
| File batch size | 2,000 files |
| Insert batch size | 500 rows (execute_values) |

**Section-aware chunking:**
Documents are first split by markdown headers (`#`, `##`, `###`) into named sections. Each section is chunked independently, and the section name is stored alongside every chunk. This enables metadata-filtered retrieval (e.g. retrieve only from "Risk Factors" sections) and improves embedding quality — a model encoding a chunk labelled "Risk Factors" produces a more discriminative vector than one encoding an unmarked mid-document chunk.

**Memory management:**
`chunk.py` maintains flat memory by processing files in batches of 2,000, inserting each batch into PostgreSQL immediately, then explicitly freeing the batch with `del` and `gc.collect()` before proceeding. Peak RAM usage is proportional to one batch, not the entire corpus.

**Why multiprocessing, not threads:**
Chunking is CPU-bound (regex, string splitting, I/O). Python's GIL prevents true parallelism with threads for CPU-bound work. `multiprocessing.Pool` with `maxtasksperchild=20` provides true parallelism and bounds per-worker memory growth.

**`INCREMENTAL` flag:**
```python
INCREMENTAL = False  # TRUNCATE table and rechunk everything (default, first run)
INCREMENTAL = True   # skip files already in DB, append only new chunks (use for 8-K top-ups)
```
When `INCREMENTAL = True`, the script queries `SELECT DISTINCT source_file FROM filing_chunks` at startup and skips any file already present — existing 10-K/10-Q chunks are completely untouched.

---

### 4.5 Semantic Embedding

**Script:** `embed.py`

Streams un-embedded rows from PostgreSQL, generates 384-dimensional sentence embeddings on GPU, and updates rows in place. Builds the IVFFlat approximate nearest-neighbour index upon completion.

| Parameter | Value |
|---|---|
| Model | `all-MiniLM-L6-v2` (sentence-transformers) |
| Embedding dimensions | 384 |
| Batch size | 256 chunks per GPU call |
| Device | CUDA |
| Index type | IVFFlat (cosine distance) |
| IVFFlat lists | 100 |

**Streaming architecture:**
```python
while True:
    rows = SELECT id, chunk_text WHERE embedding IS NULL LIMIT 256
    if not rows: break
    embeddings = model.encode(texts)           # GPU
    UPDATE filing_chunks SET embedding = ...   # per-batch commit
```
At no point are more than 256 embedding vectors in RAM simultaneously. If the process is interrupted at any point, restarting resumes from the last uncommitted batch — `WHERE embedding IS NULL` acts as a natural checkpoint.

**Model selection rationale:**
`all-MiniLM-L6-v2` is a distilled variant of MiniLM trained on 1 billion sentence pairs. At 384 dimensions, it produces embeddings that achieve 80–90% of the retrieval quality of much larger models (BERT-large, E5-large) at a fraction of the inference cost. For a corpus of 2,841,255 chunks requiring millions of embedding operations, inference throughput is a first-order concern.

**IVFFlat index:**
Built after all embeddings are populated. IVFFlat partitions the vector space into `lists = 100` Voronoi cells. At query time, only the nearest `nprobe` cells are searched (default: 10), reducing retrieval from O(n) to approximately O(n / lists). For datasets up to ~1M vectors, `lists = 100` is optimal; for larger datasets, `lists = sqrt(n)` is the recommended heuristic.

---

## 5. Database & Vector Store

**Engine:** PostgreSQL 16 with `pgvector` extension

```
Database: sec_filings
│
├── filing_chunks        — 2,841,255 rows
│   ├── vector(384) embeddings (all-MiniLM-L6-v2)
│   ├── fts tsvector GENERATED ALWAYS AS STORED (BM25)
│   ├── B-tree indexes: ticker, filing_type, filing_date
│   ├── IVFFlat index: embedding (cosine, lists=100)
│   └── GIN index: fts (full-text search)
│
├── stock_prices         — 4,095,806 rows
│   ├── 473 tickers · 1962–2026 · OHLCV daily
│   └── B-tree indexes: ticker, date
│
├── financials           — EDGAR XBRL structured data
│   ├── Annual + quarterly periods per ticker
│   ├── Income: revenue, gross_profit, operating_income, net_income, EPS, R&D
│   ├── Balance: total_assets, liabilities, equity, cash, long_term_debt
│   ├── Cash flow: operating_cash_flow, capex, free_cash_flow
│   ├── Computed: gross_margin, operating_margin, net_margin
│   └── Indexes: ticker, period_end, (ticker, fiscal_year)
│
├── company_info         — 473 companies
│   ├── name, CIK, SIC code + description
│   ├── exchange, state_of_incorporation, fiscal_year_end
│   └── SEC filer category
│
├── news_articles        — RSS-ingested headlines
│   ├── 473 tickers · up to 50 articles/ticker/run
│   ├── FinBERT sentiment: positive / negative / neutral + score
│   └── Indexes: ticker, published_at, sentiment_label
│
└── earnings_calls       — transcripts extracted from 8-K chunks
    ├── Full text (management remarks + Q&A, up to 80K chars)
    ├── Fiscal year + quarter inferred from filing date
    └── Indexes: ticker, (ticker, fiscal_year)
```

**Hybrid retrieval query (BM25 + dense RRF):**
```sql
WITH dense_raw AS (
    SELECT id, ticker, filing_type, filing_date, section, chunk_text,
           1 - (embedding <=> $1::vector) AS sim
    FROM   filing_chunks WHERE embedding IS NOT NULL
    ORDER  BY sim DESC LIMIT 100
),
dense AS (SELECT *, ROW_NUMBER() OVER (ORDER BY sim DESC) AS rk FROM dense_raw),
bm25_raw AS (
    SELECT id, ticker, filing_type, filing_date, section, chunk_text,
           ts_rank_cd(fts, websearch_to_tsquery('english', $2)) AS bm25_score
    FROM   filing_chunks, websearch_to_tsquery('english', $2) AS q
    WHERE  fts @@ q ORDER BY bm25_score DESC LIMIT 100
),
bm25 AS (SELECT *, ROW_NUMBER() OVER (ORDER BY bm25_score DESC) AS rk FROM bm25_raw),
fused AS (
    SELECT COALESCE(d.id, b.id) AS id, ...,
           COALESCE(1.0/(60+d.rk), 0) + COALESCE(1.0/(60+b.rk), 0) AS rrf_score
    FROM dense d FULL OUTER JOIN bm25 b ON d.id = b.id
)
SELECT * FROM fused ORDER BY rrf_score DESC LIMIT 10;
```

---

## 6. Retrieval-Augmented Generation

FinSight uses an **agentic RAG** pattern — Claude autonomously decides which tools to call, in what order, and how many times, before synthesizing a final answer:

```
User query
    │
    ▼
Claude (AWS Bedrock) — decides which tools to call
    │
    ├── search_filings()       → Hybrid BM25 + dense retrieval (pgvector)
    ├── get_financials()       → XBRL structured numbers (exact revenue, margins)
    ├── get_company_info()     → Company metadata (SIC, exchange, fiscal year)
    ├── get_earnings_call()    → Full earnings transcript from 8-K
    ├── get_stock_data()       → OHLCV price history + 52w stats
    ├── get_news_sentiment()   → FinBERT-scored headlines
    ├── get_filing_price_impact() → Stock reaction around a filing date
    ├── get_risk_drift()       → Risk factor change detection across 10-Ks
    └── render_chart()         → Interactive chart rendered in UI
    │
    ▼
Tool results returned as context to Claude
    │
    ▼
Claude streams final synthesized answer (SSE) with citations
```

**Key design decisions:**
- **Retrieval is local** — all 9 tools query local PostgreSQL. Bedrock is used only for generation/orchestration.
- **Claude controls the loop** — no hardcoded retrieval pipeline. Claude decides whether to call 1 tool or 5 based on the question.
- **Two agent loops** — Anthropic SDK for Claude models; AWS Converse API for Amazon Nova and Google Gemma (graceful fallback if model doesn't support tools).
- **Redis caching** — responses cached with smart TTLs: 24h for filing queries, 1h for stock data, 30m for news.

---

## 7. Agentic Architecture

A single Claude agent orchestrates 9 specialised tools across 6 data sources. Claude autonomously chains tool calls — calling `get_financials` for numbers, then `search_filings` for context, then `render_chart` for visualisation — without any hardcoded pipeline.

### The 9 Tools

| Tool | Data Source | What it answers |
|---|---|---|
| `search_filings` | `filing_chunks` (2.84M, hybrid BM25+dense) | Qualitative: strategy, risk language, disclosures, guidance |
| `get_financials` | `financials` (XBRL) | Exact numbers: revenue, margins, EPS, FCF, debt |
| `get_company_info` | `company_info` | What does this company do? What sector? |
| `get_earnings_call` | `earnings_calls` (from 8-K) | What did management say? What did analysts ask? |
| `get_stock_data` | `stock_prices` (4.09M rows) | Price history, 52-week high/low, OHLCV |
| `get_news_sentiment` | `news_articles` (FinBERT) | Current market sentiment around a ticker |
| `get_filing_price_impact` | `stock_prices` + filing date | How did the market react to a specific filing? |
| `get_risk_drift` | `filing_chunks` embeddings | How have risk factors changed year over year? |
| `render_chart` | (UI passthrough) | Bar, line, grouped bar, pie — rendered in browser |

### Multi-model Support

| Model | Provider | API path |
|---|---|---|
| Claude Sonnet 4.6 | Anthropic | Bedrock (Anthropic SDK) — default |
| Claude Opus 4.6 | Anthropic | Bedrock (Anthropic SDK) |
| Claude Haiku 4.5 | Anthropic | Bedrock (Anthropic SDK) |
| Amazon Nova 2 Lite | Amazon | Bedrock Converse API |
| Google Gemma 3 27B | Google | Bedrock Converse API |

Non-Anthropic models use the Converse API with graceful fallback if the model doesn't support tool use.

### Example multi-tool query

```
"Compare Apple and Microsoft's free cash flow margins over 5 years
 and tell me what management said about capital allocation"

→ get_financials(AAPL, annual, 5)   → exact FCF, revenue, margins
→ get_financials(MSFT, annual, 5)   → exact FCF, revenue, margins
→ render_chart(grouped_bar, ...)    → side-by-side FCF margin chart
→ get_earnings_call(AAPL)           → management commentary on capital return
→ get_earnings_call(MSFT)           → management commentary on capital return
→ Claude synthesizes: numbers + chart + qualitative context
```

---

## 8. Use Cases

FinSight answers questions that no keyword search or spreadsheet can. Below are real queries that demonstrate the platform's breadth.

### Competitive Intelligence
> "What are the gross margins, operating margins, and R&D spend as a percentage of revenue for Salesforce, HubSpot, and Workday over the last 3 years?"

*Tools used: `get_financials` × 3 + `render_chart` (grouped bar)*

---

> "Which S&P 500 companies mentioned supply chain concentration risk in their 2021 10-K and underperformed their sector by more than 15% in 2022?"

*Tools used: `search_filings` + `get_stock_data` × N*

---

### Executive Intelligence
> "What did Nvidia's CEO say about data center demand and AI infrastructure investment in their last three earnings calls?"

*Tools used: `get_earnings_call` × 3 + `search_filings`*

---

> "Before any enterprise sales call: what are Microsoft's top 5 strategic priorities for 2024 based on their 10-K and latest earnings call?"

*Tools used: `search_filings` + `get_earnings_call` + `get_company_info`*

---

### Financial Benchmarking
> "Show me Apple's free cash flow trend over 5 years and compare their net margin to Microsoft and Google. What does management say about capital allocation?"

*Tools used: `get_financials` × 3 + `render_chart` + `get_earnings_call` × 3*

---

### Risk Intelligence
> "What new risks did Meta disclose in their 2024 10-K that they didn't mention in 2022? How much has their risk language changed?"

*Tools used: `get_risk_drift` + `search_filings`*

---

> "What are the most common reasons tech companies cite for missing revenue guidance in their 8-K filings?"

*Tools used: `search_filings` (filing_type=8-K)*

---

### Market Reaction Analysis
> "How did Tesla's stock react in the 10 days after their last 10-K filing? What in the filing might have caused it?"

*Tools used: `get_filing_price_impact` + `search_filings` + `get_stock_data`*

---

### Sector Trends
> "Which sectors saw the biggest increase in AI-related risk disclosures between 2022 and 2024? Where is disruption happening fastest?"

*Tools used: `search_filings` (broad query, no ticker filter)*

---

### Investor Preparation
> "What do high-growth SaaS companies say about their path to profitability and how they communicate burn rate to investors? Give me benchmarks."

*Tools used: `search_filings` + `get_financials` (multiple tickers)*

---

## 9. Installation & Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 16 with `pgvector` extension
- CUDA-compatible GPU (for embedding)
- AWS credentials (for S3 access)

### Environment

```bash
cd ~/Desktop/SEC_AI_AGENT
source agent/bin/activate
```

### Dependencies

```bash
pip install edgar boto3 pandas requests selectolax tqdm \
            psycopg2-binary pgvector sentence-transformers \
            torch numpy langchain langchain-anthropic \
            langchain-community fastapi uvicorn redis
```

### PostgreSQL Setup

```sql
CREATE DATABASE sec_filings;
\c sec_filings
CREATE EXTENSION vector;
```

### Environment Variables

```bash
export ANTHROPIC_API_KEY="your-key"
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-key"
export AWS_DEFAULT_REGION="us-east-1"
```

---

## 9. Usage

### Full pipeline — first run (10-K + 10-Q)

```bash
# Step 1 — Download 10-K + 10-Q from SEC EDGAR → S3
jupyter nbconvert --to notebook --execute notebooks/downloader.ipynb

# Step 2 — Convert HTML → Markdown (FORCE_RERUN = True by default)
python convert_to_md.py

# Step 3 — Create filing_chunks schema
python create_table.py

# Step 4 — Chunk and insert (INCREMENTAL = False by default)
python chunk.py

# Step 5 — Embed and build IVFFlat index
python embed.py
```

### Add 8-K filings (incremental top-up)

```bash
# Step 1 — Download 8-K HTML from S3 → data/raw_html/
python download_8k.py

# Step 2 — Convert only new 8-K files (set FORCE_RERUN = False first)
python convert_to_md.py

# Step 3 — Chunk only new files (set INCREMENTAL = True first)
python chunk.py

# Step 4 — Embed new NULL rows (no changes needed)
python embed.py
```

### Ingest stock data

```bash
# Step 1 — Create stock_prices schema
python create_stock_table.py

# Step 2 — Download 473 ticker CSVs from S3 and insert
python ingest_stocks.py
```

### Phase 7 — Hybrid search + new data tables

```bash
# BM25 full-text search (run once — adds tsvector column + GIN index to filing_chunks)
python add_hybrid_search.py

# XBRL structured financials
python create_financials_table.py
python ingest_xbrl.py               # ~2 min, 473 EDGAR API calls

# Company metadata
python create_company_table.py
python ingest_company_info.py       # ~2 min, 473 EDGAR API calls

# Earnings call transcripts (extracted from existing 8-K chunks — no network needed)
python create_earnings_table.py
python ingest_earnings.py

# Incremental stock price refresh
python refresh_stocks.py
```

### Running the API and UI

```bash
# Start FastAPI backend
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Start Next.js UI (separate terminal)
cd ui && npm run dev
```

### Daily Refresh (Optional — for production use)

> **Note for university project:** This step is optional and only needed if you want the data to stay current automatically. For a demo or submission, just run `daily_refresh.py` manually once before presenting.

`daily_refresh.py` chains three jobs in order:
1. **Stock prices** — incremental yfinance download from last stored date to today
2. **News ingestion** — RSS feeds for all 473 tickers (50 articles/ticker max)
3. **Sentiment scoring** — FinBERT GPU pass over any unscored articles

**To run manually:**
```bash
cd /home/ashish-varma-j/Desktop/SEC_AI_AGENT
agent/bin/python daily_refresh.py
```

**To automate with cron (Linux/macOS):**
```bash
# Open crontab editor
crontab -e

# Add this line — runs every weekday at 5:00 PM (after US market close)
0 17 * * 1-5 cd /home/ashish-varma-j/Desktop/SEC_AI_AGENT && agent/bin/python daily_refresh.py >> /tmp/finsight_refresh.log 2>&1

# Check logs
tail -f /tmp/finsight_refresh.log
```

**To verify cron is installed:**
```bash
crontab -l
```

---

### Query the vector store directly

```python
import psycopg2
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
query = "supply chain concentration risk in semiconductor manufacturing"
vec   = model.encode(query).tolist()

conn = psycopg2.connect(database="sec_filings", user="ashish", password="ashish")
cur  = conn.cursor()
cur.execute("""
    SELECT ticker, filing_type, filing_date, section, chunk_text,
           1 - (embedding <=> %s::vector) AS similarity
    FROM   filing_chunks
    ORDER  BY embedding <=> %s::vector
    LIMIT  10;
""", (vec, vec))

for row in cur.fetchall():
    print(f"[{row[2]}] {row[0]} {row[1]} | {row[3]}")
    print(f"Similarity: {row[5]:.4f}")
    print(row[4][:300])
    print()
```

---

## 10. Usage

(See Section 9 for installation. Run `source agent/bin/activate` before all commands.)

### Full pipeline — first run

```bash
# Phase 1–2: Filing pipeline
jupyter nbconvert --to notebook --execute notebooks/downloader.ipynb
python convert_to_md.py && python create_table.py && python chunk.py && python embed.py
python download_8k.py   # then re-run convert_to_md, chunk, embed with flags set

# Phase 3: Market data
python create_stock_table.py && python ingest_stocks.py
python create_financials_table.py && python ingest_xbrl.py
python create_company_table.py && python ingest_company_info.py

# Phase 4: News & earnings
python create_news_table.py && python news_ingest.py && python sentiment.py
python create_earnings_table.py && python ingest_earnings.py

# Phase 7: Hybrid search
python add_hybrid_search.py && python refresh_stocks.py
```

### Start the platform

```bash
# Terminal 1 — FastAPI backend
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Next.js UI
cd ui && npm run dev
```

Open `http://localhost:3000` and start querying.

---

## 11. Performance Characteristics

| Stage | Input | Output | Notes |
|---|---|---|---|
| Download 10-K/10-Q | 505 companies | 38,183 HTML → S3 | 8 threads, ~10 req/s |
| Download 8-K | S3 `raw_8k/` (170k objects) | 138,030 HTML → local | 16 threads, resumable |
| Stock ingest | S3 `stocks/` (473 CSVs) | 4,095,806 rows | idempotent, ON CONFLICT DO NOTHING |
| XBRL ingest | EDGAR Company Facts API | financials table | ~473 API calls, 0.15s delay |
| Company info | EDGAR Submissions API | company_info table | ~473 API calls, 0.15s delay |
| Convert | HTML files | `.md` files | 16 CPU workers, `FORCE_RERUN` flag |
| Chunk | `.md` files | rows (embedding=NULL) | 24 CPU workers, `INCREMENTAL` flag |
| Embed | 2,841,255 chunks | 384-dim embeddings | GPU (CUDA), 256/batch, resumable |
| Add BM25 | filing_chunks | tsvector + GIN index | One-time migration, ~few minutes |
| Query (hybrid) | 1 natural language query | Top-k chunks (RRF fused) | <15ms |
| Full agent response | 1 user question | Streamed answer + charts | 3–15s depending on tools called |

**Storage:**
- Raw HTML (S3): ~180 GB (10-K/10-Q) + ~8 GB (8-K)
- Markdown: ~12 GB · PostgreSQL (all tables + embeddings): ~15 GB
- Stock prices: 4.09M rows · ~1.5 GB

---

## 12. Roadmap

### Phase 1 — Complete
- [x] `downloader.ipynb` — SEC EDGAR → S3 (38,183 filings, 10-K + 10-Q)
- [x] `convert_to_md.py` — HTML → Markdown with iXBRL stripping
- [x] `create_table.py` — PostgreSQL schema with pgvector
- [x] `chunk.py` — section-aware chunking, flat memory, `INCREMENTAL` flag
- [x] `embed.py` — GPU embedding pipeline, fully resumable

### Phase 2 — Complete
- [x] `download_8k.py` — 8-K filings from S3 → local (138,030 files)
- [x] `convert_to_md.py` with `FORCE_RERUN = False` — 8-K HTML → Markdown
- [x] `chunk.py` with `INCREMENTAL = True` — 8-K chunks appended
- [x] `embed.py` — 2,841,255 total chunks, 100% embedded

### Phase 3 — Complete
- [x] `create_stock_table.py` — `stock_prices` schema
- [x] `ingest_stocks.py` — 473 tickers, 4,095,806 rows, 1962–2026
- [x] `create_financials_table.py` — XBRL financials schema
- [x] `ingest_xbrl.py` — EDGAR Company Facts API → structured financials
- [x] `create_company_table.py` — company metadata schema
- [x] `ingest_company_info.py` — EDGAR Submissions API → company_info

### Phase 4 — Complete
- [x] `create_news_table.py` — news_articles schema
- [x] `news_ingest.py` — RSS feed ingestion (473 tickers, 50 articles/ticker)
- [x] `sentiment.py` — FinBERT GPU sentiment scoring
- [x] `create_earnings_table.py` — earnings_calls schema
- [x] `ingest_earnings.py` — earnings call transcripts extracted from 8-K chunks

### Phase 5 — Complete
- [x] `api/main.py` — FastAPI with SSE streaming, `/api/query`, `/api/models`
- [x] `api/agents.py` — 9-tool agentic loop (Anthropic SDK + Converse API for multi-model)
- [x] `api/retrieval.py` — all tool implementations
- [x] `api/cache.py` — Redis cache with smart TTLs (24h / 1h / 30m)

### Phase 6 — Complete
- [x] `ui/` — Next.js + TypeScript + Tailwind CSS
- [x] Chat interface with SSE streaming
- [x] Interactive charts (DynamicChart, StockChart, SentimentChart)
- [x] Source panel, sidebar navigation

### Phase 7 — Complete
- [x] `add_hybrid_search.py` — BM25 tsvector + GIN index + RRF fusion
- [x] `get_filing_price_impact` tool — temporal correlation (filing → stock reaction)
- [x] `get_risk_drift` tool — risk factor drift detection across consecutive 10-Ks
- [x] `refresh_stocks.py` — incremental daily stock price update (yfinance)
- [x] `daily_refresh.py` — orchestrator for all daily refresh jobs

---

## 13. References

1. Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020.
2. Wang, W. et al. (2020). *MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers.* NeurIPS 2020.
3. Johnson, J., Douze, M., & Jégou, H. (2019). *Billion-scale similarity search with GPUs.* IEEE Transactions on Big Data.
4. U.S. Securities and Exchange Commission. *EDGAR Full-Text Search and API.* https://efts.sec.gov/
5. pgvector. *Open-source vector similarity search for PostgreSQL.* https://github.com/pgvector/pgvector
6. Reimers, N. & Gurevych, I. (2019). *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks.* EMNLP 2019.
7. Anthropic. (2024). *Claude: AI Assistant.* https://www.anthropic.com
8. Amazon Web Services. (2024). *Amazon Bedrock — Fully managed foundation models.* https://aws.amazon.com/bedrock/
9. U.S. Securities and Exchange Commission. *EDGAR XBRL Company Facts API.* https://data.sec.gov/api/xbrl/
10. Araci, D. (2019). *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models.* arXiv:1908.10063.

---

## Project Structure

```
SEC_AI_AGENT/
├── agent/                        # Python virtual environment
├── api/
│   ├── main.py                   # FastAPI app — /api/query (SSE), /api/models, /health
│   ├── agents.py                 # Agentic tool loop (Anthropic SDK + Converse API)
│   ├── retrieval.py              # All 9 tool implementations
│   └── cache.py                  # Redis cache with smart TTLs
├── ui/                           # Next.js frontend (TypeScript + Tailwind)
│   ├── app/                      # Next.js app router
│   ├── components/               # Chat, Sidebar, StockChart, SentimentChart, DynamicChart, SourcePanel
│   └── lib/api.ts                # SSE streaming API client
├── data/
│   ├── raw_html/                 # HTML filings (10-K/10-Q + 8-K)
│   └── md_files/                 # Converted markdown files
├── notebooks/
│   └── downloader.ipynb          # SEC EDGAR → S3 (10-K + 10-Q)
│
├── — Phase 1–2: Filing Pipeline ──────────────────────────────────────
├── convert_to_md.py              # HTML → Markdown (FORCE_RERUN flag)
├── create_table.py               # filing_chunks schema
├── chunk.py                      # Parallel chunker (INCREMENTAL flag)
├── embed.py                      # GPU embedder + IVFFlat index
├── download_8k.py                # 8-K downloader from S3
│
├── — Phase 3: Market Data ─────────────────────────────────────────────
├── create_stock_table.py         # stock_prices schema
├── ingest_stocks.py              # 473 ticker CSVs from S3 → PostgreSQL
├── create_financials_table.py    # financials schema (XBRL)
├── ingest_xbrl.py                # EDGAR Company Facts API → financials
├── create_company_table.py       # company_info schema
├── ingest_company_info.py        # EDGAR Submissions API → company_info
│
├── — Phase 4: News & Earnings ─────────────────────────────────────────
├── create_news_table.py          # news_articles schema
├── news_ingest.py                # RSS feed ingestion (473 tickers)
├── sentiment.py                  # FinBERT GPU sentiment scoring
├── create_earnings_table.py      # earnings_calls schema
├── ingest_earnings.py            # Earnings transcripts from 8-K chunks
│
├── — Phase 7: Hybrid Search & Refresh ─────────────────────────────────
├── add_hybrid_search.py          # BM25 tsvector + GIN index (run once)
├── refresh_stocks.py             # Incremental stock price update (yfinance)
├── daily_refresh.py              # Cron orchestrator (stocks + news + sentiment)
│
├── CODE_EXPLANATION.md           # Detailed per-script technical documentation
└── README.md                     # This file
```

---

*Built with the goal of democratising institutional-grade financial research.*
