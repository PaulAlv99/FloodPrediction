import React, { useState, useEffect } from 'react';
import api from '../../api';
import { Card, Spinner, StationSelect, DateRange, Table } from '../../components/Common';
import { TimeSeriesChart } from '../../components/Charts';
import StationMap from '../../components/StationMap';

function today() { return new Date().toISOString().slice(0, 10); }
function daysAgo(n) { return new Date(Date.now() - n * 86400000).toISOString().slice(0, 10); }

function PrecipitationPanel() {
  const [station, setStation] = useState('');
  const [start, setStart] = useState(daysAgo(30));
  const [end, setEnd] = useState(today());
  const [gran, setGran] = useState('day');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.get('/ah/precipitation', { params: { station_sk: station || undefined, start, end, granularity: gran } })
      .then((r) => setData(r.data)).catch(() => setData([])).finally(() => setLoading(false));
  }, [station, start, end, gran]);

  const chartData = (data || []).map(d => ({
    data_ponto: String(d.data_ponto).slice(0, 10),
    sum_valor: d.sum_valor,
    avg_valor: d.avg_valor,
    max_valor: d.max_valor,
  }));

  return (
    <Card title="Precipitacao">
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <StationSelect value={station} onChange={setStation} />
        <DateRange start={start} end={end} onStartChange={setStart} onEndChange={setEnd} />
        <select value={gran} onChange={(e) => setGran(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }}>
          <option value="day">Dia</option><option value="month">Mes</option>
        </select>
      </div>
      {loading ? <Spinner /> : <TimeSeriesChart data={chartData} xKey="data_ponto"
        lines={[
          { dataKey: 'sum_valor', name: 'Precip. Total (mm)', color: '#2196F3' },
          { dataKey: 'max_valor', name: 'Max (mm)', color: '#FF5722' },
        ]} height={350} />}
    </Card>
  );
}

function LevelStationSelect({ value, onChange }) {
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/ah/level-stations').then(r => setStations(r.data)).finally(() => setLoading(false));
  }, []);
  if (loading) return <span>A carregar estacoes...</span>;
  return (
    <select value={value || ''} onChange={(e) => onChange(e.target.value)}
      style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13, minWidth: 250 }}>
      <option value="">Selecione estacao</option>
      {stations.map(s => (
        <option key={s.estacao_sk} value={s.estacao_sk}>{s.estacao_nome} ({s.sistema_origem})</option>
      ))}
    </select>
  );
}

function LevelsPanel() {
  const [station, setStation] = useState('229');
  const [start, setStart] = useState(daysAgo(90));
  const [end, setEnd] = useState(today());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!station) return;
    setLoading(true);
    api.get('/ah/levels', { params: { station_sk: station, start, end, granularity: 'day' } })
      .then((r) => setData(r.data)).catch(() => setData([])).finally(() => setLoading(false));
  }, [station, start, end]);

  if (!station) return <Card title="Niveis e Caudais"><div style={{ color: '#888' }}>Selecione uma estacao com dados de nivel/caudal</div></Card>;

  const paramCodes = [...new Set((data || []).map(d => d.parametro_codigo))];
  const lines = paramCodes.map((c, i) => ({
    dataKey: 'avg_valor',
    name: c === '1843' ? 'Nivel Inst. (m)' : c === '354895424' ? 'Cota (m)' : 'Caudal (m3/s)',
    color: ['#2196F3', '#FF5722', '#4CAF50'][i % 3],
  }));

  return (
    <Card title="Niveis e Caudais">
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <LevelStationSelect value={station} onChange={setStation} />
        <DateRange start={start} end={end} onStartChange={setStart} onEndChange={setEnd} />
      </div>
      {loading ? <Spinner /> : <TimeSeriesChart data={data || []} xKey="data_ponto" lines={lines} height={350} />}
    </Card>
  );
}

function PercentilesPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/ah/percentiles').then(r => setData(r.data)).catch(() => setData([])).finally(() => setLoading(false));
  }, []);

  const columns = [
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'target_parametro', label: 'Parametro' },
    { key: 'p50', label: 'P50', render: v => v != null ? v.toFixed(3) : '—' },
    { key: 'p75', label: 'P75', render: v => v != null ? v.toFixed(3) : '—' },
    { key: 'p90', label: 'P90', render: v => v != null ? v.toFixed(3) : '—' },
    { key: 'p95', label: 'P95', render: v => v != null ? v.toFixed(3) : '—' },
    { key: 'p99', label: 'P99', render: v => v != null ? v.toFixed(3) : '—' },
    { key: 'max_hist', label: 'Max', render: v => v != null ? v.toFixed(3) : '—' },
  ];

  return (
    <Card title="Percentis Historicos">
      {loading ? <Spinner /> : <>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{(data || []).length} registos</div>
        <Table columns={columns} data={data} />
      </>}
    </Card>
  );
}

