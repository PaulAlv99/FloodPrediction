-- ============================================================================
-- 18_Create_AgentJobs.sql
-- SQL Server Agent Jobs — tudo referencia Pkg_Master.dtsx (package unico)
-- Proxy: PreFloodProxy (PauloCredential)
-- ============================================================================

USE msdb;
GO

-- Job 1: PreFlood_Hourly — Bronze+Silver+Gold+Predict (sem ML train)
IF EXISTS (SELECT 1 FROM sysjobs WHERE name = 'PreFlood_Hourly')
BEGIN
    DECLARE @J1 UNIQUEIDENTIFIER; SELECT @J1 = job_id FROM sysjobs WHERE name = 'PreFlood_Hourly';
    EXEC sp_delete_job @job_id = @J1;
END
GO
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @JobId1 UNIQUEIDENTIFIER;
    EXEC sp_add_job @job_name = N'PreFlood_Hourly', @enabled = 1,
        @description = N'ETL completo (Bronze+Silver+Gold+Predict) sem treino ML. Corre hourly.',
        @owner_login_name = N'sa', @job_id = @JobId1 OUTPUT;

    EXEC sp_add_jobstep @job_id = @JobId1, @step_name = N'1 - Pkg_Master (sem ML)',
        @step_id = 1, @subsystem = N'CmdExec',
        @command = N'"C:\Program Files\Microsoft SQL Server\170\DTS\Binn\dtexec.exe" /Project "C:\ProjetoDW\V4\SSIS\PreFlood_DW\PreFlood\bin\Development\PreFlood.ispac" /Package "Pkg_Master.dtsx" /Par "\Package.Variables[User::RunML].Value";0',
        @retry_attempts = 1, @retry_interval = 5, @on_success_action = 3,
        @output_file_name = N'C:\ProjetoDW\V4\Logs\hourly_step1.txt',
        @proxy_name = N'PreFloodProxy';

    EXEC sp_add_jobstep @job_id = @JobId1, @step_name = N'2 - Verificar Erros',
        @step_id = 2, @subsystem = N'TSQL',
        @command = N'
IF EXISTS (SELECT 1 FROM PreFlood_DW.logs.ETL_Log WHERE CAST(Dt_Inicio AS DATE) = CAST(GETDATE() AS DATE) AND Status = ''ERRO'')
BEGIN
    PRINT ''ATENCAO: Erros na execucao ETL. Verifique PreFlood_DW.logs.ETL_Log.'';
    SELECT Fase, Passo, Status, Mensagem, Dt_Inicio FROM PreFlood_DW.logs.ETL_Log WHERE CAST(Dt_Inicio AS DATE) = CAST(GETDATE() AS DATE) AND Status = ''ERRO'';
END
ELSE
    PRINT ''ETL executado com sucesso.'';
',
        @database_name = N'msdb', @on_success_action = 1,
        @output_file_name = N'C:\ProjetoDW\V4\Logs\hourly_step2.txt';

    EXEC sp_add_jobschedule @job_id = @JobId1, @name = N'Hourly_xx15',
        @freq_type = 4, @freq_interval = 1, @freq_subday_type = 8, @freq_subday_interval = 1, @active_start_time = 001500;
    EXEC sp_add_jobserver @job_id = @JobId1, @server_name = N'(LOCAL)';
    COMMIT TRANSACTION;
END TRY BEGIN CATCH; ROLLBACK; PRINT 'Erro Job1: ' + ERROR_MESSAGE(); END CATCH;
GO

-- Job 2: PreFlood_Daily — Tudo (Bronze+Silver+Gold+ML+Alerts)
IF EXISTS (SELECT 1 FROM sysjobs WHERE name = 'PreFlood_Daily')
BEGIN
    DECLARE @J2 UNIQUEIDENTIFIER; SELECT @J2 = job_id FROM sysjobs WHERE name = 'PreFlood_Daily';
    EXEC sp_delete_job @job_id = @J2;
END
GO
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @JobId2 UNIQUEIDENTIFIER;
    EXEC sp_add_job @job_name = N'PreFlood_Daily', @enabled = 1,
        @description = N'ETL completo + treino ML + alertas. Corre diario as 06:00.',
        @owner_login_name = N'sa', @job_id = @JobId2 OUTPUT;

    EXEC sp_add_jobstep @job_id = @JobId2, @step_name = N'1 - Pkg_Master (completo)',
        @step_id = 1, @subsystem = N'CmdExec',
        @command = N'"C:\Program Files\Microsoft SQL Server\170\DTS\Binn\dtexec.exe" /Project "C:\ProjetoDW\V4\SSIS\PreFlood_DW\PreFlood\bin\Development\PreFlood.ispac" /Package "Pkg_Master.dtsx"',
        @retry_attempts = 1, @retry_interval = 5, @on_success_action = 1,
        @output_file_name = N'C:\ProjetoDW\V4\Logs\daily_step1.txt',
        @proxy_name = N'PreFloodProxy';

    EXEC sp_add_jobschedule @job_id = @JobId2, @name = N'Diario_06h00',
        @freq_type = 4, @freq_interval = 1, @active_start_time = 060000;
    EXEC sp_add_jobserver @job_id = @JobId2, @server_name = N'(LOCAL)';
    COMMIT TRANSACTION;
