import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar, Area, AreaChart, ComposedChart } from 'recharts';

const COLORS = ['#2196F3', '#FF5722', '#4CAF50', '#FF9800', '#9C27B0', '#00BCD4', '#E91E63', '#795548'];

export function TimeSeriesChart({ data, xKey = 'data_ponto', lines, height = 350, title }) {
  if (!data || data.length === 0) return <div style={{ color: '#999', padding: 20 }}>Sem dados para o periodo selecionado</div>;
  return (
    <div>
      {title && <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>{title}</div>}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ fontSize: 12 }} />
          <Legend />
          {lines.map((l, i) => (
            <Line key={l.dataKey} type="monotone" dataKey={l.dataKey} name={l.name || l.dataKey}
                  stroke={l.color || COLORS[i % COLORS.length]} strokeWidth={l.width || 1.5}
                  dot={false} yAxisId={l.yAxisId || 0} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BarChartPanel({ data, xKey, bars, height = 300, title }) {
  if (!data || data.length === 0) return <div style={{ color: '#999', padding: 20 }}>Sem dados</div>;
  return (
    <div>
      {title && <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>{title}</div>}
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ fontSize: 12 }} />
          <Legend />
          {bars.map((b, i) => (
            <Bar key={b.dataKey} dataKey={b.dataKey} name={b.name || b.dataKey}
                 fill={b.color || COLORS[i % COLORS.length]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function RiskGauge({ value, max = 5 }) {
  const colors = ['#4CAF50', '#8BC34A', '#FFC107', '#FF5722', '#D32F2F', '#B71C1C'];
  const pct = Math.min(value / max, 1);
  const color = colors[Math.min(Math.floor(value), colors.length - 1)];
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 36, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: '#888' }}>/ {max}</div>
      <div style={{ width: '100%', height: 6, background: '#e0e0e0', borderRadius: 3, marginTop: 6 }}>
        <div style={{ width: `${pct * 100}%`, height: 6, background: color, borderRadius: 3 }} />
      </div>
    </div>
  );
}

export { COLORS };
