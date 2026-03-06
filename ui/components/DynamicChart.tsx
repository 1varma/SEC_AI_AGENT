"use client";

import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";

const PALETTE = [
  "#2563eb", // blue   — MSFT
  "#16a34a", // green  — GOOGL / AAPL
  "#dc2626", // red    — Amazon / TSLA
  "#d97706", // amber  — NVDA
  "#7c3aed", // violet — Meta
  "#0891b2", // cyan   — general
  "#be185d", // pink
  "#065f46", // dark green
];

export interface ChartSeries {
  name: string;
  color?: string;
  data: Array<{ label: string; value: number }>;
}

export interface ChartData {
  chart_type: "bar" | "grouped_bar" | "line" | "pie";
  title: string;
  y_label?: string;
  value_format?: "dollars_billions" | "percentage" | "number";
  series: ChartSeries[];
}

function formatValue(v: number, fmt?: string): string {
  if (fmt === "dollars_billions") return `$${v.toFixed(1)}B`;
  if (fmt === "percentage")       return `${v.toFixed(1)}%`;
  return String(v);
}

function tickFormatter(fmt?: string) {
  return (v: number) => {
    if (fmt === "dollars_billions") return `$${v}B`;
    if (fmt === "percentage")       return `${v}%`;
    return String(v);
  };
}

// Pivot series data into Recharts row format:
// [{label: "FY2020", MSFT: 143, GOOGL: 182}, ...]
function pivotData(series: ChartSeries[]): Record<string, string | number>[] {
  const seen = new Set<string>();
  const labels = series.flatMap((s) => s.data.map((d) => d.label)).filter((l) => {
    if (seen.has(l)) return false;
    seen.add(l);
    return true;
  });
  return labels.map((label) => {
    const row: Record<string, string | number> = { label };
    series.forEach((s) => {
      const pt = s.data.find((d) => d.label === label);
      row[s.name] = pt?.value ?? 0;
    });
    return row;
  });
}

export default function DynamicChart({ data }: { data: ChartData }) {
  const { chart_type, title, value_format, series } = data;
  const fmt    = value_format ?? "number";
  const rows   = pivotData(series);
  const isDark = typeof window !== "undefined" && document.documentElement.classList.contains("dark");
  const gridColor  = isDark ? "#374151" : "#e5e7eb";
  const tickStyle  = { fontSize: 10, fill: isDark ? "#9ca3af" : "#6b7280" };

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 shadow-sm">
      <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 mb-3">{title}</p>

      {/* ── Bar / Grouped Bar ───────────────────────────────────────────────── */}
      {(chart_type === "bar" || chart_type === "grouped_bar") && (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey="label" tick={tickStyle} />
            <YAxis tick={tickStyle} tickFormatter={tickFormatter(fmt)} width={60} />
            <Tooltip
              formatter={(v: unknown, name: string | undefined) => [
                formatValue(Number(v), fmt), name ?? ""
              ]}
            />
            {series.length > 1 && <Legend iconType="circle" iconSize={8} />}
            {series.map((s, i) => (
              <Bar
                key={s.name}
                dataKey={s.name}
                fill={s.color ?? PALETTE[i % PALETTE.length]}
                radius={[3, 3, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}

      {/* ── Line ────────────────────────────────────────────────────────────── */}
      {chart_type === "line" && (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis dataKey="label" tick={tickStyle} />
            <YAxis tick={tickStyle} tickFormatter={tickFormatter(fmt)} width={60} />
            <Tooltip
              formatter={(v: unknown, name: string | undefined) => [
                formatValue(Number(v), fmt), name ?? ""
              ]}
            />
            {series.length > 1 && <Legend iconType="circle" iconSize={8} />}
            {series.map((s, i) => (
              <Line
                key={s.name}
                type="monotone"
                dataKey={s.name}
                stroke={s.color ?? PALETTE[i % PALETTE.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* ── Pie ─────────────────────────────────────────────────────────────── */}
      {chart_type === "pie" && series[0] && (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={series[0].data.map((d) => ({ name: d.label, value: d.value }))}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={85}
              paddingAngle={3}
              label={({ name, percent }: { name?: string; percent?: number }) =>
                `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
              }
              labelLine={false}
            >
              {series[0].data.map((_, i) => (
                <Cell
                  key={i}
                  fill={series[0].data[i] && series[0].color
                    ? series[0].color
                    : PALETTE[i % PALETTE.length]
                  }
                />
              ))}
            </Pie>
            <Tooltip formatter={(v: unknown) => formatValue(Number(v), fmt)} />
            <Legend iconType="circle" iconSize={8} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
