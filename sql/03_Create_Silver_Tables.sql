-- ============================================================================
-- 03_Create_Silver_Tables.sql
-- Silver layer (stg schema): typed, cleaned, validated data
-- stg IS the silver layer — no separate staging
-- ============================================================================

USE PreFlood_DW;
GO

CREATE TABLE silver.ipma_stations (
    station_id     VARCHAR(50)   NOT NULL,
    station_name   NVARCHAR(200) NULL,
    latitude       FLOAT         NULL,
    longitude      FLOAT         NULL,
    bacia_codigo   BIGINT        DEFAULT 47,
    ingestion_ts   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_stg_ipma_st PRIMARY KEY (station_id)
);

CREATE TABLE silver.ipma_observations (
    observation_datetime DATETIME2     NOT NULL,
    station_id           VARCHAR(50)   NOT NULL,
    parametro_id         INT           NOT NULL,
    valor                FLOAT         NOT NULL,
    ingestion_ts         DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_stg_ipma_obs PRIMARY KEY NONCLUSTERED (observation_datetime, station_id, parametro_id)
);
CREATE CLUSTERED INDEX IX_silver_ipma_obs_dt ON silver.ipma_observations(observation_datetime);

CREATE TABLE silver.snirh_stations (
    station_id     VARCHAR(50)   NOT NULL,
    station_name   NVARCHAR(200) NULL,
    latitude       FLOAT         NULL,
    longitude      FLOAT         NULL,
    bacia_codigo   BIGINT        DEFAULT 47,
    ingestion_ts   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_stg_snirh_st PRIMARY KEY (station_id)
);

CREATE TABLE silver.snirh_observations (
    observation_datetime DATETIME2     NOT NULL,
    station_id           VARCHAR(50)   NOT NULL,
    parametro_id         BIGINT        NOT NULL,
    valor                FLOAT         NOT NULL,
    granularidade        VARCHAR(20)   NULL,
    ingestion_ts         DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT PK_silver_snirh_obs PRIMARY KEY NONCLUSTERED (observation_datetime, station_id, parametro_id)
);
CREATE CLUSTERED INDEX IX_silver_snirh_obs_dt ON silver.snirh_observations(observation_datetime);

CREATE TABLE silver.era5_locations (
    location_id    INT IDENTITY(1,1) PRIMARY KEY,
    location_label NVARCHAR(200) NOT NULL,
    latitude       FLOAT         NOT NULL,
    longitude      FLOAT         NOT NULL,
    ingestion_ts   DATETIME2     DEFAULT GETDATE(),
    CONSTRAINT UQ_stg_era5_loc UNIQUE (latitude, longitude)
);

CREATE TABLE silver.era5_observations (
    observation_datetime   DATETIME2 NOT NULL,
    location_id            INT       NOT NULL REFERENCES silver.era5_locations(location_id),
    temperature_2m         FLOAT NULL,
    dewpoint_2m            FLOAT NULL,
    precipitation_total    FLOAT NULL,
    surface_pressure       FLOAT NULL,
    skin_temperature       FLOAT NULL,
    snow_depth             FLOAT NULL,
    soil_temperature_l1    FLOAT NULL,
    soil_temperature_l2    FLOAT NULL,
    soil_temperature_l3    FLOAT NULL,
    soil_temperature_l4    FLOAT NULL,
    soil_water_level_1     FLOAT NULL,
    soil_water_level_2     FLOAT NULL,
    soil_water_level_3     FLOAT NULL,
    soil_water_level_4     FLOAT NULL,
    wind_u_10m             FLOAT NULL,
    wind_v_10m             FLOAT NULL,
    solar_radiation_down   FLOAT NULL,
    thermal_radiation_down FLOAT NULL,
    ingestion_ts           DATETIME2 DEFAULT GETDATE(),
    CONSTRAINT PK_stg_era5_obs PRIMARY KEY NONCLUSTERED (observation_datetime, location_id)
);
GO

PRINT 'Silver (stg) tables criados';
GO
