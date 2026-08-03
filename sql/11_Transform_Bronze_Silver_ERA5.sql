-- ============================================================================
-- 11_Transform_Bronze_Silver_ERA5.sql
-- Transformacao brz -> stg: ERA5 (locations + observations)
-- Com logging e quarentena
-- ============================================================================

USE PreFlood_DW;
GO

-- PARTE 1: Locations (MERGE deduplicar lat/lon)
DECLARE @ExecId1 UNIQUEIDENTIFIER = NEWID();
DECLARE @Lidos1 INT, @Escritos1 INT, @Rejeitados1 INT;

EXEC logs.sp_ETL_LogInicio @ExecId1, 'TRANSFORM', 'Bronze->Silver ERA5 Locations';

SELECT @Lidos1 = COUNT(*) FROM brz.era5_obs;

MERGE INTO silver.era5_locations AS tgt
USING (
    SELECT DISTINCT
        ROUND(TRY_CAST(latitude  AS FLOAT), 3) AS lat,
        ROUND(TRY_CAST(longitude AS FLOAT), 3) AS lon
    FROM brz.era5_obs
    WHERE TRY_CAST(latitude  AS FLOAT) IS NOT NULL
      AND TRY_CAST(longitude AS FLOAT) IS NOT NULL
      AND TRY_CAST(latitude  AS FLOAT) BETWEEN -90  AND 90
      AND TRY_CAST(longitude AS FLOAT) BETWEEN -180 AND 180
) AS src
ON tgt.latitude  = src.lat
AND tgt.longitude = src.lon
WHEN NOT MATCHED BY TARGET THEN
    INSERT (location_label, latitude, longitude, ingestion_ts)
    VALUES (CONCAT('ERA5_', src.lat, '_', src.lon), src.lat, src.lon, GETDATE());

SET @Escritos1 = @@ROWCOUNT;
SET @Rejeitados1 = @Lidos1 - @Escritos1;

EXEC logs.sp_ETL_LogFim
    @ExecId1, 'TRANSFORM', 'Bronze->Silver ERA5 Locations',
    'OK', @Lidos1, @Escritos1, @Rejeitados1;
GO

-- PARTE 2: Observations
DECLARE @ExecId2 UNIQUEIDENTIFIER = NEWID();
DECLARE @Lidos2 INT, @Escritos2 INT, @Rejeitados2 INT;

EXEC logs.sp_ETL_LogInicio @ExecId2, 'TRANSFORM', 'Bronze->Silver ERA5 Observations';

SELECT @Lidos2 = COUNT(*) FROM brz.era5_obs;

INSERT INTO silver.era5_observations (
    observation_datetime, location_id,
    temperature_2m, precipitation_total, surface_pressure,
    soil_water_level_1, soil_water_level_2, soil_water_level_3, soil_water_level_4,
    ingestion_ts
)
SELECT
    TRY_CAST(obs.data_hora      AS DATETIME2),
    loc.location_id,
    TRY_CAST(obs.temperatura_2m AS FLOAT),
    CASE WHEN TRY_CAST(obs.precipitacao AS FLOAT) < 0 THEN 0.0 ELSE TRY_CAST(obs.precipitacao AS FLOAT) END,
    TRY_CAST(obs.pressao_superf AS FLOAT),
    TRY_CAST(obs.solo_l1        AS FLOAT),
    TRY_CAST(obs.solo_l2        AS FLOAT),
    TRY_CAST(obs.solo_l3        AS FLOAT),
    TRY_CAST(obs.solo_l4        AS FLOAT),
    GETDATE()
FROM brz.era5_obs AS obs
INNER JOIN silver.era5_locations AS loc
    ON loc.latitude  = ROUND(TRY_CAST(obs.latitude  AS FLOAT), 3)
   AND loc.longitude = ROUND(TRY_CAST(obs.longitude AS FLOAT), 3)
