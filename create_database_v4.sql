-- ============================================================================
-- create_database_v4.sql
-- Standalone DDL: creates the full PreFlood_DW database
-- Includes tables, logging, ML schema, control, SPs, and seed data
-- Generated from 01-08, 12-14, 99
-- ============================================================================

-- ============================================================================
-- PreFlood_DW v4.0 — Data Lakehouse (brz + silver + gold + logs + ml + quarentena + ctl)
-- Bacia do Mondego — Hydro-meteorological Flood Prediction
-- ============================================================================
--
-- Schemas:
--   brz        -> Bronze (raw ingestion, all NVARCHAR, audit columns)
--   silver     -> Silver (typed, cleaned, validated — IS the staging/silver layer)
--   gold       -> Gold star schema (dims + facts ONLY)
--   logs       -> Structured ETL logging (ETL_Log, Ficheiros_Processados, SPs)
--   ml         -> ML datamart (results, predictions, risk — separated from gold)
--   quarentena -> Rejected records with reason
--   ctl        -> Control (incremental load, spatial mapping, model registry)
--
-- Principles:
--   sistema_origem lives in dims ONLY (not in fact)
--   IPMA temp != ERA5 temp -> separate rows in dim_parametro
--   bacia_codigo: SNIRH=47 (download filter), ERA5=47 (imputed), IPMA=NULL
--   Logging via logs.sp_ETL_LogInicio/LogFim/RegistarErro
--   Rejected records -> quarentena.ETL_Quarentena
-- ============================================================================

USE master;
GO
IF EXISTS (SELECT 1 FROM sys.databases WHERE name = 'PreFlood_DW')
BEGIN
    ALTER DATABASE [PreFlood_DW] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE [PreFlood_DW];
END
CREATE DATABASE [PreFlood_DW];
GO
USE [PreFlood_DW];
GO

CREATE SCHEMA brz;
GO
CREATE SCHEMA silver;
GO
CREATE SCHEMA gold;
GO
CREATE SCHEMA logs;
GO
CREATE SCHEMA ml;
GO
CREATE SCHEMA quarentena;
GO
CREATE SCHEMA ctl;
GO

PRINT 'PreFlood_DW v4.0 — 7 schemas criados: brz, stg, gold, logs, ml, quarentena, ctl';
GO

-- ============================================================================
-- 02_Create_Bronze_Tables.sql
-- Bronze layer: raw ingestion tables (all NVARCHAR, audit columns)
-- Schema: brz
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE brz.ipma_obs (
    data_hora      NVARCHAR(30)   NOT NULL,
    id_estacao     NVARCHAR(20)   NOT NULL,
    temperatura    NVARCHAR(20)   NULL,
    humidade       NVARCHAR(20)   NULL,
    pressao        NVARCHAR(20)   NULL,
    vento_km       NVARCHAR(20)   NULL,
    vento_ms       NVARCHAR(20)   NULL,
    vento_dir      NVARCHAR(20)   NULL,
    precipitacao   NVARCHAR(20)   NULL,
    radiacao       NVARCHAR(20)   NULL,
    _arquivo       NVARCHAR(500)  NULL,
    _run_id        UNIQUEIDENTIFIER NULL,
    _dt_carga      DATETIME2      DEFAULT GETDATE()
);

CREATE TABLE brz.ipma_est (
    id_estacao     NVARCHAR(50)   NOT NULL,
    nome           NVARCHAR(200)  NULL,
    latitude       NVARCHAR(50)   NULL,
    longitude      NVARCHAR(50)   NULL,
    _arquivo       NVARCHAR(500)  NULL,
    _run_id        UNIQUEIDENTIFIER NULL,
    _dt_carga      DATETIME2      DEFAULT GETDATE()
);

CREATE TABLE brz.snirh_obs (
    data_hora      NVARCHAR(30)   NOT NULL,
    id_estacao     NVARCHAR(20)   NOT NULL,
    id_parametro   NVARCHAR(20)   NOT NULL,
    valor          NVARCHAR(30)   NULL,
    _arquivo       NVARCHAR(500)  NULL,
    _run_id        UNIQUEIDENTIFIER NULL,
    _dt_carga      DATETIME2      DEFAULT GETDATE()
);

CREATE TABLE brz.snirh_est (
    id_estacao     NVARCHAR(50)   NOT NULL,
    nome           NVARCHAR(200)  NULL,
    latitude       NVARCHAR(50)   NULL,
    longitude      NVARCHAR(50)   NULL,
    activa         NVARCHAR(5)    NULL,
    _arquivo       NVARCHAR(500)  NULL,
    _run_id        UNIQUEIDENTIFIER NULL,
    _dt_carga      DATETIME2      DEFAULT GETDATE()
);

