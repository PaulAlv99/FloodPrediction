-- ============================================================================
-- 08_Create_Control_Tables.sql
-- Control layer: incremental load tracking, spatial mapping, model registry
-- Schema: ctl
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE ctl.incremental_load (
    ctl_id               INT IDENTITY(1,1) PRIMARY KEY,
    source_system        VARCHAR(50)  NOT NULL,
    silver_table         VARCHAR(200) NOT NULL,
    last_successful_load DATETIME2    NULL,
    rows_loaded          INT          DEFAULT 0,
    load_timestamp       DATETIME2    DEFAULT GETDATE(),
    status               VARCHAR(20)  DEFAULT 'PENDING',
    error_message        NVARCHAR(MAX) NULL
);

CREATE TABLE ctl.map_spatial_proximity (
    mapping_id        INT IDENTITY(1,1) PRIMARY KEY,
    source_station_sk INT    NOT NULL REFERENCES gold.dim_estacao(estacao_sk),
    target_station_sk INT    NOT NULL REFERENCES gold.dim_estacao(estacao_sk),
    distance_meters   FLOAT  NOT NULL,
    is_nearest        BIT    DEFAULT 1,
    rank_distance     INT    DEFAULT 1,
    data_criacao      DATETIME2 DEFAULT GETDATE()
);
CREATE INDEX IX_spatial_source ON ctl.map_spatial_proximity(source_station_sk, is_nearest);
GO

CREATE TABLE ctl.ml_models (
    model_id          INT IDENTITY(1,1) PRIMARY KEY,
    estacao_sk        INT NOT NULL,
    estacao_nome      NVARCHAR(200),
    target_parametro  NVARCHAR(50) NOT NULL,
    horizon_hours     INT NOT NULL,
    algorithm         NVARCHAR(50),
    model_path        NVARCHAR(500),
    scaler_path       NVARCHAR(500),
    feature_list_path NVARCHAR(500),
    n_features        INT,
    n_train_samples   INT,
    n_estimators      INT,
    mae               FLOAT,
    r2                FLOAT,
    versao            NVARCHAR(20),
    modelo_tipo       NVARCHAR(20) NULL,
    data_treino       DATETIME2 DEFAULT GETDATE()
);
GO

CREATE TABLE ctl.ml_risk_thresholds (
    threshold_id     INT IDENTITY(1,1) PRIMARY KEY,
    estacao_sk       INT NOT NULL,
    estacao_nome     NVARCHAR(200),
    target_parametro NVARCHAR(50) NOT NULL,
    p50              FLOAT,
    p75              FLOAT,
    p90              FLOAT,
    p95              FLOAT,
    p99              FLOAT,
    max_hist         FLOAT,
    data_calculo     DATETIME2 DEFAULT GETDATE()
);
CREATE UNIQUE INDEX IX_risk_thresh_sk ON ctl.ml_risk_thresholds (estacao_sk, target_parametro);
GO

CREATE TABLE ctl.ew_thresholds (
    threshold_id    INT IDENTITY(1,1)  PRIMARY KEY,
    estacao_sk      INT                NOT NULL,
    metric_name     NVARCHAR(50)       NOT NULL,
    warning_level   FLOAT              NULL,
    alert_level     FLOAT              NULL,
    critical_level  FLOAT              NULL,
    lookback_hours  INT                DEFAULT 6,
    data_calculo    DATETIME2          DEFAULT GETDATE(),
    CONSTRAINT UQ_ew_thresholds UNIQUE (estacao_sk, metric_name)
);
GO

CREATE TABLE ctl.alerts (
    alert_id            BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    alert_type          NVARCHAR(50)    NOT NULL,
    severity            NVARCHAR(20)    NOT NULL,
    estacao_sk          INT             NULL,
    detection_id        BIGINT          NULL,
    message             NVARCHAR(MAX)   NOT NULL,
    metric_value        FLOAT           NULL,
    threshold_value     FLOAT           NULL,
    run_id              UNIQUEIDENTIFIER NULL,
    status              NVARCHAR(20)    DEFAULT 'ACTIVE',
    created_at          DATETIME2       DEFAULT GETDATE(),
    expires_at          DATETIME2       NULL,
    acknowledged_by     NVARCHAR(100)   NULL,
    acknowledged_at     DATETIME2       NULL,
    resolved_at         DATETIME2       NULL,
    notification_sent   BIT             DEFAULT 0,
    notification_channel NVARCHAR(50)   NULL,
    notification_log    NVARCHAR(MAX)   NULL
);
CREATE CLUSTERED INDEX IX_alerts_status_created ON ctl.alerts (status, created_at DESC);
GO

CREATE TABLE ctl.alert_config (
    config_key      NVARCHAR(50)    PRIMARY KEY,
    config_value    NVARCHAR(MAX)   NOT NULL,
    description     NVARCHAR(200)   NULL
);
GO

INSERT INTO ctl.alert_config (config_key, config_value, description) VALUES
    ('webhook_url', '', 'Webhook endpoint URL (futuro)');
GO

PRINT 'ctl.* criado: incremental_load, map_spatial_proximity, ml_models, ml_risk_thresholds, ew_thresholds, alerts, alert_config, flood_thresholds';
GO

CREATE TABLE ml.flood_labels (
    id BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk INT NOT NULL,
    data_hora DATETIME2 NOT NULL,
    nivel FLOAT NOT NULL,
    nivel_p95 FLOAT NULL,
    flood_6h BIT DEFAULT 0,
    flood_12h BIT DEFAULT 0,
    flood_24h BIT DEFAULT 0
);
CREATE CLUSTERED INDEX IX_flood_labels ON ml.flood_labels (estacao_sk, data_hora);
GO

CREATE TABLE ml.lstm_predictions (
    id INT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk INT NOT NULL,
    ts_previsao DATETIME2 NOT NULL,
    horizonte_h INT NOT NULL,
    prob_cheia FLOAT NOT NULL,
    flood_alert BIT NOT NULL,
    threshold_used FLOAT NOT NULL,
    model_version NVARCHAR(20),
    created_at DATETIME DEFAULT GETDATE()
);
CREATE CLUSTERED INDEX IX_lstm_pred ON ml.lstm_predictions (estacao_sk, horizonte_h, ts_previsao);
GO

CREATE TABLE ctl.flood_thresholds (
    estacao_sk INT PRIMARY KEY,
    p90 FLOAT, p95 FLOAT, p99 FLOAT,
    mean_nivel FLOAT, std_nivel FLOAT, max_nivel FLOAT
);
GO

PRINT 'ml: flood_labels, lstm_predictions | ctl: flood_thresholds';
GO
