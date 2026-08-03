import React, { useState, useEffect } from 'react';
import api from '../../api';
import { Card, StatCard, Spinner, Table } from '../../components/Common';
import { TimeSeriesChart, BarChartPanel, COLORS } from '../../components/Charts';
import StationMap from '../../components/StationMap';

function FloodHistoryPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/de/flood-history').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  const years = [...new Set(data.map(d => d.ano))].sort();

  const columns = [
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'ano', label: 'Ano' },
    { key: 'num_eventos', label: 'Eventos' },
    { key: 'duracao_media_h', label: 'Dur. Media (h)', render: v => v?.toFixed(1) },
    { key: 'pico_maximo', label: 'Pico Max (m)', render: v => v?.toFixed(3) },
    { key: 'pico_medio', label: 'Pico Medio', render: v => v?.toFixed(3) },
    { key: 'taxa_subida_media', label: 'Taxa Subida', render: v => v?.toFixed(4) },
    { key: 'precip_antecedente_media', label: 'Precip Ant. (mm)', render: v => v?.toFixed(1) },
  ];

  const barData = data.reduce((acc, d) => {
    const existing = acc.find(a => a.ano === d.ano);
    if (existing) existing.total += d.num_eventos;
    else acc.push({ ano: d.ano, total: d.num_eventos });
    return acc;
  }, []);

  return (
    <>
      <Card title="Evolucao Historica de Cheias">
        {loading ? <Spinner /> : <>
          <BarChartPanel data={barData} xKey="ano" bars={[{ dataKey: 'total', name: 'Nr Eventos', color: '#FF5722' }]} height={250} />
          <div style={{ marginTop: 16 }}><Table columns={columns} data={data} /></div>
        </>}
      </Card>
    </>
  );
}

function ComparisonPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/de/risk-comparison').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card title="Mapa de Risco Comparativo">
          {loading ? <Spinner /> : <StationMap stations={data} valueKey="nivel_risco"
            labelFn={(s) => `${s.estacao_nome} — Risco ${s.nivel_risco}/5 (${s.categoria_risco})`}
            colorFn={(s) => ({ 1: '#4CAF50', 2: '#8BC34A', 3: '#FFC107', 4: '#FF5722', 5: '#D32F2F' }[s.nivel_risco] || '#999')} />}
        </Card>
        <Card title="Comparacao de Risco">
          {loading ? <Spinner /> : (
            <Table columns={[
              { key: 'estacao_nome', label: 'Estacao' },
              { key: 'categoria_risco', label: 'Categoria', render: (v) => {
                const c = { 'Muito Baixo': '#4CAF50', 'Baixo': '#8BC34A', 'Moderado': '#FFC107', 'Alto': '#FF5722', 'Muito Alto': '#D32F2F' };
                return <span style={{ color: c[v] || '#999', fontWeight: 600 }}>{v}</span>;
              }},
              { key: 'nivel_inst_atual', label: 'Nivel Atual', render: v => v?.toFixed(2) ?? '—' },
              { key: 'precip_accum_24h', label: 'Precip 24h', render: v => v?.toFixed(1) ?? '—' },
              { key: 'solo_saturacao_pct', label: 'Solo %', render: v => v?.toFixed(0) ?? '—' },
            ]} data={data} />
          )}
        </Card>
      </div>
    </>
  );
}