CREATE TABLE brz.era5_obs (
    data_hora        NVARCHAR(30)   NOT NULL,
    latitude         NVARCHAR(20)   NULL,
    longitude        NVARCHAR(20)   NULL,
    temperatura_2m   NVARCHAR(20)   NULL,
    precipitacao     NVARCHAR(20)   NULL,
    solo_l1          NVARCHAR(20)   NULL,
    solo_l2          NVARCHAR(20)   NULL,
    solo_l3          NVARCHAR(20)   NULL,
    solo_l4          NVARCHAR(20)   NULL,
    pressao_superf   NVARCHAR(20)   NULL,
    _arquivo         NVARCHAR(500)  NULL,
    _run_id          UNIQUEIDENTIFIER NULL,
    _dt_carga        DATETIME2      DEFAULT GETDATE()
);

GO

PRINT 'Bronze tables criados: brz.ipma_obs, brz.ipma_est, brz.snirh_obs, brz.snirh_est, brz.era5_obs';
GO

-- ============================================================================
-- 03_Create_Silver_Tables.sql
-- Silver layer (stg schema): typed, cleaned, validated data
-- stg IS the silver layer — no separate staging
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE silver.ipma_stations (
    station_id     VARCHAR(50)   NOT NULL,
    station_name   NVARCHAR(200) NULL,
    latitude       FLOAT         NULL,
    longitude      FLOAT         NULL,
    bacia_codigo   BIGINT        DEFAULT 47,
    ingestion_ts   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_silver_ipma_st PRIMARY KEY (station_id)
);

CREATE TABLE silver.ipma_observations (
    observation_datetime DATETIME2     NOT NULL,
    station_id           VARCHAR(50)   NOT NULL,
    parametro_id         INT           NOT NULL,
    valor                FLOAT         NOT NULL,
    ingestion_ts         DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_stg_ipma_obs PRIMARY KEY NONCLUSTERED (observation_datetime, station_id, parametro_id)
);
CREATE CLUSTERED INDEX IX_silver_ipma_obs_dt ON silver.ipma_observations(observation_datetime);

CREATE TABLE silver.snirh_stations (
    station_id     VARCHAR(50)   NOT NULL,
    station_name   NVARCHAR(200) NULL,
    latitude       FLOAT         NULL,
    longitude      FLOAT         NULL,
    bacia_codigo   BIGINT        DEFAULT 47,
    ingestion_ts   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_stg_snirh_st PRIMARY KEY (station_id)
);

CREATE TABLE silver.snirh_observations (
    observation_datetime DATETIME2     NOT NULL,
    station_id           VARCHAR(50)   NOT NULL,
    parametro_id         BIGINT        NOT NULL,
    valor                FLOAT         NOT NULL,
    granularidade        VARCHAR(20)   NULL,
    ingestion_ts         DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_silver_snirh_obs PRIMARY KEY NONCLUSTERED (observation_datetime, station_id, parametro_id)
);
CREATE CLUSTERED INDEX IX_silver_snirh_obs_dt ON silver.snirh_observations(observation_datetime);

CREATE TABLE silver.era5_locations (
    location_id    INT IDENTITY(1,1) PRIMARY KEY,
    location_label NVARCHAR(200) NOT NULL,
    latitude       FLOAT         NOT NULL,
    longitude      FLOAT         NOT NULL,
    ingestion_ts   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT UQ_stg_era5_loc UNIQUE (latitude, longitude)
);

CREATE TABLE silver.era5_observations (
    observation_datetime   DATETIME2 NOT NULL,
    location_id            INT       NOT NULL REFERENCES silver.era5_locations(location_id),
    temperature_2m         FLOAT NULL,
    dewpoint_2m            FLOAT NULL,
    precipitation_total    FLOAT NULL,
    surface_pressure       FLOAT NULL,
    skin_temperature       FLOAT NULL,
    snow_depth             FLOAT NULL,
    soil_temperature_l1    FLOAT NULL,
    soil_temperature_l2    FLOAT NULL,
    soil_temperature_l3    FLOAT NULL,
    soil_temperature_l4    FLOAT NULL,
    soil_water_level_1     FLOAT NULL,
    soil_water_level_2     FLOAT NULL,
    soil_water_level_3     FLOAT NULL,
    soil_water_level_4     FLOAT NULL,
    wind_u_10m             FLOAT NULL,
    wind_v_10m             FLOAT NULL,
    solar_radiation_down   FLOAT NULL,
    thermal_radiation_down FLOAT NULL,
    ingestion_ts           DATETIME2 DEFAULT GETDATE(),
    CONSTRAINT PK_stg_era5_obs PRIMARY KEY NONCLUSTERED (observation_datetime, location_id)
);
GO

