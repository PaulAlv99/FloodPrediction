-- ============================================================================
-- 17_Create_Alerts.sql
-- Alert evaluation: ctl.usp_evaluate_alerts (consulta manual, sem email)
-- Schema: ctl
-- ============================================================================

USE PreFlood_DW;
GO

CREATE OR ALTER PROCEDURE ctl.usp_evaluate_alerts
    @Execucao_Id UNIQUEIDENTIFIER = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF @Execucao_Id IS NULL SET @Execucao_Id = NEWID();

    DECLARE @AlertasGerados INT = 0;
    DECLARE @AlertasExpirados INT = 0;

    EXEC logs.sp_ETL_LogInicio @Execucao_Id, 'ALERTA', 'Evaluate_Alerts';

    BEGIN TRY
        UPDATE ctl.alerts
        SET status = 'EXPIRED', resolved_at = GETDATE()
        WHERE status IN ('ACTIVE', 'WARNING')
          AND created_at < DATEADD(HOUR, -24, GETDATE());

        SET @AlertasExpirados = @@ROWCOUNT;

        INSERT INTO ctl.alerts
            (alert_type, severity, estacao_sk, message, metric_value, threshold_value,
             run_id, status, created_at, expires_at)
        SELECT
            'RISK_LEVEL',
            CASE
                WHEN rc.nivel_risco >= 5 THEN 'CRITICAL'
                WHEN rc.nivel_risco >= 4 THEN 'ALERT'
                ELSE 'WARNING'
            END,
            rc.estacao_sk,
            CONCAT(
                'Estacao ', ISNULL(rc.estacao_nome, CAST(rc.estacao_sk AS VARCHAR(10))),
                ' — Risco nivel ', rc.nivel_risco, ' (', ISNULL(rc.categoria_risco, 'N/A'), ')',
                ' | Cota albuf: ', ISNULL(CAST(rc.cota_albuf_atual AS VARCHAR(20)), 'N/A'),
                ' | Pred 6h: ', ISNULL(CAST(rc.cota_albuf_pred_6h AS VARCHAR(20)), 'N/A')
            ),
            CAST(rc.nivel_risco AS FLOAT), 3.0,
            @Execucao_Id, 'ACTIVE', GETDATE(), DATEADD(HOUR, 24, GETDATE())
        FROM ml.flood_risk_current rc
        WHERE rc.nivel_risco >= 3
          AND NOT EXISTS (
              SELECT 1 FROM ctl.alerts a
              WHERE a.estacao_sk = rc.estacao_sk
                AND a.alert_type  = 'RISK_LEVEL'
                AND a.status     IN ('ACTIVE', 'WARNING')
                AND a.created_at >= DATEADD(HOUR, -1, GETDATE())
          );

        SET @AlertasGerados = @AlertasGerados + @@ROWCOUNT;

        EXEC logs.sp_ETL_LogFim
            @Execucao_Id, 'ALERTA', 'Evaluate_Alerts', 'OK',
            NULL, @AlertasGerados, @AlertasExpirados,
            CONCAT('Alertas gerados: ', @AlertasGerados, ' | Expirados: ', @AlertasExpirados);
    END TRY
    BEGIN CATCH
        DECLARE @ErroMsg NVARCHAR(4000) = ERROR_MESSAGE();
        EXEC logs.sp_ETL_LogFim
            @Execucao_Id, 'ALERTA', 'Evaluate_Alerts', 'ERRO',
            NULL, NULL, NULL, LEFT(@ErroMsg, 500);
        RAISERROR('Erro em usp_evaluate_alerts: %s', 16, 1, @ErroMsg);
    END CATCH;
END;
GO

PRINT 'ctl.usp_evaluate_alerts criado (consulta manual, sem envio automatico)';
GO
