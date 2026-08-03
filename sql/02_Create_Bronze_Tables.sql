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