PRINT 'Silver (stg) tables criados';
GO

-- ============================================================================
-- 04_Create_Gold_Tables.sql
-- Gold layer: star schema — dims + facts ONLY (ML tables in ml schema)
-- Schema: gold
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE gold.dim_bacia (
    bacia_codigo   BIGINT         PRIMARY KEY,
    bacia_nome     NVARCHAR(100)  NOT NULL
);

CREATE TABLE gold.dim_estacao (
    estacao_sk     INT IDENTITY(1,1) PRIMARY KEY,
    estacao_id     VARCHAR(50)   NOT NULL,
    estacao_nome   NVARCHAR(200) NOT NULL,
    sistema_origem VARCHAR(20)   NOT NULL,
    latitude       FLOAT         NULL,
    longitude      FLOAT         NULL,
    bacia_codigo   BIGINT        NULL REFERENCES gold.dim_bacia(bacia_codigo),
    ativa          BIT           DEFAULT 1,
    data_criacao   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT UQ_estacao UNIQUE (estacao_id, sistema_origem)
);
CREATE INDEX IX_estacao_origem ON gold.dim_estacao(sistema_origem);
CREATE INDEX IX_estacao_coords ON gold.dim_estacao(latitude, longitude) WHERE latitude IS NOT NULL;

CREATE TABLE gold.dim_tempo (
    tempo_sk        INT IDENTITY(1,1) PRIMARY KEY,
    data_hora       DATETIME2     NOT NULL,
    data            DATE          NOT NULL,
    hora            INT           NOT NULL,
    ano             SMALLINT      NOT NULL,
    mes             TINYINT       NOT NULL,
    dia             TINYINT       NOT NULL,
    trimestre       TINYINT       NOT NULL,
    semana_ano      TINYINT       NOT NULL,
    dia_ano         SMALLINT      NOT NULL,
    dia_semana      TINYINT       NOT NULL,
    dia_semana_nome NVARCHAR(20)  NOT NULL,
    fim_de_semana   BIT           NOT NULL,
    estacao_do_ano  NVARCHAR(20)  NOT NULL,
    CONSTRAINT UQ_tempo UNIQUE (data_hora)
);

CREATE TABLE gold.dim_parametro (
    parametro_sk     INT IDENTITY(1,1) PRIMARY KEY,
    parametro_id     INT            NOT NULL,
    parametro_nome   NVARCHAR(200)  NOT NULL,
    parametro_codigo VARCHAR(50)    NOT NULL,
    categoria        NVARCHAR(50)   NOT NULL,
    unidade_medida   NVARCHAR(30)   NOT NULL,
    sistema_origem   VARCHAR(20)    NOT NULL,
    granularidade    VARCHAR(20)    NULL,
    CONSTRAINT UQ_parametro UNIQUE (parametro_id, sistema_origem)
);

CREATE TABLE gold.fact_medicao (
    medicao_id    BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk    INT       NOT NULL REFERENCES gold.dim_estacao(estacao_sk),
    tempo_sk      INT       NOT NULL REFERENCES gold.dim_tempo(tempo_sk),
    parametro_sk  INT       NOT NULL REFERENCES gold.dim_parametro(parametro_sk),
    valor         FLOAT     NOT NULL,
    data_ingestao DATETIME2 DEFAULT GETDATE(),
    CONSTRAINT UQ_medicao UNIQUE (estacao_sk, tempo_sk, parametro_sk)
);
CREATE CLUSTERED INDEX IX_fact_tempo ON gold.fact_medicao(tempo_sk, estacao_sk);
CREATE NONCLUSTERED INDEX IX_fact_param ON gold.fact_medicao(parametro_sk);

GO

PRINT 'Gold tables criados: 4 dims + 1 fact (sem tabelas ML — estao em ml.*)';
GO

-- ============================================================================
-- 05_Create_Logging.sql
-- Logging framework (padrao Ficha2SETCD adaptado a PreFlood_DW)
-- Schema: logs
-- ============================================================================

USE PreFlood_DW;
GO

IF OBJECT_ID('logs.ETL_Log') IS NOT NULL DROP TABLE logs.ETL_Log;
GO

