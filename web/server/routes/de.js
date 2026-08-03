const { Router } = require('express');
const { query } = require('../db');
const { requireProfile } = require('../auth');

const router = Router();
router.use(requireProfile('AH', 'DE'));

router.get('/flood-history', async (req, res) => {
  try {
    const { station_sk, year } = req.query;
    let where = [];
    let params = {};
    if (station_sk) { where.push('e.estacao_sk = @station_sk'); params.station_sk = parseInt(station_sk); }
    if (year) { where.push('YEAR(e.event_start) = @year'); params.year = parseInt(year); }
    const w = where.length ? 'WHERE ' + where.join(' AND ') : '';
    const stmt = `
      SELECT e.estacao_sk, est.estacao_nome, b.bacia_nome, YEAR(e.event_start) AS ano,
             COUNT(*) AS num_eventos, AVG(CAST(e.duration_hours AS FLOAT)) AS duracao_media_h,
             MAX(e.peak_value) AS pico_maximo, AVG(e.peak_value) AS pico_medio,
             AVG(CAST(e.rise_rate AS FLOAT)) AS taxa_subida_media,
             AVG(e.antecedent_precip_24h) AS precip_antecedente_media
      FROM ml.ew_flood_events e
      JOIN gold.dim_estacao est ON e.estacao_sk = est.estacao_sk
      LEFT JOIN gold.dim_bacia b ON est.bacia_codigo = b.bacia_codigo
      ${w} GROUP BY e.estacao_sk, est.estacao_nome, b.bacia_nome, YEAR(e.event_start)
      ORDER BY ano`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/risk-comparison', async (req, res) => {
  try {
    const stmt = `
      SELECT e.estacao_sk, e.estacao_nome, e.sistema_origem, e.latitude, e.longitude,
             b.bacia_nome, rc.nivel_risco, rc.categoria_risco,
             rc.nivel_inst_atual, rc.precip_accum_24h, rc.solo_saturacao_pct,
             rc.data_atualizacao
      FROM ml.flood_risk_current rc
      JOIN gold.dim_estacao e ON rc.estacao_sk = e.estacao_sk
      LEFT JOIN gold.dim_bacia b ON e.bacia_codigo = b.bacia_codigo
      ORDER BY rc.nivel_risco DESC`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/event-assessment', async (req, res) => {
  try {
    const { event_id } = req.query;
    if (!event_id) return res.status(400).json({ error: 'event_id obrigatorio' });
    const eventStmt = `
      SELECT fe.*, e.estacao_nome, e.latitude, e.longitude
      FROM ml.ew_flood_events fe
      JOIN gold.dim_estacao e ON fe.estacao_sk = e.estacao_sk
      WHERE fe.event_id = @event_id`;
    const ev = await query(eventStmt, { event_id: parseInt(event_id) });
    if (ev.recordset.length === 0) return res.json({ event: null, series: [] });
    const evData = ev.recordset[0];
    const seriesStmt = `
      SELECT t.data_hora, p.parametro_codigo, fm.valor
      FROM gold.fact_medicao fm
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE fm.estacao_sk = @station_sk
        AND p.parametro_codigo IN ('1843','354895424','prec')
        AND t.data_hora BETWEEN @start AND @end
      ORDER BY t.data_hora`;
    const margin = 48;
    const start = new Date(new Date(evData.event_start).getTime() - margin * 3600000);
    const end = new Date(new Date(evData.event_end).getTime() + margin * 3600000);
    const ser = await query(seriesStmt, { station_sk: evData.estacao_sk, start, end });
    res.json({ event: evData, series: ser.recordset });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/climate-trends', async (req, res) => {
  try {
    const { station_sk } = req.query;
    let where = '';
    let params = {};
    if (station_sk) { where = 'AND e.estacao_sk = @station_sk'; params.station_sk = parseInt(station_sk); }
    const stmt = `
      SELECT e.estacao_sk, e.estacao_nome, t.ano,
             AVG(CASE WHEN p.parametro_codigo='tp' THEN fm.valor END) AS precip_media_anual,
             SUM(CASE WHEN p.parametro_codigo='tp' THEN fm.valor END) AS precip_total_anual,
             MAX(CASE WHEN p.parametro_codigo='tp' THEN fm.valor END) AS precip_max_anual,
             AVG(CASE WHEN p.parametro_codigo='swvl1' THEN fm.valor END) AS swvl1_media_anual,
             AVG(CASE WHEN p.parametro_codigo='t2m' THEN fm.valor END) AS temp_media_anual
      FROM gold.fact_medicao fm
      JOIN gold.dim_estacao e ON fm.estacao_sk = e.estacao_sk
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE e.sistema_origem = 'ERA5' AND p.parametro_codigo IN ('tp','swvl1','t2m') ${where}
      GROUP BY e.estacao_sk, e.estacao_nome, t.ano
      ORDER BY e.estacao_sk, t.ano`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

module.exports = router;
