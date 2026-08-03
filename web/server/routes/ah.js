const { Router } = require('express');
const { query } = require('../db');
const { requireProfile } = require('../auth');

const router = Router();
router.use(requireProfile('AH'));

router.get('/stations', async (req, res) => {
  try {
    const r = await query(`
      SELECT estacao_sk, estacao_id, estacao_nome, sistema_origem,
             latitude, longitude, bacia_codigo, ativa
      FROM gold.dim_estacao WHERE ativa = 1 ORDER BY estacao_nome`);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/precipitation', async (req, res) => {
  try {
    const { station_sk, start, end, granularity = 'day' } = req.query;
    if (!start || !end) return res.status(400).json({ error: 'start e end obrigatorios (YYYY-MM-DD)' });

    let groupBy, selectDate;
    if (granularity === 'month') {
      groupBy = "FORMAT(t.data_hora, N'yyyy-MM')";
      selectDate = "FORMAT(t.data_hora, N'yyyy-MM') AS data_ponto";
    } else {
      groupBy = 'CAST(t.data_hora AS DATE)';
      selectDate = 'CAST(t.data_hora AS DATE) AS data_ponto';
    }

    let where = `p.parametro_codigo IN ('prec','tp') AND t.data_hora BETWEEN @start AND @end`;
    let params = { start: new Date(start), end: new Date(end) };
    if (station_sk) {
      where += ` AND fm.estacao_sk = @station_sk`;
      params.station_sk = parseInt(station_sk);
    }

    const stmt = `
      SELECT ${selectDate}, e.estacao_sk, e.estacao_nome, e.sistema_origem,
             AVG(fm.valor) AS avg_valor, MAX(fm.valor) AS max_valor,
             SUM(fm.valor) AS sum_valor, COUNT(*) AS num_obs
      FROM gold.fact_medicao fm
      JOIN gold.dim_estacao e ON fm.estacao_sk = e.estacao_sk
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE ${where}
      GROUP BY ${groupBy}, e.estacao_sk, e.estacao_nome, e.sistema_origem
      ORDER BY data_ponto`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/levels', async (req, res) => {
  try {
    const { station_sk, start, end, granularity = 'day' } = req.query;
    if (!station_sk) return res.status(400).json({ error: 'station_sk obrigatorio' });
    if (!start || !end) return res.status(400).json({ error: 'start e end obrigatorios' });

    let groupBy, selectDate;
    if (granularity === 'month') {
      groupBy = "FORMAT(t.data_hora, N'yyyy-MM')";
      selectDate = "FORMAT(t.data_hora, N'yyyy-MM') AS data_ponto";
    } else {
      groupBy = 'CAST(t.data_hora AS DATE)';
      selectDate = 'CAST(t.data_hora AS DATE) AS data_ponto';
    }

    const stmt = `
      SELECT ${selectDate}, e.estacao_sk, e.estacao_nome, p.parametro_codigo, p.parametro_nome,
             AVG(fm.valor) AS avg_valor, MAX(fm.valor) AS max_valor, MIN(fm.valor) AS min_valor
      FROM gold.fact_medicao fm
      JOIN gold.dim_estacao e ON fm.estacao_sk = e.estacao_sk
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE p.parametro_codigo IN ('1843','1850','354895424')
        AND fm.estacao_sk = @station_sk
        AND t.data_hora BETWEEN @start AND @end
      GROUP BY ${groupBy}, e.estacao_sk, e.estacao_nome, p.parametro_codigo, p.parametro_nome
      ORDER BY data_ponto`;
    const r = await query(stmt, { station_sk: parseInt(station_sk), start: new Date(start), end: new Date(end) });
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/level-stations', async (req, res) => {
  try {
    const stmt = `
      SELECT e.estacao_sk, e.estacao_nome, e.sistema_origem, e.latitude, e.longitude
      FROM gold.dim_estacao e
      WHERE e.ativa = 1
        AND EXISTS (
          SELECT 1 FROM gold.fact_medicao fm
          JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
          WHERE fm.estacao_sk = e.estacao_sk
            AND p.parametro_codigo IN ('1843','1850','354895424')
        )
      ORDER BY e.estacao_nome`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/percentiles', async (req, res) => {
  try {
    const stmt = `
      SELECT rt.estacao_sk, e.estacao_nome, e.sistema_origem, rt.target_parametro,
             p.parametro_nome, p.unidade_medida,
             rt.p50, rt.p75, rt.p90, rt.p95, rt.p99, rt.max_hist,
             ft.p90 AS flood_p90, ft.p95 AS flood_p95, ft.p99 AS flood_p99,
             ft.mean_nivel, ft.std_nivel, ft.max_nivel
      FROM ctl.ml_risk_thresholds rt
      JOIN gold.dim_estacao e ON rt.estacao_sk = e.estacao_sk
      LEFT JOIN gold.dim_parametro p ON p.parametro_codigo = rt.target_parametro
      LEFT JOIN ctl.flood_thresholds ft ON rt.estacao_sk = ft.estacao_sk
      ORDER BY e.estacao_nome`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/flood-events', async (req, res) => {
  try {
    const { station_sk, year } = req.query;
    let where = [];
    let params = {};
    if (station_sk) { where.push('fe.estacao_sk = @station_sk'); params.station_sk = parseInt(station_sk); }
    if (year) { where.push('YEAR(fe.event_start) = @year'); params.year = parseInt(year); }
    const w = where.length ? 'WHERE ' + where.join(' AND ') : '';
    const stmt = `
      SELECT fe.event_id, e.estacao_sk, e.estacao_id, e.estacao_nome, e.latitude, e.longitude,
             b.bacia_nome, fe.event_start, fe.event_peak, fe.event_end,
             fe.duration_hours, fe.peak_value, fe.start_value, fe.end_value,
             fe.rise_rate, fe.antecedent_precip_6h, fe.antecedent_precip_24h,
             fe.antecedent_soil_moisture, fe.threshold_p95,
             CASE WHEN fe.peak_value >= fe.threshold_p95 * 1.5 THEN N'Grave'
                  WHEN fe.peak_value >= fe.threshold_p95 * 1.2 THEN N'Moderado'
                  ELSE N'Leve' END AS severidade
      FROM ml.ew_flood_events fe
      JOIN gold.dim_estacao e ON fe.estacao_sk = e.estacao_sk
      LEFT JOIN gold.dim_bacia b ON e.bacia_codigo = b.bacia_codigo
      ${w} ORDER BY fe.event_start DESC`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/precip-flow', async (req, res) => {
  try {
    const { station_sk, start, end } = req.query;
    if (!station_sk || !start || !end) return res.status(400).json({ error: 'station_sk, start, end obrigatorios' });

    const stmt = `
      SELECT t.data_hora, p.parametro_codigo, fm.valor
      FROM gold.fact_medicao fm
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE fm.estacao_sk = @station_sk
        AND p.parametro_codigo IN ('prec','1843')
        AND t.data_hora BETWEEN @start AND @end
      ORDER BY t.data_hora`;
    const r = await query(stmt, { station_sk: parseInt(station_sk), start: new Date(start), end: new Date(end) });
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/soil-saturation', async (req, res) => {
  try {
    const { station_sk, start, end } = req.query;
    if (!start || !end) return res.status(400).json({ error: 'start e end obrigatorios' });
    let params = { start: new Date(start), end: new Date(end) };
    let whereSta = '';
    if (station_sk) {
      whereSta = ' AND fm.estacao_sk = @station_sk';
      params.station_sk = parseInt(station_sk);
    }
    const stmt = `
      SELECT CAST(t.data_hora AS DATE) AS data_dia, e.estacao_sk, e.estacao_nome,
             AVG(CASE WHEN p.parametro_codigo='swvl1' THEN fm.valor END) AS swvl1,
             AVG(CASE WHEN p.parametro_codigo='swvl2' THEN fm.valor END) AS swvl2,
             AVG(CASE WHEN p.parametro_codigo='swvl3' THEN fm.valor END) AS swvl3,
             AVG(CASE WHEN p.parametro_codigo='swvl4' THEN fm.valor END) AS swvl4
      FROM gold.fact_medicao fm
      JOIN gold.dim_estacao e ON fm.estacao_sk = e.estacao_sk
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE p.parametro_codigo IN ('swvl1','swvl2','swvl3','swvl4')
        AND e.sistema_origem = 'ERA5'
        AND t.data_hora BETWEEN @start AND @end
        ${whereSta}
      GROUP BY CAST(t.data_hora AS DATE), e.estacao_sk, e.estacao_nome
      ORDER BY data_dia`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/map', async (req, res) => {
  try {
    const stmt = `
      SELECT e.estacao_sk, e.estacao_nome, e.sistema_origem,
             e.latitude, e.longitude,
             ISNULL(b.bacia_nome, N'Bacia do Mondego') AS bacia_nome,
             rc.nivel_inst_atual, rc.nivel_risco, rc.categoria_risco,
             rc.precip_accum_24h, rc.solo_saturacao_pct
      FROM gold.dim_estacao e
      LEFT JOIN ml.flood_risk_current rc ON e.estacao_sk = rc.estacao_sk
      LEFT JOIN gold.dim_bacia b ON e.bacia_codigo = b.bacia_codigo
      WHERE e.ativa = 1 AND e.latitude IS NOT NULL AND e.longitude IS NOT NULL
        AND e.sistema_origem = 'SNIRH'
      ORDER BY e.estacao_nome`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/reservoirs', async (req, res) => {
  try {
    const stmt = `
      SELECT e.estacao_sk, e.estacao_id, e.estacao_nome, e.latitude, e.longitude,
             b.bacia_nome
      FROM gold.dim_estacao e
      LEFT JOIN gold.dim_bacia b ON e.bacia_codigo = b.bacia_codigo
      WHERE e.estacao_sk IN (223,224,225,226,227,228,230,235)
      ORDER BY e.estacao_nome`;
    const stations = (await query(stmt)).recordset;
    const results = [];
    for (const s of stations) {
      const lr = await query(`
        SELECT TOP 1 t.data_hora AS ultima_leitura, fm.valor AS cota_atual
        FROM gold.fact_medicao fm
        JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
        WHERE fm.estacao_sk = @sk AND p.parametro_codigo = '354895424'
        ORDER BY t.data_hora DESC`, { sk: s.estacao_sk });
      results.push({ ...s, ultima_leitura: lr.recordset[0]?.ultima_leitura || null, cota_atual: lr.recordset[0]?.cota_atual || null });
    }
    res.json(results);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/export', async (req, res) => {
  try {
    const { station_sk, start, end, parametro_codigo, format } = req.query;
    if (!station_sk || !start || !end) return res.status(400).json({ error: 'station_sk, start, end obrigatorios' });
    const fmt = format || 'json';
    let paramFilter = '';
    let params = { station_sk: parseInt(station_sk), start: new Date(start), end: new Date(end) };
    if (parametro_codigo) {
      paramFilter = ` AND p.parametro_codigo = @parametro_codigo`;
      params.parametro_codigo = parametro_codigo;
    }
    const stmt = `
      SELECT t.data_hora, e.estacao_nome, p.parametro_nome, p.parametro_codigo, p.unidade_medida, fm.valor
      FROM gold.fact_medicao fm
      JOIN gold.dim_estacao e ON fm.estacao_sk = e.estacao_sk
      JOIN gold.dim_tempo t ON fm.tempo_sk = t.tempo_sk
      JOIN gold.dim_parametro p ON fm.parametro_sk = p.parametro_sk
      WHERE fm.estacao_sk = @station_sk AND t.data_hora BETWEEN @start AND @end ${paramFilter}
      ORDER BY t.data_hora`;
    const r = await query(stmt, params);

    if (fmt === 'csv') {
      const rows = r.recordset;
      if (rows.length === 0) return res.send('');
      const cols = Object.keys(rows[0]);
      const csv = [cols.join(';'), ...rows.map(r => cols.map(c => {
        const v = r[c];
        if (v instanceof Date) return v.toISOString();
        if (v === null || v === undefined) return '';
        return String(v);
      }).join(';'))].join('\r\n');
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename=export_${station_sk}.csv`);
      return res.send('\uFEFF' + csv);
    }
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

module.exports = router;