CREATE TABLE logs.ETL_Log (
    Id_Log              INT IDENTITY(1,1) PRIMARY KEY,
    Execucao_Id         UNIQUEIDENTIFIER NOT NULL,
    Fase                VARCHAR(50)  NOT NULL,
    Passo               VARCHAR(100) NOT NULL,
    Status              VARCHAR(20)  NOT NULL,
    Registros_Lidos     INT NULL,
    Registros_Escritos  INT NULL,
    Registros_Rejeitados INT NULL,
    Dt_Inicio           DATETIME NOT NULL,
    Dt_Fim              DATETIME NULL,
    Duracao_Segundos    INT NULL,
    Mensagem            VARCHAR(500) NULL,
    Erro_Numero         INT NULL,
    Erro_Severidade     INT NULL
);
GO

CREATE INDEX IX_ETL_Log_Exec ON logs.ETL_Log(Execucao_Id);
CREATE INDEX IX_ETL_Log_Status ON logs.ETL_Log(Status);
CREATE INDEX IX_ETL_Log_Data ON logs.ETL_Log(Dt_Inicio);
GO

IF OBJECT_ID('logs.Ficheiros_Processados') IS NOT NULL DROP TABLE logs.Ficheiros_Processados;
GO

CREATE TABLE logs.Ficheiros_Processados (
    Id                  INT IDENTITY(1,1) PRIMARY KEY,
    Execucao_Id         UNIQUEIDENTIFIER NOT NULL,
    CaminhoFicheiro     VARCHAR(500) NOT NULL,
    NomeFicheiro        VARCHAR(200) NOT NULL,
    TipoFicheiro        VARCHAR(20)  NOT NULL,
    RegistosLidos       INT NULL,
    Status              VARCHAR(20)  NOT NULL,
    Dt_Processamento    DATETIME DEFAULT GETDATE()
);
GO

CREATE OR ALTER PROCEDURE logs.sp_ETL_LogInicio
    @Execucao_Id UNIQUEIDENTIFIER,
    @Fase        VARCHAR(50),
    @Passo       VARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO logs.ETL_Log (Execucao_Id, Fase, Passo, Status, Dt_Inicio)
    VALUES (@Execucao_Id, @Fase, @Passo, 'INICIO', GETDATE());
END;
GO

CREATE OR ALTER PROCEDURE logs.sp_ETL_LogFim
    @Execucao_Id  UNIQUEIDENTIFIER,
    @Fase         VARCHAR(50),
    @Passo        VARCHAR(100),
    @Status       VARCHAR(20),
    @Lidos        INT = NULL,
    @Escritos     INT = NULL,
    @Rejeitados   INT = NULL,
    @Mensagem     VARCHAR(500) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE logs.ETL_Log
    SET Status              = @Status,
        Registros_Lidos     = @Lidos,
        Registros_Escritos  = @Escritos,
        Registros_Rejeitados = @Rejeitados,
        Dt_Fim              = GETDATE(),
        Duracao_Segundos    = DATEDIFF(SECOND, Dt_Inicio, GETDATE()),
        Mensagem            = @Mensagem
    WHERE Execucao_Id = @Execucao_Id
      AND Fase = @Fase
      AND Passo = @Passo
      AND Status = 'INICIO';
END;
GO

CREATE OR ALTER PROCEDURE logs.sp_ETL_RegistarErro
    @Execucao_Id    UNIQUEIDENTIFIER,
    @Fase           VARCHAR(50),
    @Passo          VARCHAR(100),
    @Erro_Numero    INT = NULL,
    @Erro_Mensagem  NVARCHAR(4000) = NULL,
    @Erro_Severidade INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO logs.ETL_Log (Execucao_Id, Fase, Passo, Status, Dt_Inicio, Dt_Fim,
                              Mensagem, Erro_Numero, Erro_Severidade)
    VALUES (@Execucao_Id, @Fase, @Passo, 'ERRO', GETDATE(), GETDATE(),
            LEFT(ISNULL(@Erro_Mensagem, ''), 500), @Erro_Numero, @Erro_Severidade);
END;
GO

CREATE SYNONYM dbo.sp_ETL_LogInicio FOR logs.sp_ETL_LogInicio;
CREATE SYNONYM dbo.sp_ETL_LogFim FOR logs.sp_ETL_LogFim;
CREATE SYNONYM dbo.sp_ETL_RegistarErro FOR logs.sp_ETL_RegistarErro;
GO

PRINT 'logs.* criado: ETL_Log, Ficheiros_Processados, 3 SPs, 3 synonyms';
GO

