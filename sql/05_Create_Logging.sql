-- ============================================================================
-- 05_Create_Logging.sql
-- Logging framework (padrao Ficha2SETCD adaptado a PreFlood_DW)
-- Schema: logs
-- ============================================================================

USE PreFlood_DW;
GO

IF OBJECT_ID('logs.ETL_Log') IS NOT NULL DROP TABLE logs.ETL_Log;
GO

CREATE TABLE logs.ETL_Log (
    Id_Log              INT IDENTITY(1,1) PRIMARY KEY,
    Execucao_Id         UNIQUEIDENTIFIER NOT NULL,
    Fase                VARCHAR(50)  NOT NULL,
    Passo               VARCHAR(100) NOT NULL,
    Status              VARCHAR(20)  NOT NULL,
    Registros_Lidos     INT NULL,
    Registros_Escritos  INT NULL,
    Registros_Rejeitados INT NULL,
    Dt_Inicio           DATETIME NOT NULL,
    Dt_Fim              DATETIME NULL,
    Duracao_Segundos    INT NULL,
    Mensagem            VARCHAR(500) NULL,
    Erro_Numero         INT NULL,
    Erro_Severidade     INT NULL
);
GO

CREATE INDEX IX_ETL_Log_Exec ON logs.ETL_Log(Execucao_Id);
CREATE INDEX IX_ETL_Log_Status ON logs.ETL_Log(Status);
CREATE INDEX IX_ETL_Log_Data ON logs.ETL_Log(Dt_Inicio);
GO

IF OBJECT_ID('logs.Ficheiros_Processados') IS NOT NULL DROP TABLE logs.Ficheiros_Processados;
GO

CREATE TABLE logs.Ficheiros_Processados (
    Id                  INT IDENTITY(1,1) PRIMARY KEY,
    Execucao_Id         UNIQUEIDENTIFIER NOT NULL,
    CaminhoFicheiro     VARCHAR(500) NOT NULL,
    NomeFicheiro        VARCHAR(200) NOT NULL,
    TipoFicheiro        VARCHAR(20)  NOT NULL,
    RegistosLidos       INT NULL,
    Status              VARCHAR(20)  NOT NULL,
    Dt_Processamento    DATETIME DEFAULT GETDATE()
);
GO

CREATE OR ALTER PROCEDURE logs.sp_ETL_LogInicio
    @Execucao_Id UNIQUEIDENTIFIER,
    @Fase        VARCHAR(50),
    @Passo       VARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO logs.ETL_Log (Execucao_Id, Fase, Passo, Status, Dt_Inicio)
    VALUES (@Execucao_Id, @Fase, @Passo, 'INICIO', GETDATE());
END;
GO

CREATE OR ALTER PROCEDURE logs.sp_ETL_LogFim
    @Execucao_Id  UNIQUEIDENTIFIER,
    @Fase         VARCHAR(50),
    @Passo        VARCHAR(100),
    @Status       VARCHAR(20),
    @Lidos        INT = NULL,
    @Escritos     INT = NULL,
    @Rejeitados   INT = NULL,
    @Mensagem     VARCHAR(500) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE logs.ETL_Log
    SET Status              = @Status,
        Registros_Lidos     = @Lidos,
        Registros_Escritos  = @Escritos,
        Registros_Rejeitados = @Rejeitados,
        Dt_Fim              = GETDATE(),
        Duracao_Segundos    = DATEDIFF(SECOND, Dt_Inicio, GETDATE()),
        Mensagem            = @Mensagem
    WHERE Execucao_Id = @Execucao_Id
      AND Fase = @Fase
      AND Passo = @Passo
      AND Status = 'INICIO';
END;
GO

CREATE OR ALTER PROCEDURE logs.sp_ETL_RegistarErro
    @Execucao_Id    UNIQUEIDENTIFIER,
    @Fase           VARCHAR(50),
    @Passo          VARCHAR(100),
    @Erro_Numero    INT = NULL,
    @Erro_Mensagem  NVARCHAR(4000) = NULL,
    @Erro_Severidade INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO logs.ETL_Log (Execucao_Id, Fase, Passo, Status, Dt_Inicio, Dt_Fim,
                              Mensagem, Erro_Numero, Erro_Severidade)
    VALUES (@Execucao_Id, @Fase, @Passo, 'ERRO', GETDATE(), GETDATE(),
            LEFT(ISNULL(@Erro_Mensagem, ''), 500), @Erro_Numero, @Erro_Severidade);
END;
GO

CREATE SYNONYM dbo.sp_ETL_LogInicio FOR logs.sp_ETL_LogInicio;
CREATE SYNONYM dbo.sp_ETL_LogFim FOR logs.sp_ETL_LogFim;
CREATE SYNONYM dbo.sp_ETL_RegistarErro FOR logs.sp_ETL_RegistarErro;
GO

PRINT 'logs.* criado: ETL_Log, Ficheiros_Processados, 3 SPs, 3 synonyms';
GO
