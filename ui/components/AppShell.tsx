"use client";

import { useState, useEffect, useCallback } from "react";
import Sidebar from "./Sidebar";
import Chat from "./Chat";
import { fetchModels } from "@/lib/api";
import type { ModelInfo, ChatSession } from "@/lib/api";

// Fallback list shown immediately — updated from backend on mount
const DEFAULT_MODELS: ModelInfo[] = [
  { id: "us.anthropic.claude-sonnet-4-6",          name: "Claude Sonnet 4.6",  provider: "Anthropic", description: "Balanced speed & intelligence (default)" },
  { id: "anthropic.claude-opus-4-6-v1",            name: "Claude Opus 4.6",    provider: "Anthropic", description: "Most capable, deepest reasoning" },
  { id: "anthropic.claude-haiku-4-5-20251001-v1:0",name: "Claude Haiku 4.5",   provider: "Anthropic", description: "Fastest, most cost-efficient" },
  { id: "amazon.nova-2-lite-v1:0",                 name: "Nova 2 Lite",        provider: "Amazon",    description: "Amazon's lightweight frontier model" },
  { id: "google.gemma-3-27b-it",                   name: "Gemma 3 27B",        provider: "Google",    description: "Google open-weight instruction model" },
];

let _sid = 0;
function newSession(): ChatSession {
  const id = `s${++_sid}`;
  return { id, name: "New Chat", messages: [], history: [] };
}

export default function AppShell() {
  const [{ sessions, activeId }, setAppState] = useState(() => {
    const s = newSession();
    return { sessions: [s], activeId: s.id };
  });

  const [theme, setTheme]     = useState<"light" | "dark">("light");
  const [models, setModels]   = useState<ModelInfo[]>(DEFAULT_MODELS);
  const [modelId, setModelId] = useState("us.anthropic.claude-sonnet-4-6");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Restore saved theme + fetch models on mount
  useEffect(() => {
    const saved = localStorage.getItem("finsight-theme") as "light" | "dark" | null;
    if (saved) setTheme(saved);
    fetchModels().then(setModels).catch(() => {});
  }, []);

  // Apply dark class to <html>
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem("finsight-theme", theme);
  }, [theme]);

  const activeSession = sessions.find((s) => s.id === activeId) ?? sessions[0];

  const setActiveId = (id: string) =>
    setAppState((p) => ({ ...p, activeId: id }));

  const setSessions = (fn: (s: ChatSession[]) => ChatSession[]) =>
    setAppState((p) => ({ ...p, sessions: fn(p.sessions) }));

  const createSession = () => {
    const s = newSession();
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
  };

  const deleteSession = (id: string) => {
    setAppState((p) => {
      const next = p.sessions.filter((s) => s.id !== id);
      if (next.length === 0) {
        const s = newSession();
        return { sessions: [s], activeId: s.id };
      }
      return {
        sessions: next,
        activeId: p.activeId === id ? next[0].id : p.activeId,
      };
    });
  };

  const updateSession = useCallback(
    (id: string, partial: Partial<ChatSession>) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, ...partial } : s))
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-gray-950 transition-colors duration-200">
      <Sidebar
        open={sidebarOpen}
        sessions={sessions}
        activeId={activeId}
        models={models}
        modelId={modelId}
        theme={theme}
        onSelectSession={setActiveId}
        onNewSession={createSession}
        onDeleteSession={deleteSession}
        onModelChange={setModelId}
        onThemeToggle={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
        onToggle={() => setSidebarOpen((o) => !o)}
      />

      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 px-4 py-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-1.5 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                title="Open sidebar"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
            )}
            <span className="text-lg font-bold text-blue-600">FinSight</span>
            <span className="text-xs text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-gray-700 px-2 py-0.5 rounded-full">
              AI
            </span>
          </div>
          <span className="text-xs text-gray-400 dark:text-gray-600 hidden sm:block">
            2.8M SEC chunks · 473 tickers · Real-time sentiment
          </span>
        </header>

        {activeSession && (
          <Chat
            key={activeSession.id}
            session={activeSession}
            modelId={modelId}
            onUpdate={updateSession}
          />
        )}
      </div>
    </div>
  );
}