function EventAssessmentPanel() {
  const [events, setEvents] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingEvent, setLoadingEvent] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.get('/ah/flood-events').then(r => {
      setEvents(r.data);
      if (r.data.length > 0) setSelectedEvent(r.data[0].event_id);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedEvent) return;
    setLoadingEvent(true);
    api.get('/de/event-assessment', { params: { event_id: selectedEvent } })
      .then(r => setResult(r.data)).finally(() => setLoadingEvent(false));
  }, [selectedEvent]);

  const chartData = result?.series ? (() => {
    const pivoted = {};
    result.series.forEach(s => {
      const k = s.data_hora?.slice(0, 16);
      if (!pivoted[k]) pivoted[k] = { data_hora: k };
      pivoted[k][s.parametro_codigo] = s.valor;
    });
    return Object.values(pivoted).sort((a, b) => a.data_hora > b.data_hora ? 1 : -1);
  })() : [];

  return (
    <Card title="Avaliacao Pre/Pos Evento">
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        <label style={{ fontSize: 13 }}>Evento:</label>
        <select value={selectedEvent || ''} onChange={(e) => setSelectedEvent(parseInt(e.target.value))}
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13, minWidth: 350 }}>
          {events.map(ev => (
            <option key={ev.event_id} value={ev.event_id}>
              #{ev.event_id} — {ev.estacao_nome} ({ev.event_start?.slice(0, 10)}) Pico: {ev.peak_value?.toFixed(2)}m
            </option>
          ))}
        </select>
      </div>
      {loadingEvent ? <Spinner /> : result?.event ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginBottom: 16 }}>
            <StatCard label="Estacao" value={result.event.estacao_nome} color="#2196F3" />
            <StatCard label="Pico" value={result.event.peak_value?.toFixed(3)} suffix=" m" color="#FF5722" />
            <StatCard label="Duracao" value={result.event.duration_hours?.toFixed(1)} suffix=" h" color="#4CAF50" />
            <StatCard label="Taxa Subida" value={result.event.rise_rate?.toFixed(4)} color="#FF9800" />
          </div>
          {chartData.length > 0 ? (
            <TimeSeriesChart data={chartData} xKey="data_hora"
              lines={[
                { dataKey: '1843', name: 'Nivel (m)', color: '#2196F3', width: 2 },
                { dataKey: '354895424', name: 'Cota (m)', color: '#9C27B0', width: 2 },
                { dataKey: 'prec', name: 'Precipitacao', color: '#FF5722', yAxisId: 1 },
              ]} height={350} />
          ) : <div style={{ color: '#999', padding: 20 }}>Sem dados de serie temporal para este evento</div>}
        </>
      ) : <div style={{ color: '#999' }}>Selecione um evento para analisar</div>}
    </Card>
  );
}

function ClimateTrendsPanel() {
  const [station, setStation] = useState('');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/de/climate-trends', { params: { station_sk: station || undefined } })
      .then(r => setData(r.data)).finally(() => setLoading(false));
  }, [station]);

  return (
    <Card title="Tendencias Climaticas Longo Prazo">
      <div style={{ marginBottom: 12 }}>
        <select value={station} onChange={(e) => setStation(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }}>
          <option value="">Todas ERA5</option>
          <option value="237">ERA5_40.1_-8.3</option>
          <option value="238">ERA5_40.2_-8.4</option>
          <option value="239">ERA5_40.2_-8.2</option>
          <option value="240">ERA5_40.2_-7.8</option>
          <option value="241">ERA5_40.3_-8.3</option>
          <option value="242">ERA5_40.3_-8.2</option>
          <option value="243">ERA5_40.4_-7.6</option>
          <option value="244">ERA5_40.5_-7.3</option>
        </select>
      </div>
      {loading ? <Spinner /> : data.length > 0 ? (
        <>
          <TimeSeriesChart data={data} xKey="ano"
            lines={[
              { dataKey: 'precip_total_anual', name: 'Precip Total ERA5 (mm)', color: '#2196F3' },
              { dataKey: 'temp_media_anual', name: 'Temp Media (K)', color: '#FF5722' },
            ]} height={350} />
          <Table columns={[
            { key: 'estacao_nome', label: 'Estacao' },
            { key: 'ano', label: 'Ano' },
            { key: 'precip_total_anual', label: 'Precip Total', render: v => v?.toFixed(0) },
            { key: 'temp_media_anual', label: 'Temp Media', render: v => v?.toFixed(1) },
            { key: 'swvl1_media_anual', label: 'Solo L1', render: v => v?.toFixed(3) },
          ]} data={data} />
        </>
      ) : <div style={{ color: '#999', padding: 20 }}>Sem dados para o periodo selecionado</div>}
    </Card>
  );
}

const PANELS = {
  'flood-history': FloodHistoryPanel,
  'comparison': ComparisonPanel,
  'event-assessment': EventAssessmentPanel,
  'climate-trends': ClimateTrendsPanel,
};

export default function DEDashboard({ section = 'flood-history' }) {
  const Panel = PANELS[section] || FloodHistoryPanel;
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ margin: '0 0 20px', fontSize: 20, color: '#1a2332' }}>Decisor Estrategico</h2>
      <Panel />
    </div>
  );
}
