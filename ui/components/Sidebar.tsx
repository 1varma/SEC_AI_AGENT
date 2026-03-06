"use client";

import type { ChatSession, ModelInfo } from "@/lib/api";

interface Props {
  open: boolean;
  sessions: ChatSession[];
  activeId: string;
  models: ModelInfo[];
  modelId: string;
  theme: "light" | "dark";
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  onModelChange: (id: string) => void;
  onThemeToggle: () => void;
  onToggle: () => void;
}

function SunIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="5" strokeWidth={2} />
      <path strokeLinecap="round" strokeWidth={2}
        d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  );
}

export default function Sidebar({
  open, sessions, activeId, models, modelId, theme,
  onSelectSession, onNewSession, onDeleteSession,
  onModelChange, onThemeToggle, onToggle,
}: Props) {
  return (
    <div
      className={`
        flex flex-col shrink-0 bg-white dark:bg-gray-900
        border-r border-gray-200 dark:border-gray-700
        transition-all duration-200 overflow-hidden
        ${open ? "w-64" : "w-0"}
      `}
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
        <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">
          FinSight AI
        </span>
        <button
          onClick={onToggle}
          className="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="Collapse sidebar"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7M18 19l-7-7 7-7" />
          </svg>
        </button>
      </div>

      {/* New Chat button */}
      <div className="px-3 pt-3 pb-2 shrink-0">
        <button
          onClick={onNewSession}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium
                     bg-blue-600 hover:bg-blue-700 text-white transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {sessions.length > 0 && (
          <p className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-600">
            Chats
          </p>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`
              group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer mb-0.5
              text-sm transition-colors
              ${s.id === activeId
                ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
              }
            `}
            onClick={() => onSelectSession(s.id)}
          >
            <svg className="w-3.5 h-3.5 shrink-0 text-gray-400 dark:text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
            <span className="flex-1 truncate text-xs">{s.name}</span>
            {sessions.length > 1 && (
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteSession(s.id); }}
                className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-all"
              >
                <TrashIcon />
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Model selector */}
      <div className="px-3 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0 space-y-3">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-600 mb-1.5">
            Model
          </label>
          <select
            value={modelId}
            onChange={(e) => onModelChange(e.target.value)}
            className="w-full text-xs border border-gray-200 dark:border-gray-700 rounded-lg px-2.5 py-2
                       bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200
                       focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                [{m.provider}] {m.name}
              </option>
            ))}
          </select>
          {models.find((m) => m.id === modelId) && (
            <p className="mt-1 text-xs text-gray-400 dark:text-gray-600">
              {models.find((m) => m.id === modelId)?.description}
            </p>
          )}
        </div>

        {/* Theme toggle */}
        <button
          onClick={onThemeToggle}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium
                     text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800
                     border border-gray-200 dark:border-gray-700 transition-colors"
        >
          {theme === "light" ? <MoonIcon /> : <SunIcon />}
          {theme === "light" ? "Switch to Dark mode" : "Switch to Light mode"}
        </button>
      </div>
    </div>
  );
}
