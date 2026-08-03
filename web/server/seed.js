const bcrypt = require('bcryptjs');
const { query, close, sql } = require('./db');

async function seed() {
  const users = [
    { u: 'ah_user', p: 'AH', n: 'Analista Hidrologico' },
    { u: 'rpc_user', p: 'RPC', n: 'Responsavel Protecao Civil' },
    { u: 'de_user', p: 'DE', n: 'Decisor Estrategico' },
    { u: 'as_user', p: 'AS', n: 'Administrador Sistema' },
  ];

  for (const { u, p, n } of users) {
    const hash = await bcrypt.hash('Preflood2026!', 10);
    await query(
      `IF NOT EXISTS (SELECT 1 FROM web.users WHERE username = @u)
       INSERT INTO web.users (username, password_hash, profile, nome) VALUES (@u, @h, @p, @n)`,
      { u, h: hash, p, n }
    );
    console.log('Seeded:', u);
  }
  await close();
}

seed().catch(e => console.error(e));
