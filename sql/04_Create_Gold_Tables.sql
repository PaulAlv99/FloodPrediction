-- ============================================================================
-- 04_Create_Gold_Tables.sql
-- Gold layer: star schema — dims + facts ONLY (ML tables in ml schema)
-- Schema: gold
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE gold.dim_bacia (
    bacia_codigo   BIGINT         PRIMARY KEY,
    bacia_nome     NVARCHAR(100)  NOT NULL
);

CREATE TABLE gold.dim_estacao (
    estacao_sk     INT IDENTITY(1,1) PRIMARY KEY,
    estacao_id     VARCHAR(50)   NOT NULL,
    estacao_nome   NVARCHAR(200) NOT NULL,
    sistema_origem VARCHAR(20)   NOT NULL,
    latitude       FLOAT         NULL,
    longitude      FLOAT         NULL,
    bacia_codigo   BIGINT        NULL REFERENCES gold.dim_bacia(bacia_codigo),
    ativa          BIT           DEFAULT 1,
    data_criacao   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT UQ_estacao UNIQUE (estacao_id, sistema_origem)
);
CREATE INDEX IX_estacao_origem ON gold.dim_estacao(sistema_origem);
CREATE INDEX IX_estacao_coords ON gold.dim_estacao(latitude, longitude) WHERE latitude IS NOT NULL;

CREATE TABLE gold.dim_tempo (
    tempo_sk        INT IDENTITY(1,1) PRIMARY KEY,
    data_hora       DATETIME2     NOT NULL,
    data            DATE          NOT NULL,
    hora            INT           NOT NULL,
    ano             SMALLINT      NOT NULL,
    mes             TINYINT       NOT NULL,
    dia             TINYINT       NOT NULL,
    trimestre       TINYINT       NOT NULL,
    semana_ano      TINYINT       NOT NULL,
    dia_ano         SMALLINT      NOT NULL,
    dia_semana      TINYINT       NOT NULL,
    dia_semana_nome NVARCHAR(20)  NOT NULL,
    fim_de_semana   BIT           NOT NULL,
    estacao_do_ano  NVARCHAR(20)  NOT NULL,
    CONSTRAINT UQ_tempo UNIQUE (data_hora)
);

CREATE TABLE gold.dim_parametro (
    parametro_sk     INT IDENTITY(1,1) PRIMARY KEY,
    parametro_id     INT            NOT NULL,
    parametro_nome   NVARCHAR(200)  NOT NULL,
    parametro_codigo VARCHAR(50)    NOT NULL,
    categoria        NVARCHAR(50)   NOT NULL,
    unidade_medida   NVARCHAR(30)   NOT NULL,
    sistema_origem   VARCHAR(20)    NOT NULL,
    granularidade    VARCHAR(20)    NULL,
    CONSTRAINT UQ_parametro UNIQUE (parametro_id, sistema_origem)
);

CREATE TABLE gold.fact_medicao (
    medicao_id    BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk    INT       NOT NULL REFERENCES gold.dim_estacao(estacao_sk),
    tempo_sk      INT       NOT NULL REFERENCES gold.dim_tempo(tempo_sk),
    parametro_sk  INT       NOT NULL REFERENCES gold.dim_parametro(parametro_sk),
    valor         FLOAT     NOT NULL,
    data_ingestao DATETIME2 DEFAULT GETDATE(),
    CONSTRAINT UQ_medicao UNIQUE (estacao_sk, tempo_sk, parametro_sk)
);
CREATE CLUSTERED INDEX IX_fact_tempo ON gold.fact_medicao(tempo_sk, estacao_sk);
CREATE NONCLUSTERED INDEX IX_fact_param ON gold.fact_medicao(parametro_sk);

GO

PRINT 'Gold tables criados: 4 dims + 1 fact (sem tabelas ML — estao em ml.*)';
GO