WHERE TRY_CAST(obs.data_hora      AS DATETIME2) IS NOT NULL
  AND TRY_CAST(obs.latitude       AS FLOAT) BETWEEN -90  AND 90
  AND TRY_CAST(obs.longitude      AS FLOAT) BETWEEN -180 AND 180
  AND TRY_CAST(obs.temperatura_2m AS FLOAT) BETWEEN 180 AND 350
  AND TRY_CAST(obs.precipitacao   AS FLOAT) > -1
  AND TRY_CAST(obs.solo_l1        AS FLOAT) BETWEEN 0 AND 1
  AND TRY_CAST(obs.solo_l2        AS FLOAT) BETWEEN 0 AND 1
  AND TRY_CAST(obs.solo_l3        AS FLOAT) BETWEEN 0 AND 1
  AND TRY_CAST(obs.solo_l4        AS FLOAT) BETWEEN 0 AND 1
  AND NOT EXISTS (
      SELECT 1 FROM silver.era5_observations ex
      WHERE ex.observation_datetime = TRY_CAST(obs.data_hora AS DATETIME2)
        AND ex.location_id = loc.location_id
  );

SET @Escritos2 = @@ROWCOUNT;
SET @Rejeitados2 = @Lidos2 - @Escritos2;

EXEC logs.sp_ETL_LogFim
    @ExecId2, 'TRANSFORM', 'Bronze->Silver ERA5 Observations',
    'OK', @Lidos2, @Escritos2, @Rejeitados2;
GO

-- Quarentena
INSERT INTO quarentena.ETL_Quarentena (Execucao_Id, Fonte, Chave_Registo, Dados_Registo, Motivo)
SELECT
    NEWID(),
    'brz.era5_obs',
    ISNULL(obs.latitude,'') + '|' + ISNULL(obs.longitude,'') + '|' + ISNULL(obs.data_hora,''),
    (SELECT obs.data_hora, obs.latitude, obs.longitude, obs.temperatura_2m,
            obs.precipitacao, obs.solo_l1, obs.solo_l2, obs.solo_l3, obs.solo_l4,
            obs.pressao_superf
     FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
    CASE
        WHEN TRY_CAST(obs.data_hora AS DATETIME2) IS NULL
            THEN 'data_hora invalida: ' + ISNULL(obs.data_hora, 'NULL')
        WHEN TRY_CAST(obs.latitude AS FLOAT) IS NULL
             OR TRY_CAST(obs.latitude AS FLOAT) NOT BETWEEN -90 AND 90
            THEN 'latitude invalida: ' + ISNULL(obs.latitude, 'NULL')
        WHEN TRY_CAST(obs.longitude AS FLOAT) IS NULL
             OR TRY_CAST(obs.longitude AS FLOAT) NOT BETWEEN -180 AND 180
            THEN 'longitude invalida: ' + ISNULL(obs.longitude, 'NULL')
        WHEN TRY_CAST(obs.temperatura_2m AS FLOAT) NOT BETWEEN 180 AND 350
            THEN 'temperatura fora do range Kelvin (180-350): ' + ISNULL(obs.temperatura_2m, 'NULL')
        ELSE 'valor solo fora do range (0-1)'
    END
FROM brz.era5_obs AS obs
WHERE TRY_CAST(obs.data_hora AS DATETIME2) IS NULL
   OR TRY_CAST(obs.latitude AS FLOAT) IS NULL
   OR TRY_CAST(obs.latitude AS FLOAT) NOT BETWEEN -90 AND 90
   OR TRY_CAST(obs.longitude AS FLOAT) IS NULL
   OR TRY_CAST(obs.longitude AS FLOAT) NOT BETWEEN -180 AND 180
   OR TRY_CAST(obs.temperatura_2m AS FLOAT) NOT BETWEEN 180 AND 350
   OR TRY_CAST(obs.solo_l1 AS FLOAT) NOT BETWEEN 0 AND 1
   OR TRY_CAST(obs.solo_l2 AS FLOAT) NOT BETWEEN 0 AND 1
   OR TRY_CAST(obs.solo_l3 AS FLOAT) NOT BETWEEN 0 AND 1
   OR TRY_CAST(obs.solo_l4 AS FLOAT) NOT BETWEEN 0 AND 1;

PRINT CONCAT('Quarentena ERA5: ', @@ROWCOUNT, ' registos encaminhados');
GO
