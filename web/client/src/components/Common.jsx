import React, { useState, useEffect } from 'react';
import api from '../api';

export function useApi(url, params = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(url, { params })
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch((e) => { if (!cancelled) setError(e.response?.data?.error || e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [url, JSON.stringify(params)]);

  return { data, loading, error };
}

export function Card({ title, children, style = {} }) {
  return (
    <div style={{ background: '#fff', borderRadius: 8, padding: 20, boxShadow: '0 1px 4px rgba(0,0,0,0.08)', ...style }}>
      {title && <div style={{ fontSize: 14, fontWeight: 600, color: '#333', marginBottom: 12 }}>{title}</div>}
      {children}
    </div>
  );
}

export function StatCard({ label, value, color = '#2196F3', suffix = '' }) {
  return (
    <div style={{ background: '#fff', borderRadius: 8, padding: 16, boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color }}>{value}{suffix}</div>
    </div>
  );
}

export function Spinner() {
  return <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>A carregar...</div>;
}

export function ErrorMsg({ error }) {
  return <div style={{ padding: 20, background: '#ffebee', color: '#c62828', borderRadius: 6, margin: 16 }}>{error}</div>;
}

export function StationSelect({ value, onChange }) {
  const { data, loading } = useApi('/ah/stations');
  if (loading) return <select disabled><option>A carregar...</option></select>;
  return (
    <select value={value || ''} onChange={(e) => onChange(e.target.value)}
      style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }}>
      <option value="">Todas as estacoes</option>
      {(data || []).map((s) => (
        <option key={s.estacao_sk} value={s.estacao_sk}>{s.estacao_nome} ({s.sistema_origem})</option>
      ))}
    </select>
  );
}

export function DateRange({ start, end, onStartChange, onEndChange }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <input type="date" value={start || ''} onChange={(e) => onStartChange(e.target.value)}
        style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }} />
      <span style={{ color: '#999' }}>a</span>
      <input type="date" value={end || ''} onChange={(e) => onEndChange(e.target.value)}
        style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }} />
    </div>
  );
}

export function Table({ columns, data, style = {} }) {
  if (!data || data.length === 0) return <div style={{ color: '#999', padding: 16 }}>Sem dados</div>;
  return (
    <div style={{ overflowX: 'auto', ...style }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{ textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid #e0e0e0',
                                       color: '#555', fontWeight: 600, whiteSpace: 'nowrap' }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
              {columns.map((c) => (
                <td key={c.key} style={{ padding: '7px 10px', whiteSpace: 'nowrap' }}>
                  {c.render ? c.render(row[c.key], row) : (row[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
