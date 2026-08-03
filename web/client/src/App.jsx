import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth';
import Login from './pages/Login';
import Layout from './components/Layout';
import AHDashboard from './pages/ah/Dashboard';
import RPCDashboard from './pages/rpc/Dashboard';
import DEDashboard from './pages/de/Dashboard';
import ASDashboard from './pages/as/Dashboard';

function PrivateRoute({ children, profiles }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" />;
  if (profiles && !profiles.includes(user.profile)) return <Navigate to="/login" />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/ah" element={<PrivateRoute profiles={['AH']}><Layout><AHDashboard /></Layout></PrivateRoute>} />
        <Route path="/rpc" element={<PrivateRoute profiles={['AH','RPC','DE']}><Layout><RPCDashboard /></Layout></PrivateRoute>} />
        <Route path="/de" element={<PrivateRoute profiles={['AH','DE']}><Layout><DEDashboard /></Layout></PrivateRoute>} />
        <Route path="/as" element={<PrivateRoute profiles={['AS']}><Layout><ASDashboard /></Layout></PrivateRoute>} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    </AuthProvider>
  );
}
