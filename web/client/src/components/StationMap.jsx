import React from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

const RISK_COLORS = { 1: '#4CAF50', 2: '#8BC34A', 3: '#FFC107', 4: '#FF5722', 5: '#D32F2F' };

export default function StationMap({ stations, valueKey = 'nivel_risco', labelFn, colorFn, zoom = 9, center = [40.2, -8.0] }) {
  const getColor = (s) => {
    if (colorFn) return colorFn(s);
    if (RISK_COLORS[s[valueKey]]) return RISK_COLORS[s[valueKey]];
    return '#2196F3';
  };

  const getRadius = (s) => {
    const v = s[valueKey];
    if (typeof v === 'number') return Math.max(6, Math.min(v * 4, 20));
    return 8;
  };

  return (
    <MapContainer center={center} zoom={zoom} style={{ height: 400, borderRadius: 8 }}>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap" />
      {stations.filter(s => s.latitude && s.longitude).map((s) => (
        <CircleMarker key={s.estacao_sk} center={[s.latitude, s.longitude]}
          radius={getRadius(s)} pathOptions={{ color: getColor(s), fillColor: getColor(s), fillOpacity: 0.7, weight: 2 }}>
          <Popup>
            <div style={{ fontSize: 12 }}>
              <strong>{s.estacao_nome}</strong><br />
              {labelFn ? labelFn(s) : `${valueKey}: ${s[valueKey] ?? '—'}`}
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
