const jwt = require('jsonwebtoken');

const SECRET = process.env.JWT_SECRET || 'change_me';
const PROFILES = ['AH', 'RPC', 'DE', 'AS'];

function generateToken(user) {
  return jwt.sign(
    { id: user.user_id, username: user.username, profile: user.profile },
    SECRET,
    { expiresIn: process.env.JWT_EXPIRES_IN || '8h' }
  );
}

function authMiddleware(req, res, next) {
  const header = req.headers.authorization;
  if (!header || !header.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Token em falta' });
  }
  try {
    const decoded = jwt.verify(header.slice(7), SECRET);
    req.user = decoded;
    next();
  } catch {
    return res.status(401).json({ error: 'Token invalido' });
  }
}

function requireProfile(...profiles) {
  return (req, res, next) => {
    if (!req.user || !profiles.includes(req.user.profile)) {
      return res.status(403).json({ error: 'Perfil nao autorizado' });
    }
    next();
  };
}

module.exports = { generateToken, authMiddleware, requireProfile, PROFILES };
