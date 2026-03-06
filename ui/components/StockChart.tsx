"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface PricePoint {
  date: string;
  close: number;
}

interface Props {
  data: PricePoint[];
}

export default function StockChart({ data }: Props) {
  const sorted  = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const first   = sorted[0]?.close ?? 0;
  const last    = sorted[sorted.length - 1]?.close ?? 0;
  const change  = ((last - first) / first) * 100;
  const isUp    = change >= 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-2xl font-bold text-gray-800">${last.toFixed(2)}</span>
          <span className={`ml-2 text-sm font-medium ${isUp ? "text-green-600" : "text-red-600"}`}>
            {isUp ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%
          </span>
        </div>
        <span className="text-xs text-gray-400">{sorted.length} trading days</span>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={sorted}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tickFormatter={(v) => v.slice(5)}
            tick={{ fontSize: 10 }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 10 }}
            tickFormatter={(v) => `$${v.toFixed(0)}`}
            width={55}
          />
          <Tooltip
            formatter={(v: unknown) => [`$${Number(v).toFixed(2)}`, "Close"]}
            labelFormatter={(l: unknown) => `Date: ${l}`}
          />
          <ReferenceLine y={first} stroke="#94a3b8" strokeDasharray="4 4" />
          <Line
            type="monotone"
            dataKey="close"
            stroke={isUp ? "#16a34a" : "#dc2626"}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
