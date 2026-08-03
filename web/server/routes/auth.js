const { Router } = require('express');
const bcrypt = require('bcryptjs');
const { query } = require('../db');
const { generateToken } = require('../auth');

const router = Router();

router.post('/login', async (req, res) => {
  try {
    const { username, password } = req.body;
    if (!username || !password) {
      return res.status(400).json({ error: 'Username e password obrigatorios' });
    }
    const result = await query(
      `SELECT user_id, username, password_hash, profile, nome, ativo
       FROM web.users WHERE username = @username`,
      { username }
    );
    if (result.recordset.length === 0) {
      return res.status(401).json({ error: 'Credenciais invalidas' });
    }
    const user = result.recordset[0];
    if (!user.ativo) {
      return res.status(403).json({ error: 'Utilizador inactivo' });
    }
    const valid = await bcrypt.compare(password, user.password_hash);
    if (!valid) {
      return res.status(401).json({ error: 'Credenciais invalidas' });
    }
    const token = generateToken({
      user_id: user.user_id,
      username: user.username,
      profile: user.profile,
    });
    res.json({
      token,
      user: { username: user.username, profile: user.profile, nome: user.nome },
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.get('/me', async (req, res) => {
  const auth = require('../auth');
  auth.authMiddleware(req, res, () => {
    res.json({ user: req.user });
  });
});

module.exports = router;
