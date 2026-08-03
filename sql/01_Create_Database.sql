-- ============================================================================
-- PreFlood_DW v4.0 — Data Lakehouse (brz + stg + gold + logs + ml + quarentena + ctl)
-- Bacia do Mondego — Hydro-meteorological Flood Prediction
-- ============================================================================
--
-- Schemas:
--   brz        -> Bronze (raw ingestion, all NVARCHAR, audit columns)
--   stg        -> Silver (typed, cleaned, validated — IS the staging/silver layer)
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
