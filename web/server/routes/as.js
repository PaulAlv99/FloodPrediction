const { Router } = require('express');
const { query } = require('../db');
const { requireProfile } = require('../auth');

const router = Router();
router.use(requireProfile('AS'));

router.get('/data-sources', async (req, res) => {
  try {
    const stmt = `
      SELECT source_system, silver_table,
             COUNT(*) AS num_execucoes,
             SUM(CASE WHEN Status='OK' THEN Registros_Lidos ELSE 0 END) AS total_lidos,
             SUM(CASE WHEN Status='OK' THEN Registros_Escritos ELSE 0 END) AS total_escritos,
             SUM(CASE WHEN Status='OK' THEN Registros_Rejeitados ELSE 0 END) AS total_rejeitados,
             MAX(CASE WHEN Status='OK' THEN Dt_Fim END) AS ultima_carga_ok,
             MAX(Dt_Inicio) AS ultima_execucao,
             SUM(CASE WHEN Status='ERRO' THEN 1 ELSE 0 END) AS num_erros,
             CASE WHEN SUM(CASE WHEN Status='ERRO' THEN 1 ELSE 0 END) > 0 THEN N'Erro'
                  WHEN DATEDIFF(HOUR, MAX(CASE WHEN Status='OK' THEN Dt_Fim END), GETDATE()) > 24 THEN N'Atrasado'
                  ELSE N'Atualizado' END AS estado_fonte
      FROM (
        SELECT Fase + '->' + Passo AS source_system,
               REPLACE(REPLACE(Passo, 'API->Bronze ', ''), 'Bronze->Silver ', '') AS silver_table,
               Status, Registros_Lidos, Registros_Escritos, Registros_Rejeitados, Dt_Fim, Dt_Inicio
        FROM logs.ETL_Log
        WHERE Status <> 'INICIO'
      ) sub
      GROUP BY source_system, silver_table
      ORDER BY source_system`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/etl-history', async (req, res) => {
  try {
    const { date } = req.query;
    let where = '';
    let params = {};
    if (date) {
      where = 'WHERE CAST(Dt_Inicio AS DATE) = @date';
      params.date = date;
    }
    const stmt = `SELECT * FROM dbo.vw_etl_timeline ${where} ORDER BY Dt_Inicio DESC`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/thresholds', async (req, res) => {
  try {
    const stmt = `
      SELECT 'ml_risk_thresholds' AS tabela_origem, rt.estacao_sk, e.estacao_nome,
             rt.target_parametro AS parametro, rt.p50, rt.p75, rt.p90, rt.p95, rt.p99, rt.max_hist,
             NULL AS warning_level, NULL AS alert_level, NULL AS critical_level, rt.data_calculo
      FROM ctl.ml_risk_thresholds rt
      JOIN gold.dim_estacao e ON rt.estacao_sk = e.estacao_sk
      UNION ALL
      SELECT 'ew_thresholds' AS tabela_origem, ew.estacao_sk, e.estacao_nome,
             ew.metric_name AS parametro, NULL,NULL,NULL,NULL,NULL,NULL,
             ew.warning_level, ew.alert_level, ew.critical_level, ew.data_calculo
      FROM ctl.ew_thresholds ew
      JOIN gold.dim_estacao e ON ew.estacao_sk = e.estacao_sk
      UNION ALL
      SELECT 'flood_thresholds' AS tabela_origem, ft.estacao_sk, e.estacao_nome,
             'nivel_inst' AS parametro, NULL,NULL,ft.p90,ft.p95,ft.p99,ft.max_nivel,
             NULL,NULL,NULL, NULL
      FROM ctl.flood_thresholds ft
      JOIN gold.dim_estacao e ON ft.estacao_sk = e.estacao_sk
      ORDER BY tabela_origem, estacao_nome`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.put('/thresholds/flood/:estacao_sk', async (req, res) => {
  try {
    const { estacao_sk } = req.params;
    const { p90, p95, p99 } = req.body;
    const stmt = `
      IF EXISTS (SELECT 1 FROM ctl.flood_thresholds WHERE estacao_sk = @estacao_sk)
        UPDATE ctl.flood_thresholds SET p90=@p90, p95=@p95, p99=@p99 WHERE estacao_sk=@estacao_sk;
      ELSE
        INSERT INTO ctl.flood_thresholds (estacao_sk, p90, p95, p99, mean_nivel, std_nivel, max_nivel)
        VALUES (@estacao_sk, @p90, @p95, @p99, 0, 0, 0);`;
    await query(stmt, { estacao_sk: parseInt(estacao_sk), p90, p95, p99 });
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/quarantine', async (req, res) => {
  try {
    const stmt = `
      SELECT Fonte,
             LEFT(Motivo, CHARINDEX(':', Motivo + ':') - 1) AS Motivo_Curto,
             COUNT(*) AS total_registos,
             MIN(Dt_Quarentena) AS primeira_rejeicao,
             MAX(Dt_Quarentena) AS ultima_rejeicao
      FROM quarentena.ETL_Quarentena
      GROUP BY Fonte, LEFT(Motivo, CHARINDEX(':', Motivo + ':') - 1)
      ORDER BY Fonte, total_registos DESC`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/quarantine/detail', async (req, res) => {
  try {
    const { fonte } = req.query;
    let where = '';
    let params = {};
    if (fonte) { where = 'WHERE Fonte = @fonte'; params.fonte = fonte; }
    const stmt = `
      SELECT TOP 100 Id_Quarentena, Fonte, Motivo, Chave_Registo,
             Dados_Registo, Dt_Quarentena, Resolvido
      FROM quarentena.ETL_Quarentena ${where}
      ORDER BY Dt_Quarentena DESC`;
    const r = await query(stmt, params);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/latency', async (req, res) => {
  try {
    const stmt = `
      SELECT Passo AS source_system,
             MAX(Dt_Fim) AS ultima_carga_ok,
             DATEDIFF(MINUTE, MAX(Dt_Fim), GETDATE()) AS minutos_desde_ultima,
             SUM(Registros_Lidos) AS total_lidos,
             SUM(Registros_Escritos) AS total_escritos,
             CASE WHEN MAX(Status)='ERRO' THEN N'Erro'
                  WHEN DATEDIFF(MINUTE, MAX(Dt_Fim), GETDATE()) > 1440 THEN N'Atrasado'
                  ELSE N'OK' END AS estado
      FROM logs.ETL_Log
      WHERE Status <> 'INICIO'
      GROUP BY Passo
      ORDER BY Passo`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/models', async (req, res) => {
  try {
    const stmt = `
      SELECT m.model_id, m.estacao_sk, ISNULL(e.estacao_nome,'GLOBAL') AS estacao_nome,
             m.target_parametro, m.horizon_hours, m.algorithm, m.modelo_tipo,
             m.model_path, m.n_features, m.n_train_samples, m.n_estimators,
             m.mae, m.r2, m.versao, m.data_treino
      FROM ctl.ml_models m
      LEFT JOIN gold.dim_estacao e ON m.estacao_sk = e.estacao_sk
      ORDER BY m.data_treino DESC`;
    const r = await query(stmt);
    res.json(r.recordset);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

module.exports = router;
