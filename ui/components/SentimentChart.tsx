"use client";

import { PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer } from "recharts";

interface Props {
  summary: Record<string, number>;
}

const COLORS: Record<string, string> = {
  positive: "#16a34a",
  neutral:  "#94a3b8",
  negative: "#dc2626",
};

export default function SentimentChart({ summary }: Props) {
  const data = Object.entries(summary).map(([name, value]) => ({ name, value }));
  const total = data.reduce((s, d) => s + d.value, 0);

  // Dominant sentiment
  const dominant = data.sort((a, b) => b.value - a.value)[0];

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span
          className="text-sm font-semibold px-2 py-1 rounded-full"
          style={{
            backgroundColor: `${COLORS[dominant?.name] ?? "#94a3b8"}20`,
            color: COLORS[dominant?.name] ?? "#94a3b8",
          }}
        >
          {dominant?.name ?? "neutral"} ({((dominant?.value / total) * 100).toFixed(0)}%)
        </span>
        <span className="text-xs text-gray-400">{total} articles</span>
      </div>

      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={45}
            outerRadius={70}
            paddingAngle={3}
            dataKey="value"
          >
            {data.map((entry) => (
              <Cell key={entry.name} fill={COLORS[entry.name] ?? "#94a3b8"} />
            ))}
          </Pie>
          <Tooltip />
          <Legend iconType="circle" iconSize={8} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
