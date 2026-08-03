-- ============================================================================
-- 10_Transform_Bronze_Silver_SNIRH.sql
-- Transformacao brz -> stg: SNIRH (stations + observations)
-- Com logging e quarentena
-- ============================================================================

USE PreFlood_DW;
GO

DECLARE @ExecId UNIQUEIDENTIFIER = NEWID();
DECLARE @Lidos INT, @Escritos INT, @Rejeitados INT;

EXEC logs.sp_ETL_LogInicio @ExecId, 'TRANSFORM', 'Bronze->Silver SNIRH Stations';

SELECT @Lidos = COUNT(*) FROM brz.snirh_est;

MERGE INTO silver.snirh_stations AS tgt
USING (
    SELECT
        id_estacao,
        nome,
        ROUND(TRY_CAST(latitude  AS FLOAT), 3) AS lat,
        ROUND(TRY_CAST(longitude AS FLOAT), 3) AS lon
    FROM brz.snirh_est
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
    @ExecId, 'TRANSFORM', 'Bronze->Silver SNIRH Stations',
    'OK', @Lidos, @Escritos, @Rejeitados;
GO

DECLARE @ExecId2 UNIQUEIDENTIFIER = NEWID();
DECLARE @Lidos2 INT, @Escritos2 INT, @Rejeitados2 INT;

EXEC logs.sp_ETL_LogInicio @ExecId2, 'TRANSFORM', 'Bronze->Silver SNIRH Observations';

SELECT @Lidos2 = COUNT(*) FROM brz.snirh_obs;

INSERT INTO silver.snirh_observations (observation_datetime, station_id, parametro_id, valor, granularidade, ingestion_ts)
SELECT
    TRY_CAST(obs.data_hora    AS DATETIME2),
    obs.id_estacao,
    TRY_CAST(obs.id_parametro AS BIGINT),
    TRY_CAST(obs.valor        AS FLOAT),
    'HORARIA',
    GETDATE()
FROM brz.snirh_obs AS obs
WHERE TRY_CAST(obs.data_hora AS DATETIME2) IS NOT NULL
  AND obs.id_estacao IS NOT NULL
  AND LTRIM(RTRIM(obs.id_estacao)) <> ''
  AND TRY_CAST(obs.id_parametro AS BIGINT) IS NOT NULL
  AND TRY_CAST(obs.valor AS FLOAT) IS NOT NULL
  AND ISNUMERIC(obs.valor) = 1
  AND NOT EXISTS (
      SELECT 1 FROM silver.snirh_observations ex
      WHERE ex.observation_datetime = TRY_CAST(obs.data_hora AS DATETIME2)
        AND ex.station_id = obs.id_estacao
        AND ex.parametro_id = TRY_CAST(obs.id_parametro AS BIGINT)
  );

SET @Escritos2 = @@ROWCOUNT;
SET @Rejeitados2 = @Lidos2 - @Escritos2;

EXEC logs.sp_ETL_LogFim
    @ExecId2, 'TRANSFORM', 'Bronze->Silver SNIRH Observations',
    'OK', @Lidos2, @Escritos2, @Rejeitados2;
GO

-- Quarentena
INSERT INTO quarentena.ETL_Quarentena (Execucao_Id, Fonte, Chave_Registo, Dados_Registo, Motivo)
SELECT
    NEWID(),
    'brz.snirh_obs',
    obs.id_estacao + '|' + obs.data_hora + '|' + ISNULL(obs.id_parametro, ''),
    (SELECT obs.data_hora, obs.id_estacao, obs.id_parametro, obs.valor FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
    CASE
        WHEN TRY_CAST(obs.data_hora AS DATETIME2) IS NULL
            THEN 'data_hora invalida: ' + ISNULL(obs.data_hora, 'NULL')
        WHEN obs.id_estacao IS NULL OR LTRIM(RTRIM(obs.id_estacao)) = ''
            THEN 'id_estacao vazio ou nulo'
        WHEN TRY_CAST(obs.id_parametro AS BIGINT) IS NULL
            THEN 'id_parametro nao numerico: ' + ISNULL(obs.id_parametro, 'NULL')
        WHEN TRY_CAST(obs.valor AS FLOAT) IS NULL OR ISNUMERIC(obs.valor) = 0
            THEN 'valor nao numerico: ' + ISNULL(obs.valor, 'NULL')
        ELSE 'motivo desconhecido'
    END
FROM brz.snirh_obs AS obs
WHERE TRY_CAST(obs.data_hora AS DATETIME2) IS NULL
   OR obs.id_estacao IS NULL
   OR LTRIM(RTRIM(obs.id_estacao)) = ''
   OR TRY_CAST(obs.id_parametro AS BIGINT) IS NULL
   OR TRY_CAST(obs.valor AS FLOAT) IS NULL
   OR ISNUMERIC(obs.valor) = 0;

PRINT CONCAT('Quarentena SNIRH: ', @@ROWCOUNT, ' registos encaminhados');
GO
