import json
import boto3
from api.retrieval import (
    search_filings, get_stock_data, get_news_sentiment,
    get_financials, get_company_info, get_earnings_call,
    get_filing_price_impact, get_risk_drift,
)

# ─── Tool Definitions (Anthropic tool_use schema) ─────────────────────────────
TOOLS = [
    {
        "name": "search_filings",
        "description": (
            "Search SEC filings (10-K, 10-Q, 8-K) for relevant information using "
            "semantic similarity. Use this for questions about company financials, "
            "revenue, risks, strategy, earnings releases, and regulatory disclosures. "
            "Can filter by ticker and filing type."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query"
                },
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL). Omit to search all companies."
                },
                "filing_type": {
                    "type": "string",
                    "enum": ["10-K", "10-Q", "8-K"],
                    "description": "Type of SEC filing to filter by. Omit for all types."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return. Default 5, max 10.",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_stock_data",
        "description": (
            "Get historical stock price data (OHLCV) for a ticker. Use this for "
            "questions about price trends, returns, 52-week highs/lows, and "
            "recent market performance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                },
                "days": {
                    "type": "integer",
                    "description": "Number of recent trading days to fetch. Default 30, max 365.",
                    "default": 30
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_news_sentiment",
        "description": (
            "Get recent news articles and FinBERT sentiment scores for a ticker. "
            "Use this for current market sentiment, recent company news, and "
            "investor perception analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent articles to return. Default 10, max 20.",
                    "default": 10
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_financials",
        "description": (
            "Get structured financial data (income statement, balance sheet, cash flow) "
            "from EDGAR XBRL for a ticker. Returns revenue, gross profit, operating income, "
            "net income, EPS, R&D, assets, liabilities, equity, cash, debt, OCF, capex, FCF, "
            "and computed margins. Use this for precise quantitative financial questions — "
            "revenue figures, profit margins, EPS trends, leverage ratios, FCF analysis. "
            "Much more precise than searching filing text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                },
                "period_type": {
                    "type": "string",
                    "enum": ["annual", "quarterly"],
                    "description": "Annual (10-K) or quarterly (10-Q) periods. Default: annual.",
                    "default": "annual"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of periods to return (most recent first). Default 5, max 20.",
                    "default": 5
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_company_info",
        "description": (
            "Get company metadata for a ticker: full name, SIC code and industry, "
            "exchange, state of incorporation, fiscal year end date, and SEC filer category. "
            "Use this when the user asks about what a company does, what sector/industry "
            "it belongs to, or basic company facts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_earnings_call",
        "description": (
            "Fetch earnings call transcripts for a ticker. Returns the full transcript "
            "text including management remarks and Q&A, extracted from SEC 8-K filings. "
            "Use this for questions about management guidance, analyst questions, "
            "forward-looking statements, and qualitative commentary on results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Fiscal year to filter by (e.g. 2023). Omit for most recent."
                },
                "fiscal_quarter": {
                    "type": "string",
                    "enum": ["Q1", "Q2", "Q3", "Q4", "FY"],
                    "description": "Quarter to filter by. Omit for all quarters."
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of calls to return. Default 3, max 5.",
                    "default": 3
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "get_filing_price_impact",
        "description": (
            "Get stock price movement around a specific SEC filing date to measure "
            "market reaction. Returns price before, on, and after the filing date, "
            "plus % return for each window. Use this when asked how the market "
            "reacted to a specific filing (e.g. 'how did AAPL stock move after its "
            "2023 10-K?'). Pair with search_filings to correlate price reaction with "
            "filing content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                },
                "filing_date": {
                    "type": "string",
                    "description": "Filing date in YYYY-MM-DD format"
                },
                "window_days": {
                    "type": "integer",
                    "description": "Trading days before and after the filing to include. Default 10, max 30.",
                    "default": 10
                }
            },
            "required": ["ticker", "filing_date"]
        }
    },
    {
        "name": "get_risk_drift",
        "description": (
            "Detect how a company's risk factors have changed across consecutive 10-K "
            "filings using embedding similarity. Returns a drift score (0 = stable, "
            "1 = completely changed) for each adjacent filing pair, plus text excerpts "
            "of the most novel risk language in the newer filing. Use this for questions "
            "about evolving risks, newly disclosed threats, or risk factor trends over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g. AAPL)"
                },
                "num_filings": {
                    "type": "integer",
                    "description": "Number of recent 10-K filings to compare. Default 3, max 5.",
                    "default": 3
                }
            },
            "required": ["ticker"]
        }
    },
    {
        "name": "render_chart",
        "description": (
            "Render an interactive chart in the UI with any structured numerical data. "
            "Use this ALWAYS when you have data that tells a visual story — revenue by year, "
            "margin trends, growth rate comparisons, segment breakdowns, multi-company "
            "comparisons. Call this in addition to your text analysis, not instead of it. "
            "Supported chart types:\n"
            "- bar: single-series comparison across categories\n"
            "- grouped_bar: multi-company or multi-metric side-by-side comparison\n"
            "- line: time-series trends (revenue growth, margin over years)\n"
            "- pie: proportional breakdown (segment mix, cost structure)\n"
            "value_format options: 'dollars_billions' ($143.0B), 'percentage' (14.5%), 'number' (raw)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "grouped_bar", "line", "pie"],
                    "description": "Type of chart to render"
                },
                "title": {
                    "type": "string",
                    "description": "Chart title displayed above the chart"
                },
                "y_label": {
                    "type": "string",
                    "description": "Label for the Y-axis (e.g. 'Revenue ($B)', 'Growth (%)')"
                },
                "value_format": {
                    "type": "string",
                    "enum": ["dollars_billions", "percentage", "number"],
                    "description": "How to format values in tooltips and axis ticks",
                    "default": "number"
                },
                "series": {
                    "type": "array",
                    "description": "One or more data series. Each has a name and list of {label, value} points.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Series name shown in legend (e.g. 'MSFT', 'GOOGL')"
                            },
                            "color": {
                                "type": "string",
                                "description": "Hex color for this series (optional, e.g. '#2563eb')"
                            },
                            "data": {
                                "type": "array",
                                "description": "Data points for this series",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": "X-axis label (e.g. 'FY2020', 'Q1 2024')"
                                        },
                                        "value": {
                                            "type": "number",
                                            "description": "Numeric value for this data point"
                                        }
                                    },
                                    "required": ["label", "value"]
                                }
                            }
                        },
                        "required": ["name", "data"]
                    }
                }
            },
            "required": ["chart_type", "title", "series"]
        }
    },
]

