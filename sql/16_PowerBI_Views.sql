-- ============================================================================
-- 16_PowerBI_Views.sql
-- 9 vistas desnormalizadas mantidas para Power BI futuro + Express API
-- Eliminadas 23 vistas (substituidas por queries directas na Express API)
-- ============================================================================

USE PreFlood_DW;
GO

-- ============================================================================
-- DROP 23 vistas eliminadas
-- ============================================================================

IF OBJECT_ID('dbo.vw_medicoes_por_estacao')   IS NOT NULL DROP VIEW dbo.vw_medicoes_por_estacao;
IF OBJECT_ID('dbo.vw_medicoes_por_mes')        IS NOT NULL DROP VIEW dbo.vw_medicoes_por_mes;
IF OBJECT_ID('dbo.vw_ah_eventos_cheia')        IS NOT NULL DROP VIEW dbo.vw_ah_eventos_cheia;
IF OBJECT_ID('dbo.vw_ah_saturacao_solo')       IS NOT NULL DROP VIEW dbo.vw_ah_saturacao_solo;
IF OBJECT_ID('dbo.vw_ah_niveis_albufeira')     IS NOT NULL DROP VIEW dbo.vw_ah_niveis_albufeira;
IF OBJECT_ID('dbo.vw_ah_proximidade_espacial') IS NOT NULL DROP VIEW dbo.vw_ah_proximidade_espacial;
IF OBJECT_ID('dbo.vw_ah_percentis_historicos') IS NOT NULL DROP VIEW dbo.vw_ah_percentis_historicos;
IF OBJECT_ID('dbo.vw_rpc_alertas_ativos')      IS NOT NULL DROP VIEW dbo.vw_rpc_alertas_ativos;
IF OBJECT_ID('dbo.vw_rpc_deteccao_precoce')    IS NOT NULL DROP VIEW dbo.vw_rpc_deteccao_precoce;
IF OBJECT_ID('dbo.vw_de_eventos_anual')        IS NOT NULL DROP VIEW dbo.vw_de_eventos_anual;
IF OBJECT_ID('dbo.vw_de_tendencia_climatica')  IS NOT NULL DROP VIEW dbo.vw_de_tendencia_climatica;
IF OBJECT_ID('dbo.vw_as_fontes_estado')        IS NOT NULL DROP VIEW dbo.vw_as_fontes_estado;
IF OBJECT_ID('dbo.vw_as_limiares')             IS NOT NULL DROP VIEW dbo.vw_as_limiares;
IF OBJECT_ID('dbo.vw_as_qualidade_dados')      IS NOT NULL DROP VIEW dbo.vw_as_qualidade_dados;
IF OBJECT_ID('dbo.vw_as_modelos_registo')      IS NOT NULL DROP VIEW dbo.vw_as_modelos_registo;
IF OBJECT_ID('dbo.vw_etl_resumo_diario')       IS NOT NULL DROP VIEW dbo.vw_etl_resumo_diario;
IF OBJECT_ID('dbo.vw_etl_resumo_historico')    IS NOT NULL DROP VIEW dbo.vw_etl_resumo_historico;
IF OBJECT_ID('dbo.vw_pbi_facts')               IS NOT NULL DROP VIEW dbo.vw_pbi_facts;
IF OBJECT_ID('dbo.vw_pbi_era5_daily')          IS NOT NULL DROP VIEW dbo.vw_pbi_era5_daily;
IF OBJECT_ID('dbo.vw_pbi_ml_results')          IS NOT NULL DROP VIEW dbo.vw_pbi_ml_results;
IF OBJECT_ID('dbo.vw_pbi_estacoes')            IS NOT NULL DROP VIEW dbo.vw_pbi_estacoes;
IF OBJECT_ID('dbo.vw_pbi_dim_tempo')           IS NOT NULL DROP VIEW dbo.vw_pbi_dim_tempo;
IF OBJECT_ID('dbo.vw_pbi_dim_parametro')       IS NOT NULL DROP VIEW dbo.vw_pbi_dim_parametro;
GO

-- ============================================================================
-- 1. vw_medicoes_detalhe — Star schema completo desnormalizado
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_medicoes_detalhe AS
SELECT
    fm.medicao_id,
    e.estacao_sk, e.estacao_id, e.estacao_nome, e.sistema_origem,
    e.latitude, e.longitude, e.bacia_codigo, b.bacia_nome, e.ativa,
    t.tempo_sk, t.data_hora, t.data, t.hora, t.ano, t.mes, t.dia,
    t.trimestre, t.semana_ano, t.dia_ano, t.dia_semana, t.dia_semana_nome,
    t.fim_de_semana, t.estacao_do_ano,
    p.parametro_sk, p.parametro_id, p.parametro_nome, p.parametro_codigo,
    p.categoria, p.unidade_medida, p.granularidade,
    fm.valor, fm.data_ingestao
