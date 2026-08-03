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
