const express = require('express');
const cors = require('cors');
const path = require('path');
require('dotenv').config();

const { authMiddleware } = require('./auth');
const authRoutes = require('./routes/auth');
const ahRoutes = require('./routes/ah');
const rpcRoutes = require('./routes/rpc');
const deRoutes = require('./routes/de');
const asRoutes = require('./routes/as');

const app = express();
app.use(cors());
app.use(express.json());

app.use('/api/auth', authRoutes);
app.use('/api/ah', authMiddleware, ahRoutes);
app.use('/api/rpc', authMiddleware, rpcRoutes);
app.use('/api/de', authMiddleware, deRoutes);
app.use('/api/as', authMiddleware, asRoutes);

app.use(express.static(path.join(__dirname, '..', 'client', 'dist')));
app.get('*', (req, res) => {
  if (!req.path.startsWith('/api')) {
    res.sendFile(path.join(__dirname, '..', 'client', 'dist', 'index.html'));
  }
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => console.log(`PreFlood API listening on port ${PORT}`));