FROM gold.fact_medicao fm
INNER JOIN gold.dim_estacao   e ON fm.estacao_sk   = e.estacao_sk
INNER JOIN gold.dim_tempo     t ON fm.tempo_sk      = t.tempo_sk
INNER JOIN gold.dim_parametro p ON fm.parametro_sk  = p.parametro_sk
LEFT  JOIN gold.dim_bacia     b ON e.bacia_codigo   = b.bacia_codigo;
GO

-- ============================================================================
-- 2. vw_risco_atual — Painel de risco corrente com cores
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_risco_atual AS
SELECT
    rc.estacao_sk, e.estacao_id, e.estacao_nome, e.sistema_origem,
    e.latitude, e.longitude, e.bacia_codigo, b.bacia_nome,
    rc.nivel_inst_atual,
    rc.nivel_inst_pred_1h, rc.nivel_inst_pred_3h,
    rc.nivel_inst_pred_6h, rc.nivel_inst_pred_12h, rc.nivel_inst_pred_24h,
    rc.taxa_subida_1h, rc.taxa_subida_6h,
    rc.precip_accum_24h, rc.solo_saturacao_pct,
    rc.modelo_tipo,
    rc.nivel_risco, rc.categoria_risco,
    rc.data_atualizacao,
    CASE WHEN rc.nivel_risco >= 4 THEN 1 ELSE 0 END AS is_high_risk,
    CASE
        WHEN rc.nivel_risco >= 5 THEN N'Vermelho Escuro'
        WHEN rc.nivel_risco = 4  THEN N'Vermelho'
        WHEN rc.nivel_risco = 3  THEN N'Laranja'
        WHEN rc.nivel_risco = 2  THEN N'Amarelo'
        WHEN rc.nivel_risco <= 1 THEN N'Verde'
    END AS risk_color
FROM ml.flood_risk_current rc
INNER JOIN gold.dim_estacao e ON rc.estacao_sk = e.estacao_sk
LEFT  JOIN gold.dim_bacia   b ON e.bacia_codigo = b.bacia_codigo;
GO

-- ============================================================================
-- 3. vw_risco_unpivot — Niveis por horizonte (para graficos)
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_risco_unpivot AS
SELECT
    estacao_sk,
    estacao_nome,
    latitude,
    longitude,
    bacia_nome,
    nivel_risco,
    categoria_risco,
    risk_color,
    data_atualizacao,
    horizonte,
    nivel_previsto
FROM (
    SELECT
        rc.estacao_sk,
        e.estacao_nome,
        e.latitude,
        e.longitude,
        ISNULL(b.bacia_nome, N'Bacia do Mondego') AS bacia_nome,
        rc.nivel_risco,
        rc.categoria_risco,
        CASE
            WHEN rc.nivel_risco >= 5 THEN N'Vermelho Escuro'
            WHEN rc.nivel_risco = 4  THEN N'Vermelho'
            WHEN rc.nivel_risco = 3  THEN N'Laranja'
            WHEN rc.nivel_risco = 2  THEN N'Amarelo'
            WHEN rc.nivel_risco <= 1 THEN N'Verde'
        END AS risk_color,
        rc.nivel_inst_atual,
        rc.nivel_inst_pred_1h,
        rc.nivel_inst_pred_3h,
        rc.nivel_inst_pred_6h,
        rc.nivel_inst_pred_12h,
        rc.nivel_inst_pred_24h,
        rc.data_atualizacao
    FROM ml.flood_risk_current rc
    INNER JOIN gold.dim_estacao e ON rc.estacao_sk = e.estacao_sk
    LEFT  JOIN gold.dim_bacia   b ON e.bacia_codigo = b.bacia_codigo
) src
UNPIVOT (
    nivel_previsto FOR horizonte IN (
        nivel_inst_atual,
        nivel_inst_pred_1h,
        nivel_inst_pred_3h,
        nivel_inst_pred_6h,
        nivel_inst_pred_12h,
        nivel_inst_pred_24h
    )
) AS unpvt;
GO

-- ============================================================================
-- 4. vw_previsoes_detalhe — Previsoes com metricas de erro
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_previsoes_detalhe AS
SELECT
    fp.prediction_id, fp.estacao_sk, e.estacao_id, e.estacao_nome, e.sistema_origem,
    e.latitude, e.longitude,
    fp.target_parametro, fp.horizon_hours, fp.predicted_value, fp.actual_value,
    CASE WHEN fp.actual_value IS NOT NULL THEN ABS(fp.predicted_value - fp.actual_value) ELSE NULL END AS absolute_error,
    CASE WHEN fp.actual_value IS NOT NULL AND fp.actual_value <> 0
         THEN ABS(fp.predicted_value - fp.actual_value) / ABS(fp.actual_value) * 100 ELSE NULL END AS percent_error,
    fp.prediction_time, fp.target_time, fp.modelo_versao, fp.data_criacao
