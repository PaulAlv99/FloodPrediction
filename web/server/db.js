const sql = require('mssql');

const config = {
  server: process.env.DB_SERVER || '127.0.0.1',
  port: parseInt(process.env.DB_PORT || '1434'),
  database: process.env.DB_DATABASE || 'PreFlood_DW',
  user: process.env.DB_USER || 'sa',
  password: process.env.DB_PASS || 'TestPass123',
  options: {
    encrypt: false,
    trustServerCertificate: true,
    enableArithAbort: true,
  },
  pool: {
    max: 10,
    min: 0,
    idleTimeoutMillis: 30000,
  },
};

let poolReady = null;

async function getPool() {
  if (!poolReady) {
    poolReady = sql.connect(config);
  }
  try {
    return await poolReady;
  } catch (err) {
    poolReady = null;
    throw err;
  }
}

async function resetPool() {
  if (!poolReady) return;
  try {
    const pool = await poolReady;
    await pool.close();
  } catch {
    // Broken pool: drop it and reconnect on the next query.
  } finally {
    poolReady = null;
  }
}

function isConnectionError(err) {
  const message = `${err?.code || ''} ${err?.message || ''}`;
  return /ECONNRESET|Connection lost|EPIPE|ESOCKET|ETIMEDOUT|ECONNCLOSED|ENOTFOUND/i.test(message);
}

async function query(stmt, params = {}) {
  const runQuery = async () => {
    const p = await getPool();
    const req = p.request();
    for (const [k, v] of Object.entries(params)) {
      req.input(k, v);
    }
    return req.query(stmt);
  };

  try {
    return await runQuery();
  } catch (err) {
    if (!isConnectionError(err)) {
      throw err;
    }
    await resetPool();
    return runQuery();
  }
}

async function close() {
  if (poolReady) {
    const p = await poolReady;
    await p.close();
    poolReady = null;
  }
}

module.exports = { getPool, query, close, sql };
