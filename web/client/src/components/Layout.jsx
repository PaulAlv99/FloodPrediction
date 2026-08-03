import React from 'react';
import { useAuth } from '../auth';
import { useNavigate, useLocation } from 'react-router-dom';
import { LogOut, Droplets, ShieldAlert, TrendingUp, Settings } from 'lucide-react';

const PROFILE_META = {
  AH: { label: 'Analista Hidrologico', icon: Droplets, color: '#2196F3', path: '/ah' },
  RPC: { label: 'Protecao Civil', icon: ShieldAlert, color: '#FF5722', path: '/rpc' },
  DE: { label: 'Decisor Estrategico', icon: TrendingUp, color: '#4CAF50', path: '/de' },
  AS: { label: 'Administrador', icon: Settings, color: '#607D8B', path: '/as' },
};

const NAV_ITEMS = {
  AH: [
    { key: 'precipitation', label: 'Precipitacao' },
    { key: 'levels', label: 'Niveis e Caudais' },
    { key: 'percentiles', label: 'Percentis' },
    { key: 'flood-events', label: 'Eventos de Cheia' },
    { key: 'map', label: 'Mapa' },
    { key: 'reservoirs', label: 'Albufeiras' },
    { key: 'export', label: 'Exportar' },
  ],
  RPC: [
    { key: 'overview', label: 'Painel Integrado' },
    { key: 'alerts', label: 'Alertas' },
    { key: 'lstm', label: 'Prob. Cheia LSTM' },
    { key: 'forecast', label: 'Previsao Niveis' },
    { key: 'detections', label: 'Deteccao Precoce' },
  ],
  DE: [
    { key: 'flood-history', label: 'Evolucao Cheias' },
    { key: 'comparison', label: 'Comparacao Risco' },
    { key: 'event-assessment', label: 'Pre/Pos Evento' },
    { key: 'climate-trends', label: 'Tendencias' },
  ],
  AS: [
    { key: 'data-sources', label: 'Fontes de Dados' },
    { key: 'etl-history', label: 'Historico ETL' },
    { key: 'thresholds', label: 'Limiares' },
    { key: 'quarantine', label: 'Quarentena' },
    { key: 'latency', label: 'Latencia' },
    { key: 'models', label: 'Modelos ML' },
  ],
};

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const meta = PROFILE_META[user?.profile] || {};
  const items = NAV_ITEMS[user?.profile] || [];
  const Icon = meta.icon || Droplets;

  const [section, setSection] = React.useState(() => {
    const params = new URLSearchParams(location.search);
    return params.get('tab') || items[0]?.key || '';
  });

  const handleNav = (key) => {
    setSection(key);
    navigate(`${meta.path}?tab=${key}`, { replace: true });
  };

  const childWithSection = React.Children.map(children, (child) => {
    if (React.isValidElement(child)) {
      return React.cloneElement(child, { section });
    }
    return child;
  });

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Segoe UI', sans-serif" }}>
      <aside style={{
        width: 240, background: '#1a2332', color: '#fff', display: 'flex', flexDirection: 'column',
        flexShrink: 0,
      }}>
        <div style={{ padding: '20px 16px', borderBottom: '1px solid #2a3a4e' }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>PreFlood DW</div>
          <div style={{ fontSize: 12, color: '#8899aa', marginTop: 4 }}>Dashboard</div>
        </div>
        <div style={{ padding: '12px 16px', background: '#223344', marginBottom: 8 }}>
          <div style={{ fontSize: 13, color: '#aabbcc' }}>{user?.nome || user?.username}</div>
          <div style={{ fontSize: 11, color: meta.color, marginTop: 2 }}>
            <Icon size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
            {meta.label}
          </div>
        </div>
        <nav style={{ flex: 1, padding: '8px 0' }}>
          {items.map((item) => (
            <button key={item.key} onClick={() => handleNav(item.key)}
              style={{
                display: 'block', width: '100%', padding: '10px 20px', border: 'none',
                background: section === item.key ? '#2a4a6e' : 'transparent',
                color: section === item.key ? '#fff' : '#8899aa',
                textAlign: 'left', cursor: 'pointer', fontSize: 13,
              }}>
              {item.label}
            </button>
          ))}
        </nav>
        <button onClick={logout} style={{
          padding: '12px 20px', border: 'none', background: '#2a3a4e', color: '#8899aa',
          cursor: 'pointer', textAlign: 'left', fontSize: 13,
        }}>
          <LogOut size={14} style={{ verticalAlign: 'middle', marginRight: 8 }} />
          Terminar Sessao
        </button>
      </aside>
      <main style={{ flex: 1, background: '#f0f2f5', overflow: 'auto' }}>
        {childWithSection}
      </main>
    </div>
  );
}
