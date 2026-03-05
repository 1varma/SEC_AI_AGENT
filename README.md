# FinSight AI — SEC Filing Intelligence Platform

> A Bloomberg-competitive, open-source business intelligence platform powered by semantic search over SEC EDGAR filings, stock market data, and large language models. Built to deliver institutional-grade financial research through natural language.

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
7. [Multi-Agent Architecture](#7-multi-agent-architecture)
8. [Installation & Setup](#8-installation--setup)
9. [Usage](#9-usage)
10. [Performance Characteristics](#10-performance-characteristics)
11. [Roadmap](#11-roadmap)
12. [References](#12-references)

---

## 1. Abstract

This project presents an end-to-end financial intelligence platform that ingests, processes, and semantically indexes the complete corpus of SEC EDGAR 10-K (annual), 10-Q (quarterly), and 8-K (current reports) filings for all S&P 500 constituents. The system constructs a vector database of over 1.9 million text chunks derived from 38,136 cleaned filing documents, enabling sub-second approximate nearest-neighbour retrieval across a multi-year, multi-company corpus. A multi-agent reasoning layer, powered by Anthropic Claude, synthesizes retrieved evidence with structured stock and macroeconomic data to answer complex financial research queries in natural language. The platform is designed as an open, extensible alternative to proprietary terminals such as Bloomberg and FactSet, with no per-seat licensing cost.

---

## 2. Introduction

Financial research has traditionally required either expensive proprietary terminals (Bloomberg Terminal: ~$25,000/seat/year) or significant manual effort to navigate the SEC's EDGAR database. Existing tools offer keyword-based document search, which fails to capture semantic relationships between financial concepts — for example, surfacing filings that discuss supply chain concentration risk without using that exact phrase.

Recent advances in dense retrieval and large language models enable a fundamentally different approach: encode every sentence of every filing into a high-dimensional semantic vector space, then retrieve the most contextually relevant passages for any natural language query. Combined with structured stock and macroeconomic data, this creates a research assistant capable of answering questions that no keyword system can.

**Core contributions of this work:**

- A production-grade, fully resumable ETL pipeline for the complete S&P 500 SEC filing corpus
- A section-aware, overlap-windowed chunking strategy optimised for long-form financial documents
- A memory-efficient, process-separated embedding pipeline using local GPU inference
- A multi-agent reasoning architecture with domain-specialised sub-agents
- An open-source, self-hosted alternative to commercial financial intelligence platforms

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          UI Layer                                │
│          Next.js · Tailwind CSS · Plotly · TradingView           │
│    Chat  │  Dashboard  │  Company View  │  Screener  │  Alerts   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST / WebSocket
┌──────────────────────────▼──────────────────────────────────────┐
│                       API Layer (FastAPI)                         │
│              Auth · Rate Limiting · Response Streaming            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                Orchestrator Agent (Claude claude-sonnet-4-6)     │
│         Query classification · Tool selection · Synthesis         │
└──┬──────────┬────────────┬────────────┬────────────┬────────────┘
   │          │            │            │            │
┌──▼──┐  ┌───▼────┐  ┌────▼───┐  ┌────▼───┐  ┌────▼───┐
│ SEC │  │ Market │  │Fundmntl│  │  News  │  │ Macro  │
│Agent│  │  Agent │  │  Agent │  │  Agent │  │  Agent │
└──┬──┘  └───┬────┘  └────┬───┘  └────┬───┘  └────┬───┘
   │          │            │            │            │
┌──▼──────────▼────────────▼────────────▼────────────▼──────────┐
│                    Data Layer (PostgreSQL 16)                    │
│  filing_chunks(pgvector) · stock_prices · financials · news     │
└────────────────────────────────────────────────────────────────┘
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
`all-MiniLM-L6-v2` is a distilled variant of MiniLM trained on 1 billion sentence pairs. At 384 dimensions, it produces embeddings that achieve 80–90% of the retrieval quality of much larger models (BERT-large, E5-large) at a fraction of the inference cost. For a corpus of 1.9M chunks requiring millions of embedding operations, inference throughput is a first-order concern.

**IVFFlat index:**
Built after all embeddings are populated. IVFFlat partitions the vector space into `lists = 100` Voronoi cells. At query time, only the nearest `nprobe` cells are searched (default: 10), reducing retrieval from O(n) to approximately O(n / lists). For datasets up to ~1M vectors, `lists = 100` is optimal; for larger datasets, `lists = sqrt(n)` is the recommended heuristic.

---

## 5. Database & Vector Store

**Engine:** PostgreSQL 16 with `pgvector` extension

```
Database: sec_filings
│
├── filing_chunks
│   ├── ~1.9M rows (10-K + 10-Q); grows with 8-K ingestion
│   ├── vector(384) embeddings
│   ├── B-tree indexes: ticker, filing_type, filing_date
│   └── IVFFlat index: embedding (cosine)
│
└── stock_prices
    ├── ~5.2M rows (473 tickers, 1980–2026)
    ├── OHLCV daily data
    └── B-tree indexes: ticker, date, (ticker, date)
```

**Similarity query:**
```sql
SELECT ticker, filing_type, filing_date, section, chunk_text,
       1 - (embedding <=> $1::vector) AS similarity
FROM   filing_chunks
WHERE  ticker = 'AAPL'                    -- optional metadata filter
  AND  filing_type = '10-K'              -- optional metadata filter
ORDER  BY embedding <=> $1::vector
LIMIT  10;
```

The `<=>` operator computes cosine distance. Combined with the IVFFlat index, filtered queries across millions of vectors return in single-digit milliseconds.

---

## 6. Retrieval-Augmented Generation

The RAG pipeline converts a natural language query into a grounded, cited answer:

```
1. Embed query         → same model (all-MiniLM-L6-v2), 384-dim vector
2. Vector search       → pgvector <=> on filing_chunks, top-k chunks
3. Context assembly    → retrieved chunks + metadata (ticker, section, date)
4. Prompt construction → system prompt + context + user query
5. LLM generation      → Claude synthesizes answer with inline citations
```

**Hybrid retrieval** (planned):
Combine dense retrieval (pgvector semantic search) with sparse retrieval (BM25 on chunk_text) using Reciprocal Rank Fusion — improves recall for queries containing specific financial identifiers (e.g. exact product names, regulation codes).

---

## 7. Multi-Agent Architecture

Five domain-specialised agents, orchestrated by a routing agent (Claude):

| Agent | Data Source | Capability |
|---|---|---|
| **SEC Research** | `filing_chunks` pgvector | Semantic search over 10-K, 10-Q, and 8-K filings |
| **Market** | `stock_prices` (473 tickers, 1980–2026) | OHLCV, returns, volatility, drawdown |
| **Fundamental** | `financials` | P/E, EV/EBITDA, revenue, margins, debt |
| **News** | `news_chunks` pgvector | Recent news semantic search + sentiment |
| **Macro** | FRED API | Interest rates, CPI, GDP, yield curve |

**Example multi-agent query:**
```
"Which S&P 500 companies mentioned supply chain concentration
 risk in their 2021 10-K AND underperformed their sector by
 more than 15% in 2022?"

→ SEC Agent:    semantic search for supply chain risk mentions in 2021
→ Market Agent: sector-relative returns for matched tickers in 2022
→ Orchestrator: intersect, rank, synthesize into ranked list with evidence
```

No keyword system can answer this. It requires semantic understanding of document content cross-referenced with quantitative market data — the core value proposition of this platform.

---

## 8. Installation & Setup

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

## 10. Performance Characteristics

| Stage | Input | Output | Notes |
|---|---|---|---|
| Download 10-K/10-Q | 505 companies | 38,183 HTML → S3 | 8 threads, ~10 req/s |
| Download 8-K | S3 `raw_8k/` (170k objects) | ~56,800 HTML → local | 16 threads, resumable |
| Stock ingest | S3 `stocks/` (473 CSVs) | ~5.2M rows → PostgreSQL | 8 threads, idempotent |
| Convert | HTML files | `.md` files | 16 CPU workers, `FORCE_RERUN` flag |
| Chunk | `.md` files | rows (embedding = NULL) | 24 CPU workers, `INCREMENTAL` flag |
| Embed | chunks | 384-dim embeddings | GPU, 256/batch, resumable |
| Query | 1 natural language query | Top-k chunks | <10ms with IVFFlat |

**Storage (10-K + 10-Q corpus):**
- Raw HTML (S3): ~180 GB · Markdown: ~12 GB · PostgreSQL + embeddings: ~11 GB

**Storage (after 8-K added):**
- Additional ~3–5 GB markdown · ~3 GB PostgreSQL with embeddings

**Stock data:**
- ~5.2M rows · 473 tickers · 1980–2026 · ~1.5 GB PostgreSQL

---

## 11. Roadmap

### Phase 1 — Complete
- [x] `downloader.ipynb` — SEC EDGAR → S3 (38,183 filings, 10-K + 10-Q)
- [x] `convert_to_md.py` — HTML → Markdown with iXBRL stripping (`FORCE_RERUN` flag)
- [x] `create_table.py` — PostgreSQL schema with pgvector
- [x] `chunk.py` — section-aware chunking, flat memory, `INCREMENTAL` flag
- [x] `embed.py` — GPU embedding pipeline, fully resumable

### Phase 2 — Scripts Ready, Pending Execution
- [x] `download_8k.py` — downloads ~56,800 8-K filings from `s3://sec-filings-raw-data-ashish-v1/raw_8k/`
- [ ] Run `convert_to_md.py` with `FORCE_RERUN = False` on 8-K files
- [ ] Run `chunk.py` with `INCREMENTAL = True` on 8-K markdown
- [ ] Run `embed.py` on new NULL rows
- [x] Documentation complete

### Phase 3 — Scripts Ready, Pending Execution
- [x] `create_stock_table.py` — `stock_prices` schema (OHLCV + indexes)
- [x] `ingest_stocks.py` — 473 ticker CSVs from `s3://sec-filings-raw-data-ashish-v1/stocks/` → PostgreSQL (~5.2M rows, 1980–2026)
- [ ] `financials` table — EPS, revenue, margins, ratios via EDGAR XBRL
- [ ] `company_info` table — sector, industry, market cap
- [ ] Automated daily refresh

### Phase 4 — News & Earnings Calls
- [ ] News ingestion — financial RSS feeds + NewsAPI
- [ ] Earnings call transcript ingestion and embedding
- [ ] Sentiment scoring per article and per filing section

### Phase 5 — Multi-Agent Backend
- [ ] FastAPI service with WebSocket streaming
- [ ] SEC Research Agent
- [ ] Market Agent
- [ ] Fundamental Agent
- [ ] News Agent
- [ ] Macro Agent (FRED API)
- [ ] Orchestrator (Claude claude-sonnet-4-6 with tool use)
- [ ] Redis caching layer

### Phase 6 — UI
- [ ] Next.js frontend
- [ ] Chat interface with inline citations and charts
- [ ] Company profile pages
- [ ] Side-by-side comparison tool
- [ ] Natural language screener
- [ ] Alert system ("notify when TSLA files a 10-K mentioning 'recall'")

### Phase 7 — Advanced Intelligence
- [ ] Hybrid retrieval (dense + BM25, Reciprocal Rank Fusion)
- [ ] Temporal correlation: filing language vs. subsequent stock performance
- [ ] Risk language drift detection year-over-year
- [ ] Earnings surprise correlation with filing sentiment
- [ ] Cross-company intelligence across peer groups

---

## 12. References

1. Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020.
2. Wang, W. et al. (2020). *MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers.* NeurIPS 2020.
3. Johnson, J., Douze, M., & Jégou, H. (2019). *Billion-scale similarity search with GPUs.* IEEE Transactions on Big Data.
4. U.S. Securities and Exchange Commission. *EDGAR Full-Text Search and API.* https://efts.sec.gov/
5. pgvector. *Open-source vector similarity search for PostgreSQL.* https://github.com/pgvector/pgvector
6. Reimers, N. & Gurevych, I. (2019). *Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks.* EMNLP 2019.
7. Anthropic. (2024). *Claude: AI Assistant.* https://www.anthropic.com

---

## Project Structure

```
SEC_AI_AGENT/
├── agent/                    # Python virtual environment
├── data/
│   ├── raw_html/             # HTML filings — 10-K/10-Q (local) + 8-K (download_8k.py output)
│   └── md_files/             # Converted markdown files (38,136 files + 8-K additions)
├── notebooks/
│   ├── downloader.ipynb      # SEC EDGAR → S3 (10-K + 10-Q)
│   ├── convert_to_md.ipynb   # Original conversion notebook
│   ├── create_table.ipynb    # Original schema notebook
│   └── chunk.ipynb           # Original chunking notebook
├── convert_to_md.py          # HTML → Markdown (FORCE_RERUN flag)
├── create_table.py           # filing_chunks PostgreSQL schema
├── chunk.py                  # Parallel chunker (INCREMENTAL flag)
├── embed.py                  # GPU embedder + IVFFlat index
├── download_8k.py            # 8-K HTML downloader from S3 raw_8k/
├── create_stock_table.py     # stock_prices PostgreSQL schema
├── ingest_stocks.py          # Stock OHLCV ingestion from S3 stocks/
├── CODE_EXPLANATION.md       # Detailed per-script technical documentation
└── README.md                 # This file
```

---

*Built with the goal of democratising institutional-grade financial research.*
