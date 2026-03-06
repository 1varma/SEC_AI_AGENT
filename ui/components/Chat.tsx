"use client";

import { useState, useRef, useEffect } from "react";
import { streamQuery, Source, HistoryMessage, Message, ChatSession } from "@/lib/api";
import SourcePanel from "./SourcePanel";
import StockChart from "./StockChart";
import SentimentChart from "./SentimentChart";
import DynamicChart from "./DynamicChart";
import type { ChartData } from "./DynamicChart";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// ─── Visualizations extracted from tool results ───────────────────────────────
function DataVisuals({ sources }: { sources: Source[] }) {
  const stockSource = sources.find((s) => s.tool === "get_stock_data");
  const newsSource  = sources.find((s) => s.tool === "get_news_sentiment");

  const chartSources = sources.filter((s) => s.tool === "render_chart");

  if (!stockSource && !newsSource && chartSources.length === 0) return null;

  const stockResult = stockSource?.result as {
    ticker: string;
    latest_close: number;
    latest_date: string;
    "52w_low": number;
    "52w_high": number;
    avg_close: number;
    prices: Array<{ date: string; close: number }>;
  } | undefined;

  const newsResult = newsSource?.result as {
    ticker: string;
    sentiment_summary: Record<string, number>;
  } | undefined;

  return (
    <div className="mt-3 grid gap-4 grid-cols-1 sm:grid-cols-2">
      {chartSources.map((src, i) => (
        <DynamicChart key={i} data={src.result as ChartData} />
      ))}
      {stockResult && stockResult.prices?.length > 0 && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs font-semibold text-gray-600 dark:text-gray-300">
              {stockResult.ticker} — Price Chart
            </p>
            <span className="text-xs text-gray-400 dark:text-gray-500">{stockResult.latest_date}</span>
          </div>
          <StockChart data={stockResult.prices} />
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            {[
              { label: "Current",  value: `$${stockResult.latest_close?.toFixed(2)}` },
              { label: "52W Low",  value: `$${stockResult["52w_low"]?.toFixed(2)}` },
              { label: "52W High", value: `$${stockResult["52w_high"]?.toFixed(2)}` },
            ].map(({ label, value }) => (
              <div key={label} className="bg-gray-50 dark:bg-gray-700 rounded-lg p-2">
                <p className="text-xs text-gray-400 dark:text-gray-500">{label}</p>
                <p className="text-sm font-semibold text-gray-800 dark:text-gray-100">{value}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {newsResult && Object.keys(newsResult.sentiment_summary).length > 0 && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm">
          <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 mb-1">
            {newsResult.ticker} — News Sentiment
          </p>
          <SentimentChart summary={newsResult.sentiment_summary} />
        </div>
      )}
    </div>
  );
}

// ─── Chat component ───────────────────────────────────────────────────────────
interface ChatProps {
  session: ChatSession;
  modelId: string;
  onUpdate: (id: string, partial: Partial<ChatSession>) => void;
}

export default function Chat({ session, modelId, onUpdate }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>(session.messages);
  const [history,  setHistory]  = useState<HistoryMessage[]>(session.history);
  const [input,    setInput]    = useState("");
  const [loading,  setLoading]  = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const query = input.trim();
    setInput("");

    const userMsg: Message = { role: "user", content: query };
    const placeholderMsg: Message = { role: "assistant", content: "", sources: [] };

    setMessages((prev) => [...prev, userMsg, placeholderMsg]);
    setLoading(true);

    let fullText = "";
    let sources: Source[] = [];
    let cached  = false;

    try {
      for await (const event of streamQuery(query, history, modelId)) {
        if (event.type === "text" && event.content) {
          fullText += event.content;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: fullText, sources };
            return updated;
          });
        } else if (event.type === "sources" && event.data) {
          sources = event.data;
        } else if (event.type === "cached") {
          cached = event.value ?? false;
        } else if (event.type === "done") {
          const finalMessages: Message[] = [];
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: fullText, sources, cached };
            finalMessages.push(...updated);
            return updated;
          });

          const newHistory: HistoryMessage[] = [
            ...history,
            { role: "user",      content: query    },
            { role: "assistant", content: fullText  },
          ];
          setHistory(newHistory);

          // Sync to parent — rename session on first message
          const isFirst = history.length === 0;
          onUpdate(session.id, {
            messages: finalMessages,
            history:  newHistory,
            ...(isFirst ? { name: query.slice(0, 45) } : {}),
          });
        } else if (event.type === "error") {
          fullText = `Error: ${event.message}`;
          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = { role: "assistant", content: fullText };
            return updated;
          });
        }
      }
    } catch {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: "Failed to connect to API. Make sure the FastAPI server is running on port 8000.",
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 dark:text-gray-400 mt-20">
            <p className="text-2xl font-semibold text-gray-700 dark:text-gray-200 mb-2">
              FinSight AI
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Bloomberg-grade financial intelligence powered by SEC filings,
              stock data, and news
            </p>
            <div className="mt-8 grid grid-cols-2 gap-3 max-w-xl mx-auto text-left">
              {[
                "What are Apple's revenue risks from their latest 10-K?",
                "Compare MSFT and GOOGL revenue growth over 5 years",
                "What is NVDA's current stock price and 52-week range?",
                "What is the recent news sentiment for TSLA?",
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="p-3 text-xs border border-gray-200 dark:border-gray-700 rounded-lg
                             hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20
                             text-gray-600 dark:text-gray-300 text-left transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-3xl w-full ${msg.role === "user" ? "ml-12" : "mr-4"}`}>
              {msg.role === "user" ? (
                <div className="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm ml-auto max-w-md">
                  {msg.content}
                </div>
              ) : (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-semibold text-blue-600">
                      FinSight AI
                    </span>
                    {msg.cached && (
                      <span className="text-xs bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400 px-2 py-0.5 rounded-full">
                        cached
                      </span>
                    )}
                  </div>
                  <div className="
                    bg-white dark:bg-gray-800
                    border border-gray-200 dark:border-gray-700
                    rounded-2xl rounded-tl-sm px-5 py-4 text-sm
                    text-gray-800 dark:text-gray-100
                    leading-relaxed shadow-sm
                    prose prose-sm max-w-none dark:prose-invert
                    prose-table:text-xs
                    prose-headings:font-semibold prose-headings:text-gray-800 dark:prose-headings:text-gray-100
                    prose-a:text-blue-600
                    prose-code:bg-gray-100 dark:prose-code:bg-gray-700 prose-code:px-1 prose-code:rounded
                  ">
                    {msg.content ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    ) : (
                      <span className="inline-flex gap-1">
                        <span className="animate-bounce">●</span>
                        <span className="animate-bounce [animation-delay:0.1s]">●</span>
                        <span className="animate-bounce [animation-delay:0.2s]">●</span>
                      </span>
                    )}
                  </div>
                  {msg.sources && msg.sources.length > 0 && (
                    <>
                      <DataVisuals sources={msg.sources} />
                      <SourcePanel sources={msg.sources} />
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-4 shrink-0">
        <form onSubmit={handleSubmit} className="flex gap-3 max-w-4xl mx-auto">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about any company, filing, stock price, or news..."
            className="
              flex-1 border border-gray-300 dark:border-gray-700 rounded-xl px-4 py-3 text-sm
              bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100
              placeholder-gray-400 dark:placeholder-gray-600
              focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
            "
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-blue-600 text-white px-6 py-3 rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Thinking..." : "Ask"}
          </button>
        </form>
      </div>
    </div>
  );
}
