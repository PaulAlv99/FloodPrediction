-- ============================================================================
-- 09_Transform_Bronze_Silver_IPMA.sql
-- Transformacao brz -> stg: IPMA (stations + observations)
-- Com logging (logs.sp_ETL_*) e quarentena (quarentena.ETL_Quarentena)
-- ============================================================================

USE PreFlood_DW;
GO

DECLARE @ExecId UNIQUEIDENTIFIER = NEWID();
DECLARE @Lidos INT, @Escritos INT, @Rejeitados INT;

EXEC logs.sp_ETL_LogInicio @ExecId, 'TRANSFORM', 'Bronze->Silver IPMA Stations';

SELECT @Lidos = COUNT(*) FROM brz.ipma_est;

MERGE INTO silver.ipma_stations AS tgt
USING (
    SELECT
        id_estacao,
        nome,
        ROUND(TRY_CAST(REPLACE(latitude, ',', '.')  AS FLOAT), 3) AS lat,
        ROUND(TRY_CAST(REPLACE(longitude, ',', '.') AS FLOAT), 3) AS lon
    FROM brz.ipma_est
    WHERE id_estacao IS NOT NULL
      AND LTRIM(RTRIM(id_estacao)) <> ''
      AND nome IS NOT NULL
      AND LTRIM(RTRIM(nome)) <> ''
) AS src
ON tgt.station_id = src.id_estacao
WHEN MATCHED THEN UPDATE SET
    station_name = ISNULL(src.nome, tgt.station_name),
    latitude = ISNULL(src.lat, tgt.latitude),
    longitude = ISNULL(src.lon, tgt.longitude),
    ingestion_ts = GETDATE()
WHEN NOT MATCHED THEN
    INSERT (station_id, station_name, latitude, longitude, bacia_codigo, ingestion_ts)
    VALUES (src.id_estacao, ISNULL(src.nome, ''), src.lat, src.lon, 47, GETDATE());

SET @Escritos = @@ROWCOUNT;
SET @Rejeitados = @Lidos - @Escritos;

EXEC logs.sp_ETL_LogFim
    @ExecId, 'TRANSFORM', 'Bronze->Silver IPMA Stations',
    'OK', @Lidos, @Escritos, @Rejeitados;
GO

DECLARE @ExecId2 UNIQUEIDENTIFIER = NEWID();
DECLARE @Lidos2 INT, @Escritos2 INT, @Rejeitados2 INT;

EXEC logs.sp_ETL_LogInicio @ExecId2, 'TRANSFORM', 'Bronze->Silver IPMA Observations';

SELECT @Lidos2 = COUNT(*) FROM brz.ipma_obs;

INSERT INTO silver.ipma_observations (observation_datetime, station_id, parametro_id, valor)
SELECT
    TRY_CAST(REPLACE(obs.data_hora, 'T', ' ') AS DATETIME2),
    obs.id_estacao,
    v.parametro_id,
    v.valor
FROM brz.ipma_obs AS obs
CROSS APPLY (
    VALUES
        (1, TRY_CAST(obs.temperatura  AS FLOAT)),
        (2, TRY_CAST(obs.precipitacao AS FLOAT)),
        (3, TRY_CAST(obs.humidade     AS FLOAT)),
        (4, TRY_CAST(obs.pressao      AS FLOAT)),
        (5, TRY_CAST(obs.vento_ms     AS FLOAT)),
        (6, TRY_CAST(obs.vento_dir    AS FLOAT)),
        (7, TRY_CAST(obs.radiacao     AS FLOAT)),
        (8, TRY_CAST(obs.vento_km     AS FLOAT))
) v(parametro_id, valor)
WHERE TRY_CAST(REPLACE(obs.data_hora, 'T', ' ') AS DATETIME2) IS NOT NULL
  AND obs.id_estacao IS NOT NULL
  AND LTRIM(RTRIM(obs.id_estacao)) <> ''
  AND v.valor IS NOT NULL
  AND v.valor NOT IN (-99, -99.0)
  AND NOT EXISTS (
      SELECT 1 FROM silver.ipma_observations ex
      WHERE ex.observation_datetime = TRY_CAST(REPLACE(obs.data_hora, 'T', ' ') AS DATETIME2)
        AND ex.station_id = obs.id_estacao
        AND ex.parametro_id = v.parametro_id
  );

SET @Escritos2 = @@ROWCOUNT;
SET @Rejeitados2 = @Lidos2 - @Escritos2;

EXEC logs.sp_ETL_LogFim
    @ExecId2, 'TRANSFORM', 'Bronze->Silver IPMA Observations',
    'OK', @Lidos2, @Escritos2, @Rejeitados2;
GO

-- Quarentena: registos rejeitados de brz.ipma_obs
INSERT INTO quarentena.ETL_Quarentena (Execucao_Id, Fonte, Chave_Registo, Dados_Registo, Motivo)
SELECT
    NEWID(),
    'brz.ipma_obs',
    obs.id_estacao + '|' + obs.data_hora,
    (SELECT obs.data_hora AS data_hora, obs.id_estacao AS id_estacao,
            obs.temperatura, obs.humidade, obs.pressao,
            obs.vento_km, obs.vento_ms, obs.vento_dir,
            obs.precipitacao, obs.radiacao
     FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
    CASE
        WHEN TRY_CAST(REPLACE(obs.data_hora, 'T', ' ') AS DATETIME2) IS NULL
            THEN 'data_hora invalida: ' + ISNULL(obs.data_hora, 'NULL')
        WHEN obs.id_estacao IS NULL OR LTRIM(RTRIM(obs.id_estacao)) = ''
            THEN 'id_estacao vazio ou nulo'
        ELSE 'todos os valores metricos sao sentinela (-99) ou nulos'
    END
FROM brz.ipma_obs AS obs
WHERE TRY_CAST(REPLACE(obs.data_hora, 'T', ' ') AS DATETIME2) IS NULL
   OR obs.id_estacao IS NULL
   OR LTRIM(RTRIM(obs.id_estacao)) = ''
   OR (
       ISNULL(TRY_CAST(obs.temperatura  AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.precipitacao AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.humidade     AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.pressao      AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.vento_ms     AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.vento_dir    AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.radiacao     AS FLOAT), -99) IN (-99, -99.0)
       AND ISNULL(TRY_CAST(obs.vento_km     AS FLOAT), -99) IN (-99, -99.0)
   );

PRINT CONCAT('Quarentena IPMA: ', @@ROWCOUNT, ' registos encaminhados');
GO