function FloodEventsPanel() {
  const [year, setYear] = useState('');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/ah/flood-events', { params: { year: year || undefined } })
      .then(r => setData(r.data)).finally(() => setLoading(false));
  }, [year]);

  const columns = [
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'event_start', label: 'Inicio', render: v => v?.slice(0, 16) },
    { key: 'duration_hours', label: 'Duracao (h)', render: v => v?.toFixed(1) },
    { key: 'peak_value', label: 'Pico (m)', render: v => v?.toFixed(3) },
    { key: 'rise_rate', label: 'Taxa Subida', render: v => v?.toFixed(4) },
    { key: 'severidade', label: 'Severidade', render: (v) => {
      const c = v === 'Grave' ? '#D32F2F' : v === 'Moderado' ? '#FF9800' : '#4CAF50';
      return <span style={{ color: c, fontWeight: 600 }}>{v}</span>;
    }},
  ];

  return (
    <Card title="Catalogo de Eventos de Cheia">
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 13, marginRight: 8 }}>Ano:</label>
        <input type="number" value={year} onChange={(e) => setYear(e.target.value)} placeholder="Todos"
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', width: 100, fontSize: 13 }} />
      </div>
      {loading ? <Spinner /> : <>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{data.length} eventos encontrados</div>
        <Table columns={columns} data={data} />
      </>}
    </Card>
  );
}

function MapPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/ah/map').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <Card title="Mapa de Estacoes e Risco">
      {loading ? <Spinner /> : <StationMap stations={data} valueKey="nivel_risco"
        labelFn={(s) => {
          const parts = [s.estacao_nome];
          if (s.nivel_inst_atual != null) parts.push(`Nivel: ${s.nivel_inst_atual.toFixed(2)} m`);
          if (s.precip_accum_24h != null) parts.push(`Precip 24h: ${s.precip_accum_24h.toFixed(1)} mm`);
          if (s.categoria_risco) parts.push(`Risco: ${s.categoria_risco}`);
          return parts.join(' | ');
        }}
        colorFn={(s) => {
          const v = s.nivel_risco || 0;
          const colors = { 1: '#4CAF50', 2: '#8BC34A', 3: '#FFC107', 4: '#FF5722', 5: '#D32F2F' };
          return colors[v] || '#2196F3';
        }} />}
    </Card>
  );
}

function ReservoirsPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/ah/reservoirs').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  const columns = [
    { key: 'estacao_nome', label: 'Albufeira' },
    { key: 'cota_atual', label: 'Nivel Atual (m)', render: v => v != null ? parseFloat(v).toFixed(3) : '—' },
    { key: 'ultima_leitura', label: 'Ultima Leitura', render: v => v ? new Date(v).toLocaleString('pt-PT') : '—' },
  ];

  return (
    <Card title="Niveis de Albufeiras / Barragens">
      {loading ? <Spinner /> : <>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{data.length} albufeiras</div>
        <Table columns={columns} data={data} />
      </>}
    </Card>
  );
}

function ExportPanel() {
  const [station, setStation] = useState('');
  const [start, setStart] = useState(daysAgo(30));
  const [end, setEnd] = useState(today());
  const [downloading, setDownloading] = useState(false);
  const [msg, setMsg] = useState('');

  const handleExport = (format) => {
    if (!station) return;
    setDownloading(true);
    setMsg('');
    const config = { params: { station_sk: station, start, end, format } };
    if (format === 'csv') config.responseType = 'blob';
    api.get('/ah/export', config)
      .then((r) => {
        if (format === 'csv') {
          const blob = r.data;
          if (blob.size === 0) { setMsg('Sem dados para o periodo selecionado'); return; }
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = `export_${station}.csv`; a.click(); URL.revokeObjectURL(url);
          setMsg(`Exportado CSV com sucesso`);
        } else {
          const jsonStr = JSON.stringify(r.data, null, 2);
          const blob = new Blob([jsonStr], { type: 'application/json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = `export_${station}.json`; a.click(); URL.revokeObjectURL(url);
          setMsg(`Exportado JSON: ${r.data.length} registos`);
        }
      }).catch((e) => setMsg('Erro: ' + (e.response?.data?.error || e.message)))
      .finally(() => setDownloading(false));
  };

  return (
    <Card title="Exportar Series Temporais">
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <StationSelect value={station} onChange={setStation} />
        <DateRange start={start} end={end} onStartChange={setStart} onEndChange={setEnd} />
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={() => handleExport('csv')} disabled={!station || downloading}
          style={{ padding: '8px 20px', background: station ? '#2196F3' : '#90CAF9', color: '#fff', border: 'none', borderRadius: 6, cursor: downloading ? 'wait' : 'pointer' }}>
          Exportar CSV
        </button>
        <button onClick={() => handleExport('json')} disabled={!station || downloading}
          style={{ padding: '8px 20px', background: station ? '#4CAF50' : '#A5D6A7', color: '#fff', border: 'none', borderRadius: 6, cursor: downloading ? 'wait' : 'pointer' }}>
          Exportar JSON
        </button>
      </div>
      {!station && <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>Selecione uma estacao para exportar</div>}
      {msg && <div style={{ fontSize: 13, color: msg.startsWith('Erro') ? '#D32F2F' : '#2E7D32', marginTop: 8 }}>{msg}</div>}
    </Card>
  );
}

const PANELS = {
  'precipitation': PrecipitationPanel,
  'levels': LevelsPanel,
  'percentiles': PercentilesPanel,
  'flood-events': FloodEventsPanel,
  'map': MapPanel,
  'reservoirs': ReservoirsPanel,
  'export': ExportPanel,
};

export default function AHDashboard({ section = 'precipitation' }) {
  const Panel = PANELS[section] || PrecipitationPanel;
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ margin: '0 0 20px', fontSize: 20, color: '#1a2332' }}>Analista Hidrologico</h2>
      <Panel />
    </div>
  );
}