# ─── Converse API tool format (boto3, for non-Anthropic models) ───────────────
CONVERSE_TOOLS = [
    {
        "toolSpec": {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": {"json": t["input_schema"]},
        }
    }
    for t in TOOLS
]

SYSTEM_PROMPT = """You are FinSight, a Bloomberg-grade financial intelligence assistant.

You have access to nine tools:
- search_filings: hybrid BM25 + semantic search over 2.8M SEC filing chunks (10-K, 10-Q, 8-K)
- get_financials: structured XBRL financial data — revenue, margins, EPS, balance sheet, cash flow (use for precise numbers)
- get_company_info: company metadata — name, SIC industry, exchange, fiscal year end, incorporation state
- get_earnings_call: earnings call transcripts extracted from 8-K filings (management remarks + Q&A)
- get_stock_data: historical OHLCV price data for 473 S&P 500 tickers (1962–2026)
- get_news_sentiment: recent news articles with FinBERT sentiment scores
- get_filing_price_impact: stock price movement before/after a specific filing date (temporal correlation)
- get_risk_drift: compare how a company's risk factors have evolved across consecutive 10-K filings
- render_chart: render an interactive chart in the UI with any structured data

Guidelines:
- Always cite your sources (filing type, date, ticker) when referencing SEC data
- Use multiple tools when the question requires it (e.g. financials + price + sentiment)
- Be precise and quantitative — use actual numbers from the data
- If data is unavailable or outdated, say so clearly
- Structure your answer clearly with key findings first
- Do NOT use emojis anywhere in your response
- Use plain markdown: headers, tables, bullet points, bold — no emoji characters
- The UI automatically renders interactive charts when you call get_stock_data or get_news_sentiment — do NOT say you cannot show visualizations. Tell the user the charts are displayed above your response.
- ALWAYS call render_chart when presenting revenue comparisons, growth trends, margin analysis, segment breakdowns, or any multi-year or multi-company numerical data. Do not just write a markdown table when a chart would be clearer — call render_chart AND write your analysis.
- For multi-company comparisons use chart_type "grouped_bar" or "line". For single-company trends over time use "bar" or "line". For segment/proportion breakdowns use "pie".
- For precise financial figures (revenue, margins, EPS), ALWAYS use get_financials first — it returns exact XBRL numbers. Fall back to search_filings only for qualitative context.
- For company background questions, use get_company_info first.
- For earnings call content (guidance, management tone, analyst Q&A), use get_earnings_call. Pair with get_financials for the actual numbers.
- For questions about how a filing affected a stock, use get_filing_price_impact alongside search_filings to correlate content with market reaction.
- For questions about evolving risks or risk trends over time, use get_risk_drift. A drift_score near 0 means stable risk language; near 1 means significantly changed.
"""


