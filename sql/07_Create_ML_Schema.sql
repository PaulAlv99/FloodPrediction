-- ============================================================================
-- 07_Create_ML_Schema.sql
-- ML Datamart: resultados, previsoes, risco actual — separados do gold
-- Schema: ml
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE ml.results (
    result_id        BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk       INT NOT NULL,
    tempo_sk         INT NOT NULL,
    km_cluster       INT,
    anomaly_score    FLOAT,
    is_anomaly       BIT,
    risco_precipitacao FLOAT,
    risco_hidrologico FLOAT,
    risco_solo FLOAT,
    risco_anomalia FLOAT,
    risco_flash_flood FLOAT,
    risco_river_flood FLOAT,
    risco_combinado FLOAT,
    nivel_risco INT,
    categoria_risco NVARCHAR(20),
    modelo_versao NVARCHAR(20) DEFAULT 'v4.0',
    data_criacao DATETIME2 DEFAULT GETDATE()
);
CREATE CLUSTERED INDEX IX_ml_results_sk ON ml.results (estacao_sk, tempo_sk);
GO

CREATE TABLE ml.model_metrics (
    metric_id INT IDENTITY(1,1) PRIMARY KEY,
    algoritmo NVARCHAR(50),
    metricas NVARCHAR(MAX),
    data_treino DATETIME2 DEFAULT GETDATE()
);
GO

CREATE TABLE ml.forecast_metrics (
    metric_id INT IDENTITY(1,1) PRIMARY KEY,
    estacao_sk INT,
    estacao_nome NVARCHAR(200),
    target_parametro NVARCHAR(50),
    horizon_hours INT,
    train_samples INT,
    test_samples INT,
    n_estimators INT,
    mae FLOAT,
    rmse FLOAT,
    r2 FLOAT,
    mean_actual FLOAT,
    mean_predicted FLOAT,
    data_treino DATETIME2 DEFAULT GETDATE()
);
GO

CREATE TABLE ml.forecast_predictions (
    prediction_id    BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk       INT NOT NULL,
    estacao_nome     NVARCHAR(200),
    target_parametro NVARCHAR(50) NOT NULL,
    horizon_hours    INT NOT NULL,
    predicted_value  FLOAT NOT NULL,
    actual_value     FLOAT NULL,
    prediction_time  DATETIME2 NOT NULL,
    target_time      DATETIME2 NOT NULL,
    modelo_versao    NVARCHAR(20) DEFAULT 'v4',
    data_criacao     DATETIME2 DEFAULT GETDATE()
);
CREATE CLUSTERED INDEX IX_forecast_pred_sk ON ml.forecast_predictions (estacao_sk, target_time DESC);
GO

CREATE TABLE ml.flood_risk_current (
    risk_id               BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk            INT NOT NULL,
    estacao_nome          NVARCHAR(200),
    cota_albuf_atual      FLOAT NULL,
    cota_ultima_h_atual   FLOAT NULL,
    cota_albuf_pred_1h    FLOAT NULL,
    cota_albuf_pred_6h    FLOAT NULL,
    cota_albuf_pred_12h   FLOAT NULL,
    cota_albuf_pred_24h   FLOAT NULL,
    cota_ultima_h_pred_1h FLOAT NULL,
    cota_ultima_h_pred_6h FLOAT NULL,
    cota_ultima_h_pred_12h FLOAT NULL,
    cota_ultima_h_pred_24h FLOAT NULL,
    precip_ipma_1h        FLOAT NULL,
    precip_ipma_24h       FLOAT NULL,
    temp_ipma_atual       FLOAT NULL,
    humidade_ipma_atual   FLOAT NULL,
    vento_ipma_atual      FLOAT NULL,
    pressao_ipma_atual    FLOAT NULL,
    nivel_inst_atual      FLOAT NULL,
    nivel_inst_pred_1h    FLOAT NULL,
    nivel_inst_pred_3h    FLOAT NULL,
    nivel_inst_pred_6h    FLOAT NULL,
    nivel_inst_pred_12h   FLOAT NULL,
    nivel_inst_pred_24h   FLOAT NULL,
    taxa_subida_1h        FLOAT NULL,
    taxa_subida_6h        FLOAT NULL,
    precip_accum_24h      FLOAT NULL,
    solo_saturacao_pct    FLOAT NULL,
    modelo_tipo           NVARCHAR(20) DEFAULT 'GLOBAL_HYBRID',
    nivel_risco           INT,
    categoria_risco       NVARCHAR(20),
    data_atualizacao      DATETIME2 DEFAULT GETDATE()
);
CREATE UNIQUE CLUSTERED INDEX IX_risk_current_sk ON ml.flood_risk_current (estacao_sk);
GO

PRINT 'ml.* criado: results, model_metrics, forecast_metrics, forecast_predictions, flood_risk_current';
GO