-- ============================================================================
-- 06_Create_Quarentena.sql
-- Quarentena: registos rejeitados pela validacao Bronze->Silver
-- Schema: quarentena
-- ============================================================================

USE PreFlood_DW;
GO

IF OBJECT_ID('quarentena.ETL_Quarentena') IS NOT NULL DROP TABLE quarentena.ETL_Quarentena;
GO

CREATE TABLE quarentena.ETL_Quarentena (
    Id_Quarentena   INT IDENTITY(1,1) PRIMARY KEY,
    Execucao_Id     UNIQUEIDENTIFIER NOT NULL,
    Fonte           VARCHAR(50)     NOT NULL,
    Chave_Registo   VARCHAR(200)    NULL,
    Dados_Registo   NVARCHAR(MAX)   NULL,
    Motivo          VARCHAR(500)    NOT NULL,
    Dt_Quarentena   DATETIME DEFAULT GETDATE(),
    Resolvido       BIT DEFAULT 0
);
GO

CREATE INDEX IX_Quarentena_Fonte ON quarentena.ETL_Quarentena(Fonte);
CREATE INDEX IX_Quarentena_Data ON quarentena.ETL_Quarentena(Dt_Quarentena);
GO

PRINT 'quarentena.ETL_Quarentena criado';
GO

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

CREATE TABLE ml.ew_flood_events (
    event_id                 BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk               INT          NOT NULL,
    event_start              DATETIME2    NOT NULL,
    event_peak               DATETIME2    NULL,
    event_end                DATETIME2    NOT NULL,
    duration_hours           INT          NOT NULL,
    peak_value               FLOAT        NOT NULL,
    rise_rate                FLOAT        NULL,
    start_value              FLOAT        NOT NULL,
    end_value                FLOAT        NOT NULL,
    antecedent_precip_6h     FLOAT        NULL,
    antecedent_precip_24h    FLOAT        NULL,
    antecedent_soil_moisture FLOAT        NULL,
    threshold_p95            FLOAT        NOT NULL
);
CREATE CLUSTERED INDEX IX_ew_flood_events_sk ON ml.ew_flood_events (estacao_sk, event_start DESC);
CREATE NONCLUSTERED INDEX IX_ew_flood_events_peak ON ml.ew_flood_events (estacao_sk, peak_value DESC);
GO

CREATE TABLE ml.ew_detections (
    detection_id              BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk                INT          NOT NULL,
    detection_ts              DATETIME2    NOT NULL,
    layer1_percentile_score   FLOAT        NULL,
    layer1_details            NVARCHAR(500) NULL,
    layer2_sequence_score     FLOAT        NULL,
    layer2_details            NVARCHAR(500) NULL,
    layer3_combined_score     FLOAT        NULL,
    lead_time_hours           FLOAT        NULL
);
CREATE CLUSTERED INDEX IX_ew_detections_sk ON ml.ew_detections (estacao_sk, detection_ts DESC);
GO

PRINT 'ml.* criado: results, model_metrics, forecast_metrics, forecast_predictions, flood_risk_current, ew_flood_events, ew_detections';
GO

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

PRINT 'ctl.* criado: incremental_load, map_spatial_proximity, ml_models, ml_risk_thresholds, ew_thresholds, alerts, alert_config';
GO

-- ============================================================================
-- 12_Load_Dim_Tempo.sql
-- Popula gold.dim_tempo com datas/horas das observacoes Silver
-- ============================================================================

USE PreFlood_DW;
GO

