-- ============================================================================
-- 19_Cleanup.sql
-- Limpa tabelas Bronze e Silver (TRUNCATE)
-- ============================================================================

USE PreFlood_DW;
GO

TRUNCATE TABLE brz.ipma_obs;
TRUNCATE TABLE brz.ipma_est;
TRUNCATE TABLE brz.snirh_obs;
TRUNCATE TABLE brz.snirh_est;
TRUNCATE TABLE brz.era5_obs;
TRUNCATE TABLE silver.ipma_stations;
TRUNCATE TABLE silver.ipma_observations;
TRUNCATE TABLE silver.ipma_previsao_local;
TRUNCATE TABLE silver.ipma_previsao;
TRUNCATE TABLE silver.snirh_stations;
TRUNCATE TABLE silver.snirh_observations;
TRUNCATE TABLE silver.era5_observations;
GO

PRINT 'Bronze + Silver truncados';
GO
