-- ============================================================================
-- 18_Create_EW_Tables.sql
-- Early Warning tables: flood events catalog + detection layer
-- Schema: ml (operational ML outputs, not star schema)
-- ============================================================================

USE PreFlood_DW;
GO

IF OBJECT_ID('ml.ew_flood_events') IS NOT NULL DROP TABLE ml.ew_flood_events;
GO

CREATE TABLE ml.ew_flood_events (
    event_id                 BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk               INT          NOT NULL,
    event_start              DATETIME2    NOT NULL,
    event_peak               DATETIME2    NULL,
    event_end                DATETIME2    NOT NULL,
    duration_hours           INT          NOT NULL,
    peak_value               FLOAT        NOT NULL,
    rise_rate                FLOAT        NULL,
    start_value              FLOAT        NOT NULL,
    end_value                FLOAT        NOT NULL,
    antecedent_precip_6h     FLOAT        NULL,
    antecedent_precip_24h    FLOAT        NULL,
    antecedent_soil_moisture FLOAT        NULL,
    threshold_p95            FLOAT        NOT NULL
);
CREATE CLUSTERED INDEX IX_ew_flood_events_sk ON ml.ew_flood_events (estacao_sk, event_start DESC);
CREATE NONCLUSTERED INDEX IX_ew_flood_events_peak ON ml.ew_flood_events (estacao_sk, peak_value DESC);
GO

IF OBJECT_ID('ml.ew_detections') IS NOT NULL DROP TABLE ml.ew_detections;
GO

CREATE TABLE ml.ew_detections (
    detection_id              BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
    estacao_sk                INT          NOT NULL,
    detection_ts              DATETIME2    NOT NULL,
    layer1_percentile_score   FLOAT        NULL,
    layer1_details            NVARCHAR(500) NULL,
    layer2_sequence_score     FLOAT        NULL,
    layer2_details            NVARCHAR(500) NULL,
    layer3_combined_score     FLOAT        NULL,
    lead_time_hours           FLOAT        NULL
);
CREATE CLUSTERED INDEX IX_ew_detections_sk ON ml.ew_detections (estacao_sk, detection_ts DESC);
GO

PRINT 'ml.* criado: ew_flood_events, ew_detections';
GO