CREATE OR ALTER PROCEDURE ctl.usp_popular_dim_tempo
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @minDt DATETIME2, @maxDt DATETIME2;

    SELECT @minDt = MIN(observation_datetime) FROM (
        SELECT observation_datetime FROM silver.ipma_observations
        UNION ALL
        SELECT observation_datetime FROM silver.snirh_observations
        UNION ALL
        SELECT observation_datetime FROM silver.era5_observations
    ) x;

    SELECT @maxDt = MAX(observation_datetime) FROM (
        SELECT observation_datetime FROM silver.ipma_observations
        UNION ALL
        SELECT observation_datetime FROM silver.snirh_observations
        UNION ALL
        SELECT observation_datetime FROM silver.era5_observations
    ) x;

    IF @minDt IS NULL RETURN;

    DECLARE @d DATETIME2 = DATEADD(HOUR, DATEDIFF(HOUR, 0, @minDt), 0);

    WHILE @d <= @maxDt
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM gold.dim_tempo WHERE data_hora = @d)
        BEGIN
            INSERT INTO gold.dim_tempo (data_hora, data, hora, ano, mes, dia, trimestre, semana_ano, dia_ano, dia_semana, dia_semana_nome, fim_de_semana, estacao_do_ano)
            SELECT
                @d,
                CAST(@d AS DATE),
                DATEPART(HOUR, @d),
                DATEPART(YEAR, @d),
                DATEPART(MONTH, @d),
                DATEPART(DAY, @d),
                DATEPART(QUARTER, @d),
                DATEPART(WEEK, @d),
                DATEPART(DAYOFYEAR, @d),
                DATEPART(WEEKDAY, @d),
                DATENAME(WEEKDAY, @d),
                CASE WHEN DATEPART(WEEKDAY, @d) IN (1,7) THEN 1 ELSE 0 END,
                CASE
                    WHEN DATEPART(MONTH, @d) IN (3,4,5) THEN N'Primavera'
                    WHEN DATEPART(MONTH, @d) IN (6,7,8) THEN N'Verao'
                    WHEN DATEPART(MONTH, @d) IN (9,10,11) THEN N'Outono'
                    ELSE N'Inverno'
                END;
        END
        SET @d = DATEADD(HOUR, 1, @d);
    END
END;
GO

DECLARE @ExecId UNIQUEIDENTIFIER = NEWID();
EXEC logs.sp_ETL_LogInicio @ExecId, 'LOAD', 'Load Dim Tempo';
EXEC ctl.usp_popular_dim_tempo;
EXEC logs.sp_ETL_LogFim @ExecId, 'LOAD', 'Load Dim Tempo', 'OK';
GO

-- ============================================================================
-- 13_Load_Dim_Estacao.sql
-- MERGE IPMA + SNIRH + ERA5 stations into gold.dim_estacao
-- ============================================================================

USE PreFlood_DW;
GO

CREATE OR ALTER PROCEDURE ctl.usp_merge_dim_estacao_ipma
AS
BEGIN
    SET NOCOUNT ON;
    MERGE gold.dim_estacao AS t
    USING (SELECT station_id, station_name, latitude, longitude, bacia_codigo FROM silver.ipma_stations) AS s
    ON t.estacao_id = s.station_id AND t.sistema_origem = 'IPMA'
    WHEN MATCHED THEN UPDATE SET estacao_nome = ISNULL(s.station_name, t.estacao_nome),
        latitude = ISNULL(s.latitude, t.latitude), longitude = ISNULL(s.longitude, t.longitude),
        bacia_codigo = ISNULL(s.bacia_codigo, t.bacia_codigo)
    WHEN NOT MATCHED THEN
        INSERT (estacao_id, estacao_nome, sistema_origem, latitude, longitude, bacia_codigo)
        VALUES (s.station_id, ISNULL(s.station_name, ''), 'IPMA', s.latitude, s.longitude, s.bacia_codigo);
END;
GO

CREATE OR ALTER PROCEDURE ctl.usp_merge_dim_estacao_snirh
AS
BEGIN
    SET NOCOUNT ON;
    MERGE gold.dim_estacao AS t
    USING (SELECT station_id, station_name, latitude, longitude, bacia_codigo FROM silver.snirh_stations) AS s
    ON t.estacao_id = s.station_id AND t.sistema_origem = 'SNIRH'
    WHEN MATCHED THEN UPDATE SET estacao_nome = ISNULL(s.station_name, t.estacao_nome),
        latitude = ISNULL(s.latitude, t.latitude), longitude = ISNULL(s.longitude, t.longitude),
        bacia_codigo = ISNULL(s.bacia_codigo, t.bacia_codigo)
    WHEN NOT MATCHED THEN
        INSERT (estacao_id, estacao_nome, sistema_origem, latitude, longitude, bacia_codigo)
        VALUES (s.station_id, ISNULL(s.station_name, ''), 'SNIRH', s.latitude, s.longitude, s.bacia_codigo);
END;
GO

CREATE OR ALTER PROCEDURE ctl.usp_criar_estacoes_era5
AS
BEGIN
    SET NOCOUNT ON;
    MERGE gold.dim_estacao AS t
    USING (
        SELECT CAST(l.location_id AS VARCHAR(50)) AS location_id, l.location_label, l.latitude, l.longitude
        FROM silver.era5_locations l
    ) AS s
    ON t.estacao_id = s.location_id AND t.sistema_origem = 'ERA5'
    WHEN MATCHED THEN UPDATE SET estacao_nome = s.location_label,
        latitude = s.latitude, longitude = s.longitude
    WHEN NOT MATCHED THEN
        INSERT (estacao_id, estacao_nome, sistema_origem, latitude, longitude, bacia_codigo)
        VALUES (s.location_id, s.location_label, 'ERA5', s.latitude, s.longitude, 47);
