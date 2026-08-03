-- ============================================================================
-- 20_Bronze_Snapshot.sql
-- Cria snapshots (backup) das tabelas Bronze com sufixo _snap_YYYYMMDD
-- Executar antes de cada carga Bronze para preservar estado anterior
-- ============================================================================

USE PreFlood_DW;
GO

DECLARE @snap_suffix NVARCHAR(20) = N'_snap_' + CONVERT(NVARCHAR(8), GETDATE(), 112);
DECLARE @sql NVARCHAR(MAX);

SET @sql = N'
IF OBJECT_ID(''brz.ipma_obs' + @snap_suffix + ''') IS NOT NULL DROP TABLE brz.ipma_obs' + @snap_suffix + ';
SELECT * INTO brz.ipma_obs' + @snap_suffix + ' FROM brz.ipma_obs;

IF OBJECT_ID(''brz.ipma_est' + @snap_suffix + ''') IS NOT NULL DROP TABLE brz.ipma_est' + @snap_suffix + ';
SELECT * INTO brz.ipma_est' + @snap_suffix + ' FROM brz.ipma_est;

IF OBJECT_ID(''brz.snirh_obs' + @snap_suffix + ''') IS NOT NULL DROP TABLE brz.snirh_obs' + @snap_suffix + ';
SELECT * INTO brz.snirh_obs' + @snap_suffix + ' FROM brz.snirh_obs;

IF OBJECT_ID(''brz.snirh_est' + @snap_suffix + ''') IS NOT NULL DROP TABLE brz.snirh_est' + @snap_suffix + ';
SELECT * INTO brz.snirh_est' + @snap_suffix + ' FROM brz.snirh_est;

IF OBJECT_ID(''brz.era5_obs' + @snap_suffix + ''') IS NOT NULL DROP TABLE brz.era5_obs' + @snap_suffix + ';
SELECT * INTO brz.era5_obs' + @snap_suffix + ' FROM brz.era5_obs;
';
EXEC sp_executesql @sql;

DECLARE @msg NVARCHAR(200) = 'Bronze snapshot criado: ' + @snap_suffix;
RAISERROR(@msg, 0, 1) WITH NOWAIT;
GO

DECLARE @snap NVARCHAR(20) = N'_snap_' + CONVERT(NVARCHAR(8), GETDATE(), 112);
SELECT
    'brz.ipma_obs'  + @snap AS tabela, COUNT(*) AS registos FROM brz.ipma_obs
UNION ALL
SELECT 'brz.ipma_est'  + @snap, COUNT(*) FROM brz.ipma_est
UNION ALL
SELECT 'brz.snirh_obs' + @snap, COUNT(*) FROM brz.snirh_obs
UNION ALL
SELECT 'brz.snirh_est' + @snap, COUNT(*) FROM brz.snirh_est
UNION ALL
SELECT 'brz.era5_obs'  + @snap, COUNT(*) FROM brz.era5_obs;
GO

-- ============================================================================
-- Opcional: limpar snapshots antigos (> 7 dias)
-- Descomentar para execucao automatica
-- ============================================================================
/*
DECLARE @cutoff DATE = DATEADD(DAY, -7, GETDATE());
DECLARE @drop_sql NVARCHAR(MAX);

SELECT @drop_sql = STRING_AGG(
    'DROP TABLE ' + QUOTENAME(SCHEMA_NAME(t.schema_id)) + '.' + QUOTENAME(t.name), ';
' + CHAR(13)) WITHIN GROUP (ORDER BY t.name)
FROM sys.tables t
WHERE SCHEMA_NAME(t.schema_id) = 'brz'
  AND t.name LIKE '%_snap_%'
  AND TRY_CONVERT(DATE, RIGHT(t.name, 8)) < @cutoff;

IF @drop_sql IS NOT NULL
BEGIN
    SET @drop_sql = @drop_sql + ';';
    EXEC sp_executesql @drop_sql;
    PRINT 'Snapshots antigos removidos (anteriores a ' + CONVERT(NVARCHAR(10), @cutoff, 112) + ')';
END
*/
-- ============================================================================
