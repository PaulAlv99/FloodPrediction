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
