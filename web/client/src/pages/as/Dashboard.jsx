import React, { useState, useEffect } from 'react';
import api from '../../api';
import { Card, StatCard, Spinner, ErrorMsg, Table } from '../../components/Common';
import { BarChartPanel } from '../../components/Charts';

function DataSourcesPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/as/data-sources').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  const columns = [
    { key: 'source_system', label: 'Fonte' },
    { key: 'silver_table', label: 'Tabela' },
    { key: 'estado_fonte', label: 'Estado', render: (v) => {
      const c = { Atualizado: '#4CAF50', Atrasado: '#FF9800', Erro: '#D32F2F', Pendente: '#999' };
      return <span style={{ color: c[v] || '#999', fontWeight: 600 }}>{v}</span>;
    }},
    { key: 'total_lidos', label: 'Lidos' },
    { key: 'total_escritos', label: 'Escritos' },
    { key: 'total_rejeitados', label: 'Rejeitados' },
    { key: 'num_erros', label: 'Erros' },
    { key: 'ultima_carga_ok', label: 'Ultima Carga', render: v => v?.slice(0, 16) },
  ];

  return (
    <Card title="Estado das Fontes de Dados">
      {loading ? <Spinner /> : <Table columns={columns} data={data} />}
    </Card>
  );
}

function ETLHistoryPanel() {
  const [date, setDate] = useState('');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.get('/as/etl-history', { params: { date: date || undefined } })
      .then(r => setData(r.data)).finally(() => setLoading(false));
  }, [date]);

  const columns = [
    { key: 'Fase', label: 'Fase' },
    { key: 'Passo', label: 'Passo' },
    { key: 'Status', label: 'Status', render: (v) => (
      <span style={{ color: v === 'OK' ? '#4CAF50' : v === 'ERRO' ? '#D32F2F' : v === 'INICIO' ? '#FF9800' : '#999', fontWeight: 600 }}>{v}</span>
    )},
    { key: 'Duracao_Seg', label: 'Duracao (s)', render: v => v != null ? v.toFixed(1) : '—' },
    { key: 'Registros_Lidos', label: 'Lidos', render: v => v != null ? v.toLocaleString() : '—' },
    { key: 'Registros_Escritos', label: 'Escritos', render: v => v != null ? v.toLocaleString() : '—' },
    { key: 'Registros_Rejeitados', label: 'Rejeitados', render: v => v != null ? v.toLocaleString() : '—' },
    { key: 'Dt_Inicio', label: 'Inicio', render: v => v?.slice(0, 16) },
  ];

  const byFase = data.reduce((acc, d) => {
    const k = d.Fase;
    if (!acc[k]) acc[k] = { fase: k, total: 0, erros: 0 };
    acc[k].total++;
    if (d.Status === 'ERRO') acc[k].erros++;
    return acc;
  }, {});

  return (
    <>
      <Card title="Historico de Execucoes ETL">
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 13, marginRight: 8 }}>Data:</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', fontSize: 13 }} />
        </div>
        {loading ? <Spinner /> : <>
          <BarChartPanel data={Object.values(byFase)} xKey="fase"
            bars={[
              { dataKey: 'total', name: 'Execucoes', color: '#2196F3' },
              { dataKey: 'erros', name: 'Erros', color: '#D32F2F' },
            ]} height={200} />
          <div style={{ marginTop: 16, maxHeight: 400, overflow: 'auto' }}>
            <Table columns={columns} data={data.slice(0, 100)} />
          </div>
        </>}
      </Card>
    </>
  );
}

function ThresholdsPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editSk, setEditSk] = useState(null);
  const [editVals, setEditVals] = useState({ p90: '', p95: '', p99: '' });

  const load = () => {
    setLoading(true);
    api.get('/as/thresholds').then(r => setData(r.data)).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleSave = async () => {
    await api.put(`/as/thresholds/flood/${editSk}`, {
      p90: parseFloat(editVals.p90),
      p95: parseFloat(editVals.p95),
      p99: parseFloat(editVals.p99),
    });
    setEditSk(null);
    load();
  };

  const columns = [
    { key: 'tabela_origem', label: 'Origem' },
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'parametro', label: 'Parametro' },
    { key: 'p90', label: 'P90', render: v => v?.toFixed(3) ?? '—' },
    { key: 'p95', label: 'P95', render: v => v?.toFixed(3) ?? '—' },
    { key: 'p99', label: 'P99', render: v => v?.toFixed(3) ?? '—' },
    { key: 'warning_level', label: 'Warning', render: v => v?.toFixed(3) ?? '—' },
    { key: 'alert_level', label: 'Alert', render: v => v?.toFixed(3) ?? '—' },
    { key: 'critical_level', label: 'Critical', render: v => v?.toFixed(3) ?? '—' },
  ];

  return (
    <Card title="Gestao de Limiares">
      {loading ? <Spinner /> : <>
        <Table columns={columns} data={data} />
        <div style={{ marginTop: 16, padding: 16, background: '#f8f9fa', borderRadius: 6 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Editar Flood Thresholds (estacao_sk):</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input placeholder="estacao_sk" value={editSk || ''} onChange={(e) => setEditSk(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', width: 100, fontSize: 13 }} />
            <input placeholder="P90" value={editVals.p90} onChange={(e) => setEditVals({ ...editVals, p90: e.target.value })}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', width: 80, fontSize: 13 }} />
            <input placeholder="P95" value={editVals.p95} onChange={(e) => setEditVals({ ...editVals, p95: e.target.value })}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', width: 80, fontSize: 13 }} />
            <input placeholder="P99" value={editVals.p99} onChange={(e) => setEditVals({ ...editVals, p99: e.target.value })}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #ddd', width: 80, fontSize: 13 }} />
            <button onClick={handleSave} style={{ padding: '6px 16px', background: '#2196F3', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
              Guardar
            </button>
          </div>
        </div>
      </>}
    </Card>
  );
}

function QuarantinePanel() {
  const [summary, setSummary] = useState([]);
  const [detail, setDetail] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDetail, setShowDetail] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    Promise.all([
      api.get('/as/quarantine'),
      api.get('/as/quarantine/detail'),
    ]).then(([rS, rD]) => {
      setSummary(rS.data);
      setDetail(rD.data);
    }).catch((e) => {
      setError(e.response?.data?.error || e.message || 'Erro ao carregar quarentena');
    }).finally(() => setLoading(false));
  }, []);

  const summaryCols = [
    { key: 'Fonte', label: 'Fonte' },
    { key: 'Motivo_Curto', label: 'Motivo' },
    { key: 'total_registos', label: 'Total' },
    { key: 'primeira_rejeicao', label: 'Primeira', render: v => v?.slice(0, 10) },
    { key: 'ultima_rejeicao', label: 'Ultima', render: v => v?.slice(0, 10) },
  ];

  const detailCols = [
    { key: 'Fonte', label: 'Fonte' },
    { key: 'Motivo', label: 'Motivo' },
    { key: 'Chave_Registo', label: 'Chave', render: v => v ? String(v).slice(0, 30) : '—' },
    { key: 'Dt_Quarentena', label: 'Data', render: v => v?.slice(0, 16) },
    { key: 'Resolvido', label: 'Resolvido', render: v => v ? <span style={{ color: '#4CAF50' }}>Sim</span> : <span style={{ color: '#FF9800' }}>Nao</span> },
  ];

  return (
    <Card title="Qualidade dos Dados — Quarentena">
      {loading ? <Spinner /> : <>
        {error && <ErrorMsg error={error} />}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
          {summary.map((s, i) => (
            <StatCard key={i} label={`${s.Fonte} — ${s.Motivo_Curto || 'N/A'}`} value={s.total_registos} color={s.total_registos > 1000 ? '#D32F2F' : s.total_registos > 100 ? '#FF9800' : '#4CAF50'} />
          ))}
        </div>
        <Table columns={summaryCols} data={summary} />
        <button onClick={() => setShowDetail(!showDetail)} style={{ marginTop: 12, padding: '6px 16px', background: '#607D8B', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>
          {showDetail ? 'Ocultar Detalhes' : `Ver Ultimos ${detail.length} Registos`}
        </button>
        {showDetail && <div style={{ marginTop: 12, maxHeight: 300, overflow: 'auto' }}>
          <Table columns={detailCols} data={detail} />
        </div>}
      </>}
    </Card>
  );
}

function LatencyPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/as/latency').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  const columns = [
    { key: 'source_system', label: 'Passo ETL' },
    { key: 'estado', label: 'Estado', render: (v) => {
      const c = { OK: '#4CAF50', Atrasado: '#FF9800', Erro: '#D32F2F' };
      return <span style={{ color: c[v] || '#999', fontWeight: 600 }}>{v}</span>;
    }},
    { key: 'minutos_desde_ultima', label: 'Latencia (min)', render: v => {
      if (v == null) return '—';
      const c = v > 1440 ? '#D32F2F' : v > 360 ? '#FF9800' : '#4CAF50';
      return <span style={{ color: c, fontWeight: 600 }}>{v.toFixed(0)}</span>;
    }},
    { key: 'total_lidos', label: 'Total Lidos', render: v => v != null ? v.toLocaleString() : '—' },
    { key: 'total_escritos', label: 'Total Escritos', render: v => v != null ? v.toLocaleString() : '—' },
    { key: 'ultima_carga_ok', label: 'Ultima Carga', render: v => v?.slice(0, 16) },
  ];

  return (
    <Card title="Monitorizacao de Latencia">
      {loading ? <Spinner /> : <Table columns={columns} data={data} />}
    </Card>
  );
}

function ModelsPanel() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get('/as/models').then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);

  const columns = [
    { key: 'estacao_nome', label: 'Estacao' },
    { key: 'target_parametro', label: 'Parametro' },
    { key: 'horizon_hours', label: 'Horizonte' },
    { key: 'algorithm', label: 'Algoritmo' },
    { key: 'modelo_tipo', label: 'Tipo' },
    { key: 'mae', label: 'AUC/MAE', render: v => v?.toFixed(4) ?? '—' },
    { key: 'r2', label: 'F1/R2', render: v => v?.toFixed(4) ?? '—' },
    { key: 'data_treino', label: 'Treino', render: v => v?.slice(0, 10) },
  ];

  return (
    <Card title="Registo de Modelos ML">
      {loading ? <Spinner /> : <Table columns={columns} data={data} />}
    </Card>
  );
}

const PANELS = {
  'data-sources': DataSourcesPanel,
  'etl-history': ETLHistoryPanel,
  'thresholds': ThresholdsPanel,
  'quarantine': QuarantinePanel,
  'latency': LatencyPanel,
  'models': ModelsPanel,
};

export default function ASDashboard({ section = 'data-sources' }) {
  const Panel = PANELS[section] || DataSourcesPanel;
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ margin: '0 0 20px', fontSize: 20, color: '#1a2332' }}>Administrador do Sistema</h2>
      <Panel />
    </div>
  );
}
