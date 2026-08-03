-- ============================================================================
-- 06_Create_Quarentena.sql
-- Quarentena: registos rejeitados pela validacao Bronze->Silver
-- Schema: quarentena
-- ============================================================================

USE PreFlood_DW;
GO

IF OBJECT_ID('quarentena.ETL_Quarentena') IS NOT NULL DROP TABLE quarentena.ETL_Quarentena;
GO

CREATE TABLE quarentena.ETL_Quarentena (
    Id_Quarentena   INT IDENTITY(1,1) PRIMARY KEY,
    Execucao_Id     UNIQUEIDENTIFIER NOT NULL,
    Fonte           VARCHAR(50)     NOT NULL,
    Chave_Registo   VARCHAR(200)    NULL,
    Dados_Registo   NVARCHAR(MAX)   NULL,
    Motivo          VARCHAR(500)    NOT NULL,
    Dt_Quarentena   DATETIME DEFAULT GETDATE(),
    Resolvido       BIT DEFAULT 0
);
GO

CREATE INDEX IX_Quarentena_Fonte ON quarentena.ETL_Quarentena(Fonte);
CREATE INDEX IX_Quarentena_Data ON quarentena.ETL_Quarentena(Dt_Quarentena);
GO

PRINT 'quarentena.ETL_Quarentena criado';
GO