END;
GO

DECLARE @ExecId UNIQUEIDENTIFIER = NEWID();
EXEC logs.sp_ETL_LogInicio @ExecId, 'LOAD', 'Load Dim Estacao';
EXEC ctl.usp_merge_dim_estacao_ipma;
EXEC ctl.usp_merge_dim_estacao_snirh;
EXEC ctl.usp_criar_estacoes_era5;
EXEC logs.sp_ETL_LogFim @ExecId, 'LOAD', 'Load Dim Estacao', 'OK';
GO

-- ============================================================================
-- 14_Load_Fact_Medicao.sql
-- INSERT IPMA + SNIRH + ERA5 facts into gold.fact_medicao
-- ============================================================================

USE PreFlood_DW;
GO

CREATE OR ALTER PROCEDURE ctl.usp_merge_ipma
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.valor
    FROM silver.ipma_observations o
    INNER JOIN gold.dim_estacao e ON o.station_id = e.estacao_id AND e.sistema_origem = 'IPMA'
    INNER JOIN gold.dim_parametro p ON o.parametro_id = p.parametro_id AND p.sistema_origem = 'IPMA'
    CROSS APPLY (
        SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime
    ) t
    WHERE NOT EXISTS (
        SELECT 1 FROM gold.fact_medicao f
        WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk
    );
END;
GO

CREATE OR ALTER PROCEDURE ctl.usp_merge_snirh
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.valor
    FROM silver.snirh_observations o
    INNER JOIN gold.dim_estacao e ON o.station_id = e.estacao_id AND e.sistema_origem = 'SNIRH'
    INNER JOIN gold.dim_parametro p ON CAST(o.parametro_id AS VARCHAR(50)) = p.parametro_codigo AND p.sistema_origem = 'SNIRH'
    CROSS APPLY (
        SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime
    ) t
    WHERE NOT EXISTS (
        SELECT 1 FROM gold.fact_medicao f
        WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk
    );
END;
GO

CREATE OR ALTER PROCEDURE ctl.usp_merge_era5
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.temperature_2m
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 51 AND sistema_origem = 'ERA5') p
    WHERE o.temperature_2m IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.precipitation_total
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 53 AND sistema_origem = 'ERA5') p
    WHERE o.precipitation_total IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.surface_pressure
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 54 AND sistema_origem = 'ERA5') p
    WHERE o.surface_pressure IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.soil_water_level_1
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 61 AND sistema_origem = 'ERA5') p
    WHERE o.soil_water_level_1 IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.soil_water_level_2
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 62 AND sistema_origem = 'ERA5') p
    WHERE o.soil_water_level_2 IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.soil_water_level_3
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 63 AND sistema_origem = 'ERA5') p
    WHERE o.soil_water_level_3 IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);

    INSERT INTO gold.fact_medicao (estacao_sk, tempo_sk, parametro_sk, valor)
    SELECT e.estacao_sk, t.tempo_sk, p.parametro_sk, o.soil_water_level_4
    FROM silver.era5_observations o
    INNER JOIN silver.era5_locations l ON o.location_id = l.location_id
    INNER JOIN gold.dim_estacao e ON e.estacao_id = CAST(l.location_id AS VARCHAR(50)) AND e.sistema_origem = 'ERA5'
    CROSS APPLY (SELECT tempo_sk FROM gold.dim_tempo WHERE data_hora = o.observation_datetime) t
    CROSS APPLY (SELECT parametro_sk FROM gold.dim_parametro WHERE parametro_id = 64 AND sistema_origem = 'ERA5') p
    WHERE o.soil_water_level_4 IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM gold.fact_medicao f WHERE f.estacao_sk = e.estacao_sk AND f.tempo_sk = t.tempo_sk AND f.parametro_sk = p.parametro_sk);
END;
GO

DECLARE @ExecId UNIQUEIDENTIFIER = NEWID();
EXEC logs.sp_ETL_LogInicio @ExecId, 'LOAD', 'Load Fact Medicao';
EXEC ctl.usp_merge_ipma;
EXEC ctl.usp_merge_snirh;
EXEC ctl.usp_merge_era5;
EXEC logs.sp_ETL_LogFim @ExecId, 'LOAD', 'Load Fact Medicao', 'OK';
GO

