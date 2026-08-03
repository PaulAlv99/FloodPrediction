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
