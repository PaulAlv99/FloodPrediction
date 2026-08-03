import React, { useState, useEffect } from 'react';
import api from '../../api';
import { Card, StatCard, Spinner, ErrorMsg, Table } from '../../components/Common';
import { TimeSeriesChart, RiskGauge, COLORS } from '../../components/Charts';
import StationMap from '../../components/StationMap';

function OverviewPanel() {
  const [risk, setRisk] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    api.get('/rpc/risk-overview')
      .then((rRisk) => {
      setRisk(rRisk.data);
      })
      .catch((e) => {
        setError(e.response?.data?.error || e.message || 'Erro ao carregar painel');
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;
  if (error) return <ErrorMsg error={error} />;

  const highRisk = risk.filter(r => r.nivel_risco >= 4).length;
  const avgRisk = risk.length ? (risk.reduce((s, r) => s + r.nivel_risco, 0) / risk.length).toFixed(1) : 0;

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 20 }}>
        <StatCard label="Estacoes Monitorizadas" value={risk.length} color="#2196F3" />
        <StatCard label="Risco Alto/Muito Alto" value={highRisk} color="#D32F2F" />
        <StatCard label="Risco Medio Global" value={avgRisk} color="#FF9800" suffix="/5" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card title="Mapa de Risco">
          <StationMap stations={risk} valueKey="nivel_risco"
            labelFn={(s) => `Risco: ${s.nivel_risco}/5 — ${s.categoria_risco}`}
            colorFn={(s) => {
              const c = { 1: '#4CAF50', 2: '#8BC34A', 3: '#FFC107', 4: '#FF5722', 5: '#D32F2F' };
              return c[s.nivel_risco] || '#999';
            }} />
        </Card>
        <Card title="Nivel de Risco por Estacao">
          <div style={{ overflowY: 'auto', maxHeight: 380 }}>
            {risk.sort((a, b) => b.nivel_risco - a.nivel_risco).map((s) => (
              <div key={s.estacao_sk} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{s.estacao_nome}</div>
                  <div style={{ fontSize: 11, color: '#888' }}>{s.sistema_origem} — {s.categoria_risco}</div>
                </div>
                <div style={{ width: 60 }}><RiskGauge value={s.nivel_risco} /></div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}

function AlertsPanel() {
  const [status, setStatus] = useState('');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/rpc/alerts', { params: { status: status || undefined } })
      .then(r => setData(r.data)).finally(() => setLoading(false));
  }, [status]);

  const handleAck = async (id) => {
    await api.patch(`/rpc/alerts/${id}/acknowledge`);
    setStatus(status);
  };

  const columns = [
    { key: 'cor_alerta', label: '', render: (v) => <div style={{ width: 12, height: 12, borderRadius: 6, background: v === 'Vermelho' ? '#D32F2F' : v === 'Laranja' ? '#FF5722' : v === 'Amarelo' ? '#FFC107' : v === 'Verde' ? '#4CAF50' : '#999' }} /> },
    { key: 'alert_type', label: 'Tipo' },
    { key: 'severity', label: 'Severidade' },
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'message', label: 'Mensagem' },
    { key: 'metric_value', label: 'Valor', render: v => v?.toFixed(2) ?? '—' },
    { key: 'status', label: 'Estado' },
    { key: 'created_at', label: 'Criado', render: v => v?.slice(0, 16) },
    { key: 'alert_id', label: '', render: (v, row) => row.status === 'ACTIVE' ? (
      <button onClick={() => handleAck(v)} style={{ padding: '4px 12px', fontSize: 11, background: '#FF9800', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}>
        Confirmar
      </button>
    ) : null },
  ];

  return (
    <Card title="Gestao de Alertas">
      <div style={{ marginBottom: 12 }}>
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }}>
          <option value="">Todos</option><option value="ACTIVE">Ativos</option><option value="ACKNOWLEDGED">Confirmados</option><option value="RESOLVED">Resolvidos</option>
        </select>
      </div>
      {loading ? <Spinner /> : <>
        <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>{data.length} alertas</div>
        <Table columns={columns} data={data} />
      </>}
    </Card>
  );
}

function LSTMPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/rpc/lstm').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  const byStation = {};
  data.forEach(d => {
    if (!byStation[d.estacao_sk]) byStation[d.estacao_sk] = { nome: d.estacao_nome, rows: [] };
    byStation[d.estacao_sk].rows.push(d);
  });

  const stationCards = Object.entries(byStation).map(([sk, info]) => {
    const latest = info.rows.reduce((a, b) => a.horizonte_h < b.horizonte_h ? a : b);
    const byHorizon = {};
    info.rows.forEach(r => { byHorizon[r.horizonte_h] = r; });
    return { sk, nome: info.nome, latest, byHorizon };
  });

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
      {stationCards.length === 0 ? (
        <Card title="Probabilidade de Cheia (LSTM)">
          <div style={{ padding: 20, color: '#999' }}>Sem previsoes LSTM disponiveis</div>
        </Card>
      ) : stationCards.map(s => (
        <Card key={s.sk} title={s.nome}>
          <div style={{ textAlign: 'center', padding: '12px 0' }}>
            <div style={{ fontSize: 36, fontWeight: 700, color: s.latest.prob_cheia > 0.7 ? '#D32F2F' : s.latest.prob_cheia > 0.4 ? '#FF9800' : '#4CAF50' }}>
              {(s.latest.prob_cheia * 100).toFixed(1)}%
            </div>
            <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>Prob. Cheia — modelo LSTM v{s.latest.model_version}</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 12 }}>
            {[6, 12, 24].map(h => {
              const r = s.byHorizon[h];
              const p = r ? r.prob_cheia : 0;
              const alert = r ? r.flood_alert : 0;
              return (
                <div key={h} style={{ textAlign: 'center', padding: 8, background: alert ? '#FFF3E0' : '#f5f5f5', borderRadius: 6 }}>
                  <div style={{ fontSize: 11, color: '#888' }}>+{h}h</div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: p > 0.5 ? '#D32F2F' : p > 0.2 ? '#FF9800' : '#4CAF50' }}>
                    {(p * 100).toFixed(1)}%
                  </div>
                  {alert ? <div style={{ fontSize: 10, color: '#D32F2F', fontWeight: 600 }}>ALERTA</div> : null}
                </div>
              );
            })}
          </div>
        </Card>
      ))}
      <Card title="Historico LSTM">
        <Table columns={[
          { key: 'estacao_nome', label: 'Estacao' },
          { key: 'horizonte_h', label: 'Horizonte' },
          { key: 'prob_cheia', label: 'Prob. Cheia', render: v => v != null ? `${(v * 100).toFixed(1)}%` : '—' },
          { key: 'flood_alert', label: 'Alerta', render: v => v ? <span style={{ color: '#D32F2F' }}>Sim</span> : <span style={{ color: '#4CAF50' }}>Nao</span> },
          { key: 'ts_previsao', label: 'Data', render: v => v?.slice(0, 16) },
        ]} data={data.slice(0, 30)} />
      </Card>
    </div>
  );
}

function ForecastPanel() {
  const [station, setStation] = useState('229');
  const [horizon, setHorizon] = useState('1');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/rpc/forecast', { params: { station_sk: station, horizon: horizon || undefined } })
      .then(r => setData(r.data)).finally(() => setLoading(false));
  }, [station, horizon]);

  const sorted = [...data].sort((a, b) => a.target_time > b.target_time ? 1 : -1).slice(-200);
  const hasActual = sorted.some(d => d.actual_value != null);

  const chartData = sorted.map(d => ({
    target_time: d.target_time?.slice(0, 16),
    predicted: d.predicted_value,
    actual: d.actual_value,
  }));

  const lines = [
    { dataKey: 'predicted', name: 'Previsto', color: '#FF5722', width: 2 },
  ];
  if (hasActual) lines.push({ dataKey: 'actual', name: 'Real', color: '#2196F3', width: 2 });

  return (
    <Card title="Previsao de Nivel Hidrometrico">
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={station} onChange={(e) => setStation(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13, minWidth: 200 }}>
          {[229, 232, 233, 234].map(sk => <option key={sk} value={sk}>Estacao SK {sk}</option>)}
        </select>
        <select value={horizon} onChange={(e) => setHorizon(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }}>
          <option value="">Todos</option>
          <option value="1">1h</option><option value="3">3h</option><option value="6">6h</option>
          <option value="12">12h</option><option value="24">24h</option>
        </select>
        {!hasActual && <span style={{ fontSize: 12, color: '#FF9800' }}>Sem dados reais para comparar (actualizar com update_actuals)</span>}
      </div>
      {loading ? <Spinner /> : <TimeSeriesChart data={chartData} xKey="target_time"
        lines={lines} height={350} />}
      <div style={{ marginTop: 12, fontSize: 12, color: '#888' }}>{sorted.length} previsoes</div>
    </Card>
  );
}

function DetectionsPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/rpc/detections').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  if (data.length === 0) {
    return (
      <Card title="Deteccao Precoce de Cheias">
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ fontSize: 48, color: '#4CAF50', marginBottom: 12 }}>&#10003;</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#4CAF50' }}>Sem deteccoes ativas</div>
          <div style={{ fontSize: 13, color: '#888', marginTop: 8 }}>O sistema de deteccao precoce nao identificou anomalias nos ultimos dados analisados.</div>
        </div>
      </Card>
    );
  }

  const columns = [
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'detection_ts', label: 'Data', render: v => v?.slice(0, 16) },
    { key: 'layer3_combined_score', label: 'Score Combinado', render: v => v?.toFixed(3) },
    { key: 'nivel_deteccao', label: 'Nivel', render: (v) => {
      const c = { CRITICO: '#D32F2F', ALTO: '#FF5722', MODERADO: '#FFC107', BAIXO: '#4CAF50' };
      return <span style={{ color: c[v] || '#999', fontWeight: 600 }}>{v}</span>;
    }},
    { key: 'lead_time_hours', label: 'Lead Time (h)', render: v => v?.toFixed(1) },
  ];

  return (
    <Card title="Deteccao Precoce de Cheias">
      <Table columns={columns} data={data} />
    </Card>
  );
}

const PANELS = {
  'overview': OverviewPanel,
  'alerts': AlertsPanel,
  'lstm': LSTMPanel,
  'forecast': ForecastPanel,
  'detections': DetectionsPanel,
};

export default function RPCDashboard({ section = 'overview' }) {
  const Panel = PANELS[section] || OverviewPanel;
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ margin: '0 0 20px', fontSize: 20, color: '#1a2332' }}>Protecao Civil — Painel de Monitorizacao</h2>
      <Panel />
    </div>
  );
}
