import React, { useState } from 'react';
import { useAuth } from '../auth';
import { Droplets } from 'lucide-react';

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.response?.data?.error || 'Erro ao iniciar sessao');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
                 background: 'linear-gradient(135deg, #1a2332 0%, #2a4a6e 100%)', fontFamily: "'Segoe UI', sans-serif" }}>
      <form onSubmit={handleSubmit} style={{
        background: '#fff', borderRadius: 12, padding: 40, width: 380, boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <Droplets size={40} color="#2196F3" style={{ marginBottom: 8 }} />
          <h1 style={{ margin: 0, fontSize: 24, color: '#1a2332' }}>PreFlood DW</h1>
          <p style={{ color: '#666', fontSize: 13, marginTop: 4 }}>Sistema de Previsao de Cheias</p>
        </div>
        {error && <div style={{ background: '#ffebee', color: '#c62828', padding: 10, borderRadius: 6, marginBottom: 16, fontSize: 13 }}>{error}</div>}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#555', marginBottom: 4 }}>Utilizador</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)}
            style={{ width: '100%', padding: 10, border: '1px solid #ddd', borderRadius: 6, fontSize: 14, boxSizing: 'border-box' }} />
        </div>
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#555', marginBottom: 4 }}>Palavra-passe</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            style={{ width: '100%', padding: 10, border: '1px solid #ddd', borderRadius: 6, fontSize: 14, boxSizing: 'border-box' }} />
        </div>
        <button type="submit" disabled={loading} style={{
          width: '100%', padding: 12, background: loading ? '#90CAF9' : '#2196F3', color: '#fff',
          border: 'none', borderRadius: 6, fontSize: 15, cursor: loading ? 'wait' : 'pointer',
        }}>
          {loading ? 'A entrar...' : 'Entrar'}
        </button>
      </form>
    </div>
  );
}