END TRY BEGIN CATCH; ROLLBACK; PRINT 'Erro Job2: ' + ERROR_MESSAGE(); END CATCH;
GO

-- Job 3: PreFlood_ML_Weekly — So ML (sem Bronze/Silver/Gold)
IF EXISTS (SELECT 1 FROM sysjobs WHERE name = 'PreFlood_ML_Weekly')
BEGIN
    DECLARE @J3 UNIQUEIDENTIFIER; SELECT @J3 = job_id FROM sysjobs WHERE name = 'PreFlood_ML_Weekly';
    EXEC sp_delete_job @job_id = @J3;
END
GO
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @JobId3 UNIQUEIDENTIFIER;
    EXEC sp_add_job @job_name = N'PreFlood_ML_Weekly', @enabled = 1,
        @description = N'Treino modelos ML (so SEQ_ML). Domingo 02:00.',
        @owner_login_name = N'sa', @job_id = @JobId3 OUTPUT;

    EXEC sp_add_jobstep @job_id = @JobId3, @step_name = N'1 - Pkg_Master (so ML)',
        @step_id = 1, @subsystem = N'CmdExec',
        @command = N'"C:\Program Files\Microsoft SQL Server\170\DTS\Binn\dtexec.exe" /Project "C:\ProjetoDW\V4\SSIS\PreFlood_DW\PreFlood\bin\Development\PreFlood.ispac" /Package "Pkg_Master.dtsx" /Par "\Package.Variables[User::RunBronze].Value";0 /Par "\Package.Variables[User::RunSilver].Value";0 /Par "\Package.Variables[User::RunGold].Value";0',
        @retry_attempts = 1, @retry_interval = 5, @on_success_action = 1,
        @output_file_name = N'C:\ProjetoDW\V4\Logs\weekly_step1.txt',
        @proxy_name = N'PreFloodProxy';

    EXEC sp_add_jobschedule @job_id = @JobId3, @name = N'Semanal_Dom_02h00',
        @freq_type = 8, @freq_interval = 1, @freq_recurrence_factor = 1, @active_start_time = 020000;
    EXEC sp_add_jobserver @job_id = @JobId3, @server_name = N'(LOCAL)';
    COMMIT TRANSACTION;
END TRY BEGIN CATCH; ROLLBACK; PRINT 'Erro Job3: ' + ERROR_MESSAGE(); END CATCH;
GO

-- Job 4: PreFlood_PredictNow — Python predict + early warning (hourly)
IF EXISTS (SELECT 1 FROM sysjobs WHERE name = 'PreFlood_PredictNow')
BEGIN
    DECLARE @J4 UNIQUEIDENTIFIER; SELECT @J4 = job_id FROM sysjobs WHERE name = 'PreFlood_PredictNow';
    EXEC sp_delete_job @job_id = @J4;
END
GO
BEGIN TRANSACTION;
BEGIN TRY
    DECLARE @JobId4 UNIQUEIDENTIFIER;
    EXEC sp_add_job @job_name = N'PreFlood_PredictNow', @enabled = 1,
        @description = N'Predicoes em tempo real + early warning. Hourly.',
        @owner_login_name = N'sa', @job_id = @JobId4 OUTPUT;

    EXEC sp_add_jobstep @job_id = @JobId4, @step_name = N'1 - predict_now.py',
        @step_id = 1, @subsystem = N'CmdExec',
        @command = N'"C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" "C:\ProjetoDW\V4\Scripts\predict_now.py"',
        @retry_attempts = 1, @retry_interval = 5, @on_success_action = 3,
        @output_file_name = N'C:\ProjetoDW\V4\Logs\predict_step1.txt',
        @proxy_name = N'PreFloodProxy';

    EXEC sp_add_jobstep @job_id = @JobId4, @step_name = N'2 - early_warning.py',
        @step_id = 2, @subsystem = N'CmdExec',
        @command = N'"C:\Users\paulo\AppData\Local\Programs\Python\Python313\python.exe" "C:\ProjetoDW\V4\Scripts\early_warning.py"',
        @retry_attempts = 1, @retry_interval = 5, @on_success_action = 1,
        @output_file_name = N'C:\ProjetoDW\V4\Logs\predict_step2.txt',
        @proxy_name = N'PreFloodProxy';

    EXEC sp_add_jobschedule @job_id = @JobId4, @name = N'Hourly_xx45',
        @freq_type = 4, @freq_interval = 1, @freq_subday_type = 8, @freq_subday_interval = 1, @active_start_time = 004500;
    EXEC sp_add_jobserver @job_id = @JobId4, @server_name = N'(LOCAL)';
    COMMIT TRANSACTION;
END TRY BEGIN CATCH; ROLLBACK; PRINT 'Erro Job4: ' + ERROR_MESSAGE(); END CATCH;
GO

PRINT '';
PRINT '============================================================';
PRINT '  Agent Jobs criados (Pkg_Master unico):';
PRINT '  1. PreFlood_Hourly      -> Hourly xx:15  (ETL sem ML)';
PRINT '  2. PreFlood_Daily       -> Diario 06:00  (Tudo)';
PRINT '  3. PreFlood_ML_Weekly   -> Dom 02:00     (So ML)';
PRINT '  4. PreFlood_PredictNow  -> Hourly xx:45  (Python)';
PRINT '============================================================';
GO
