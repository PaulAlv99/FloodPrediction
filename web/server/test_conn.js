const sql = require('mssql');

(async () => {
  try {
    await sql.connect({
      server: '127.0.0.1', port: 1434,
      database: 'PreFlood_DW',
      user: 'sa', password: 'TestPass123',
      options: { encrypt: false, trustServerCertificate: true, enableArithAbort: true },
    });
    const r = await sql.query('SELECT TOP 2 estacao_sk, estacao_nome FROM gold.dim_estacao');
    console.log('Connected OK:', r.recordset);

    const r2 = await sql.query('SELECT username, profile FROM web.users');
    console.log('Users:', r2.recordset);

    await sql.close();
  } catch (e) {
    console.error('Error:', e.message);
  }
})();
