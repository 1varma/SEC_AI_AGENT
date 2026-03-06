"use client";

import { useState } from "react";
import { Source } from "@/lib/api";

interface FilingResult {
  ticker: string;
  filing_type: string;
  filing_date: string | null;
  section: string;
  text: string;
  similarity: number;
}

interface StockResult {
  ticker: string;
  latest_close: number;
  latest_date: string;
  "52w_low": number;
  "52w_high": number;
  avg_close: number;
}

interface NewsResult {
  ticker: string;
  sentiment_summary: Record<string, number>;
  articles: Array<{
    headline: string;
    source: string;
    published_at: string | null;
    sentiment_label: string;
    sentiment_score: number;
    url: string;
  }>;
}

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400",
  negative: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-400",
  neutral:  "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
};

function FilingSource({ result }: { result: FilingResult[] }) {
  return (
    <div className="space-y-2">
      {result.map((r, i) => (
        <div key={i} className="border border-gray-100 dark:border-gray-700 rounded-lg p-3 bg-gray-50 dark:bg-gray-800">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold text-xs text-blue-700 dark:text-blue-400">{r.ticker}</span>
            <span className="text-xs bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-300 px-1.5 py-0.5 rounded">{r.filing_type}</span>
            {r.filing_date && <span className="text-xs text-gray-500 dark:text-gray-400">{r.filing_date}</span>}
            <span className="ml-auto text-xs text-gray-400 dark:text-gray-500">sim: {(r.similarity * 100).toFixed(1)}%</span>
          </div>
          <p className="text-xs text-gray-600 dark:text-gray-400 line-clamp-2">{r.text}</p>
        </div>
      ))}
    </div>
  );
}

function StockSource({ result }: { result: StockResult }) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {[
        { label: "Latest Close", value: `$${result.latest_close?.toFixed(2)}` },
        { label: "52W Low",      value: `$${result["52w_low"]?.toFixed(2)}` },
        { label: "52W High",     value: `$${result["52w_high"]?.toFixed(2)}` },
      ].map(({ label, value }) => (
        <div key={label} className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
          <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-100">{value}</p>
        </div>
      ))}
    </div>
  );
}

function NewsSource({ result }: { result: NewsResult }) {
  return (
    <div className="space-y-2">
      <div className="flex gap-2 mb-2 flex-wrap">
        {Object.entries(result.sentiment_summary).map(([label, count]) => (
          <span key={label} className={`text-xs px-2 py-1 rounded-full ${SENTIMENT_COLORS[label] ?? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400"}`}>
            {label}: {count}
          </span>
        ))}
      </div>
      {result.articles.slice(0, 3).map((a, i) => (
        <div key={i} className="border border-gray-100 dark:border-gray-700 rounded-lg p-3 bg-gray-50 dark:bg-gray-800">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs px-1.5 py-0.5 rounded ${SENTIMENT_COLORS[a.sentiment_label] ?? ""}`}>
              {a.sentiment_label}
            </span>
            <span className="text-xs text-gray-400 dark:text-gray-500">{a.source}</span>
          </div>
          <p className="text-xs text-gray-700 dark:text-gray-300 line-clamp-2">{a.headline}</p>
        </div>
      ))}
    </div>
  );
}

const TOOL_LABELS: Record<string, string> = {
  search_filings:     "SEC Filings",
  get_stock_data:     "Stock Data",
  get_news_sentiment: "News & Sentiment",
  render_chart:       "Chart",
};

export default function SourcePanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);

  if (!sources.length) return null;

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 flex items-center gap-1 transition-colors"
      >
        <span>{open ? "▼" : "▶"}</span>
        {sources.length} source{sources.length > 1 ? "s" : ""} used
      </button>

      {open && (
        <div className="mt-2 space-y-4">
          {sources.map((src, i) => (
            <div key={i} className="border border-gray-200 dark:border-gray-700 rounded-xl p-4 bg-white dark:bg-gray-900">
              <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 mb-2">
                {TOOL_LABELS[src.tool] ?? src.tool}
                {src.inputs && typeof src.inputs === "object" && "ticker" in src.inputs && (
                  <span className="ml-2 text-blue-600 dark:text-blue-400">
                    {String(src.inputs.ticker)}
                  </span>
                )}
              </p>
              {src.tool === "search_filings" && (
                <FilingSource result={src.result as FilingResult[]} />
              )}
              {src.tool === "get_stock_data" && (
                <StockSource result={src.result as StockResult} />
              )}
              {src.tool === "get_news_sentiment" && (
                <NewsSource result={src.result as NewsResult} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
