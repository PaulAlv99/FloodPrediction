const { Router } = require('express');
const { query } = require('../db');
const { requireProfile } = require('../auth');

const router = Router();
router.use(requireProfile('AH', 'RPC', 'DE'));

router.get('/risk-overview', async (req, res) => {
  try {
    const stmt = `SELECT * FROM dbo.vw_risco_atual ORDER BY nivel_risco DESC`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/risk-unpivot', async (req, res) => {
  try {
    const stmt = `SELECT * FROM dbo.vw_risco_unpivot ORDER BY estacao_sk, horizonte`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/alerts', async (req, res) => {
  try {
    const { status } = req.query;
    let where = '';
    let params = {};
    if (status) { where = 'WHERE a.status = @status'; params.status = status; }
    const stmt = `
      SELECT a.alert_id, a.alert_type, a.severity, a.estacao_sk,
             e.estacao_id, e.estacao_nome, e.latitude, e.longitude, b.bacia_nome,
             a.message, a.metric_value, a.threshold_value, a.status,
             a.created_at, a.expires_at, a.acknowledged_by, a.acknowledged_at, a.resolved_at,
             DATEDIFF(MINUTE, a.created_at, GETDATE()) AS minutos_desde_criacao,
             CASE WHEN a.status='ACTIVE' AND a.severity='CRITICAL' THEN N'Vermelho'
                  WHEN a.status='ACTIVE' AND a.severity='ALERT' THEN N'Laranja'
                  WHEN a.status='ACTIVE' AND a.severity='WARNING' THEN N'Amarelo'
                  WHEN a.status='EXPIRED' THEN N'Cinza'
                  WHEN a.status='RESOLVED' THEN N'Verde'
                  ELSE N'Branco' END AS cor_alerta
      FROM ctl.alerts a
      LEFT JOIN gold.dim_estacao e ON a.estacao_sk = e.estacao_sk
      LEFT JOIN gold.dim_bacia b ON e.bacia_codigo = b.bacia_codigo
      ${where} ORDER BY a.created_at DESC`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.patch('/alerts/:id/acknowledge', async (req, res) => {
  try {
    const stmt = `
      UPDATE ctl.alerts SET status='ACKNOWLEDGED', acknowledged_by=@user, acknowledged_at=GETDATE()
      WHERE alert_id=@id AND status='ACTIVE'`;
    const r = await query(stmt, { id: parseInt(req.params.id), user: req.user.username });
    res.json({ updated: r.rowsAffected[0] });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/lstm', async (req, res) => {
  try {
    const { station_sk } = req.query;
    let where = '';
    let params = {};
    if (station_sk) { where = 'WHERE l.estacao_sk = @station_sk'; params.station_sk = parseInt(station_sk); }
    const stmt = `
      SELECT l.estacao_sk, e.estacao_nome, l.ts_previsao, l.horizonte_h,
             l.prob_cheia, l.flood_alert, l.threshold_used, l.model_version, l.created_at
      FROM ml.lstm_predictions l
      JOIN gold.dim_estacao e ON l.estacao_sk = e.estacao_sk
      ${where} ORDER BY l.ts_previsao DESC`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/forecast', async (req, res) => {
  try {
    const { station_sk, horizon } = req.query;
    let where = [];
    let params = {};
    if (station_sk) { where.push('estacao_sk = @station_sk'); params.station_sk = parseInt(station_sk); }
    if (horizon) { where.push('horizon_hours = @horizon'); params.horizon = parseInt(horizon); }
    const w = where.length ? 'WHERE ' + where.join(' AND ') : '';
    const stmt = `SELECT * FROM dbo.vw_previsoes_detalhe ${w} ORDER BY target_time DESC`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/detections', async (req, res) => {
  try {
    const stmt = `
      SELECT d.detection_id, d.estacao_sk, e.estacao_nome, e.latitude, e.longitude,
             b.bacia_nome, d.detection_ts,
             d.layer1_percentile_score, d.layer2_sequence_score, d.layer3_combined_score,
             d.lead_time_hours,
             CASE WHEN d.layer3_combined_score >= 0.8 THEN N'CRITICO'
                  WHEN d.layer3_combined_score >= 0.6 THEN N'ALTO'
                  WHEN d.layer3_combined_score >= 0.4 THEN N'MODERADO'
                  ELSE N'BAIXO' END AS nivel_deteccao
      FROM ml.ew_detections d
      JOIN gold.dim_estacao e ON d.estacao_sk = e.estacao_sk
      LEFT JOIN gold.dim_bacia b ON e.bacia_codigo = b.bacia_codigo
      ORDER BY d.detection_ts DESC`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

module.exports = router;