FROM ml.forecast_predictions fp
INNER JOIN gold.dim_estacao e ON fp.estacao_sk = e.estacao_sk;
GO

-- ============================================================================
-- 5. vw_anomalias — Resultados ML anomalias desnormalizados
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_anomalias AS
SELECT
    mr.result_id, mr.estacao_sk, e.estacao_id, e.estacao_nome, e.sistema_origem,
    e.latitude, e.longitude, e.bacia_codigo, b.bacia_nome,
    mr.tempo_sk, t.data_hora, t.data, t.hora, t.ano, t.mes, t.dia,
    t.dia_semana_nome, t.estacao_do_ano,
    mr.km_cluster, mr.hdb_cluster, mr.anomaly_score,
    mr.risco_precipitacao, mr.risco_hidrologico, mr.risco_solo, mr.risco_anomalia,
    mr.risco_flash_flood, mr.risco_river_flood, mr.risco_combinado,
    mr.nivel_risco, mr.categoria_risco, mr.datahora_registro AS data_criacao
FROM ml.results mr
INNER JOIN gold.dim_estacao e ON mr.estacao_sk = e.estacao_sk
INNER JOIN gold.dim_tempo   t ON mr.tempo_sk   = t.tempo_sk
LEFT  JOIN gold.dim_bacia   b ON e.bacia_codigo = b.bacia_codigo
WHERE mr.is_anomaly = 1;
GO

-- ============================================================================
-- 6. vw_metricas_modelo — Qualidade modelos LightGBM
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_metricas_modelo AS
SELECT
    fm.metric_id,
    fm.estacao_sk,
    ISNULL(e.estacao_nome, N'Desconhecida') AS estacao_nome,
    fm.target_parametro,
    fm.horizon_hours,
    fm.train_samples,
    fm.test_samples,
    fm.n_estimators,
    fm.mae,
    fm.rmse,
    fm.r2,
    fm.mean_actual,
    fm.mean_predicted,
    fm.data_treino,
    CASE
        WHEN fm.r2 >= 0.8  THEN N'Bom'
        WHEN fm.r2 >= 0.5  THEN N'Moderado'
        WHEN fm.r2 >= 0.3  THEN N'Fraco'
        ELSE N'Muito Fraco'
    END AS qualidade_r2
FROM ml.forecast_metrics fm
LEFT JOIN gold.dim_estacao e ON fm.estacao_sk = e.estacao_sk;
GO

-- ============================================================================
-- 7. vw_pbi_lstm — Previsoes LSTM com nomes de estacao
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_pbi_lstm AS
SELECT
    l.estacao_sk,
    e.estacao_nome,
    l.ts_previsao,
    l.horizonte_h,
    l.prob_cheia,
    l.flood_alert,
    l.threshold_used,
    l.model_version,
    l.created_at
FROM ml.lstm_predictions l
JOIN gold.dim_estacao e ON l.estacao_sk = e.estacao_sk;
GO

-- ============================================================================
-- 8. vw_etl_timeline — Execucoes ETL com duracao e cor
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_etl_timeline AS
SELECT
    Execucao_Id,
    Fase,
    Passo,
    Status,
    Dt_Inicio,
    ISNULL(Dt_Fim, GETDATE()) AS Dt_Fim,
    DATEDIFF(SECOND, Dt_Inicio, ISNULL(Dt_Fim, GETDATE())) AS Duracao_Seg,
    Registros_Lidos,
    Registros_Escritos,
    Registros_Rejeitados,
    Mensagem,
    CASE Status
        WHEN 'OK' THEN N'#2E8B57'
        WHEN 'ERRO' THEN N'#DC143C'
        ELSE N'#808080'
    END AS status_cor
FROM logs.ETL_Log;
GO

-- ============================================================================
-- 9. vw_quarentena_resumo — Resumo rejeicoes por fonte/motivo
-- ============================================================================

CREATE OR ALTER VIEW dbo.vw_quarentena_resumo AS
SELECT
    Fonte,
    Motivo,
    COUNT(*) AS total_registos,
    MIN(Dt_Quarentena) AS primeira_rejeicao,
    MAX(Dt_Quarentena) AS ultima_rejeicao
FROM quarentena.ETL_Quarentena
GROUP BY Fonte, Motivo;
GO

-- ============================================================================
-- Covering index para queries da Express API
-- ============================================================================

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('gold.fact_medicao') AND name = 'IX_fact_cover')
CREATE NONCLUSTERED INDEX IX_fact_cover
ON gold.fact_medicao(estacao_sk, tempo_sk, parametro_sk)
INCLUDE (valor);
GO

PRINT 'Vistas finais: 9 mantidas, 23 eliminadas. Covering index criado.';
GO