-- ============================================================================
-- 99_Seed_Data.sql
-- Dados iniciais: dim_bacia, dim_parametro
-- ============================================================================

USE PreFlood_DW;
GO

INSERT INTO gold.dim_bacia (bacia_codigo, bacia_nome) VALUES (47, N'Bacia do Mondego');
GO

INSERT INTO gold.dim_parametro (parametro_id, parametro_nome, parametro_codigo, categoria, unidade_medida, sistema_origem, granularidade) VALUES
-- IPMA (1-8)
(1,  N'Temperatura',        'temp',   'Meteorologica', 'C',     'IPMA', 'HORARIA'),
(2,  N'Humidade',           'humi',   'Meteorologica', '%',     'IPMA', 'HORARIA'),
(3,  N'Pressao',            'press',  'Meteorologica', 'hPa',   'IPMA', 'HORARIA'),
(4,  N'Vento Km',           'vkm',    'Vento',         'km/h',  'IPMA', 'HORARIA'),
(5,  N'Vento Ms',           'vms',    'Vento',         'm/s',   'IPMA', 'HORARIA'),
(6,  N'Precipitacao',       'prec',   'Meteorologica', 'mm',    'IPMA', 'HORARIA'),
(7,  N'Radiacao',           'rad',    'Meteorologica', 'W/m2',  'IPMA', 'HORARIA'),
(8,  N'Vento Direccao',     'vdir',   'Vento',         'graus', 'IPMA', 'HORARIA'),
-- SNIRH (10-15)
(10, N'Caudal Medio Diario','1850',   'Hidrologica',   'm3/s',  'SNIRH', 'DIARIA'),
(11, N'Nivel Medio Diario', '1845',   'Hidrologica',   'm',     'SNIRH', 'DIARIA'),
(12, N'Nivel Instantaneo',  '1843',   'Hidrologica',   'm',     'SNIRH', 'HORARIA'),
(14, N'Caudal Horario',     '3212219030','Hidrologica', 'm3/s',  'SNIRH', 'HORARIA'),
(15, N'Cota Ultima Hora',   '354895424', 'Hidrologica','m',     'SNIRH', 'HORARIA'),
-- ERA5 (51-68)
(51, N'Temperature 2m',        't2m',     'Meteorologica', 'K',    'ERA5', 'HORARIA'),
(52, N'Dewpoint 2m',           'd2m',     'Meteorologica', 'K',    'ERA5', 'HORARIA'),
(53, N'Total Precipitation',   'tp',      'Meteorologica', 'm',    'ERA5', 'HORARIA'),
(54, N'Surface Pressure',      'sp',      'Meteorologica', 'Pa',   'ERA5', 'HORARIA'),
(55, N'Skin Temperature',      'skt',     'Meteorologica', 'K',    'ERA5', 'HORARIA'),
(56, N'Snow Depth',            'sde',     'Meteorologica', 'm',    'ERA5', 'HORARIA'),
(57, N'Soil Temperature L1',   'stl1',    'Solo',          'K',    'ERA5', 'HORARIA'),
(58, N'Soil Temperature L2',   'stl2',    'Solo',          'K',    'ERA5', 'HORARIA'),
(59, N'Soil Temperature L3',   'stl3',    'Solo',          'K',    'ERA5', 'HORARIA'),
(60, N'Soil Temperature L4',   'stl4',    'Solo',          'K',    'ERA5', 'HORARIA'),
(61, N'Volumetric Soil Water L1','swvl1', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(62, N'Volumetric Soil Water L2','swvl2', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(63, N'Volumetric Soil Water L3','swvl3', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(64, N'Volumetric Soil Water L4','swvl4', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(65, N'Wind U 10m',            'u10',     'Vento',         'm/s',  'ERA5', 'HORARIA'),
(66, N'Wind V 10m',            'v10',     'Vento',         'm/s',  'ERA5', 'HORARIA'),
(67, N'Solar Radiation Down',  'ssrd',    'Radiacao',      'J/m2', 'ERA5', 'HORARIA'),
(68, N'Thermal Radiation Down','strd',    'Radiacao',      'J/m2', 'ERA5', 'HORARIA');
GO

PRINT 'Seed data inserido: dim_bacia (1), dim_parametro (30)';
GO

-- ============================================================================
-- v6.0 ML additions: flood labels, LSTM predictions, flood thresholds
-- ============================================================================

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

PRINT 'v6.0 ML tables created: ml.flood_labels, ml.lstm_predictions, ctl.flood_thresholds';
GO