# ─── Tool execution (shared across both agent loops) ──────────────────────────
def execute_tool(name: str, inputs: dict) -> dict:
    if name == "search_filings":
        return search_filings(
            query=inputs["query"],
            ticker=inputs.get("ticker"),
            filing_type=inputs.get("filing_type"),
            top_k=inputs.get("top_k", 5)
        )
    elif name == "get_stock_data":
        return get_stock_data(
            ticker=inputs["ticker"],
            days=inputs.get("days", 30)
        )
    elif name == "get_news_sentiment":
        return get_news_sentiment(
            ticker=inputs["ticker"],
            limit=inputs.get("limit", 10)
        )
    elif name == "get_financials":
        return get_financials(
            ticker=inputs["ticker"],
            period_type=inputs.get("period_type", "annual"),
            limit=inputs.get("limit", 5)
        )
    elif name == "get_company_info":
        return get_company_info(ticker=inputs["ticker"])
    elif name == "get_earnings_call":
        return get_earnings_call(
            ticker=inputs["ticker"],
            fiscal_year=inputs.get("fiscal_year"),
            fiscal_quarter=inputs.get("fiscal_quarter"),
            limit=inputs.get("limit", 3)
        )
    elif name == "get_filing_price_impact":
        return get_filing_price_impact(
            ticker=inputs["ticker"],
            filing_date=inputs["filing_date"],
            window_days=inputs.get("window_days", 10)
        )
    elif name == "get_risk_drift":
        return get_risk_drift(
            ticker=inputs["ticker"],
            num_filings=inputs.get("num_filings", 3)
        )
    elif name == "render_chart":
        return inputs   # pass-through; UI renders it
    else:
        return {"error": f"Unknown tool: {name}"}


# ─── Helper ───────────────────────────────────────────────────────────────────
def is_anthropic_model(model_id: str) -> bool:
    return "anthropic" in model_id.lower()


# ─── Anthropic SDK agent loop ─────────────────────────────────────────────────
def run_agent_loop(client, model: str, user_query: str, history: list = []):
    """
    Agentic loop using the Anthropic SDK (AnthropicBedrock).
    Works for all models whose ID contains 'anthropic'.
    Returns (messages, sources, final_text).
    Messages end with the last user/tool_results turn so the caller
    can open a fresh streaming call for the final answer.
    """
    messages = history + [{"role": "user", "content": user_query}]
    sources  = []

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason != "tool_use":
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            return messages, sources, final_text

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)
                sources.append({"tool": block.name, "inputs": block.input, "result": result})
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result, default=str)
                })

        messages.append({"role": "user", "content": tool_results})


# ─── Converse API agent loop (boto3) ─────────────────────────────────────────
def run_converse_agent_loop(model: str, user_query: str,
                             history: list = [], region: str = "us-east-1"):
    """
    Agentic loop using AWS Bedrock Converse API (boto3).
    Works for non-Anthropic models: Amazon Nova, Google Gemma, etc.
    Returns (messages, sources, final_text) where messages are in Converse format.
    """
    boto_client = boto3.client("bedrock-runtime", region_name=region)

    # Convert simple text history → Converse message format
    messages = []
    for msg in history:
        content = msg["content"]
        messages.append({
            "role": msg["role"],
            "content": [{"text": content}] if isinstance(content, str) else content
        })
    messages.append({"role": "user", "content": [{"text": user_query}]})

    sources       = []
    supports_tools = True

    while True:
        call_kwargs = dict(
            modelId=model,
            messages=messages,
            system=[{"text": SYSTEM_PROMPT}],
        )
        if supports_tools:
            call_kwargs["toolConfig"] = {"tools": CONVERSE_TOOLS}

        try:
            response = boto_client.converse(**call_kwargs)
        except Exception as e:
            err = str(e).lower()
            if supports_tools and ("tool" in err or "unsupported" in err or "validationexception" in err):
                # Model doesn't support tool use — retry without tools
                supports_tools = False
                call_kwargs.pop("toolConfig", None)
                response = boto_client.converse(**call_kwargs)
            else:
                raise

        stop_reason     = response["stopReason"]
        output_message  = response["output"]["message"]

        if stop_reason != "tool_use":
            final_text = ""
            for block in output_message.get("content", []):
                if "text" in block:
                    final_text += block["text"]
            # Append assistant message so streaming call has full context
            messages.append(output_message)
            return messages, sources, final_text

        # Append assistant tool-use message
        messages.append(output_message)

        tool_results = []
        for block in output_message.get("content", []):
            if "toolUse" in block:
                tu     = block["toolUse"]
                result = execute_tool(tu["name"], tu["input"])
                sources.append({"tool": tu["name"], "inputs": tu["input"], "result": result})
                tool_results.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content":   [{"json": result}],
                    }
                })

        messages.append({"role": "user", "content": tool_results})
