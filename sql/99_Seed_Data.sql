-- ============================================================================
-- 99_Seed_Data.sql
-- Dados iniciais: dim_bacia, dim_parametro
-- ============================================================================

USE PreFlood_DW;
GO

INSERT INTO gold.dim_bacia (bacia_codigo, bacia_nome) VALUES (47, N'Bacia do Mondego');
GO

INSERT INTO gold.dim_parametro (parametro_id, parametro_nome, parametro_codigo, categoria, unidade_medida, sistema_origem, granularidade) VALUES
-- IPMA (1-8)
(1,  N'Temperatura',        'temp',   'Meteorologica', 'C',     'IPMA', 'HORARIA'),
(2,  N'Humidade',           'humi',   'Meteorologica', '%',     'IPMA', 'HORARIA'),
(3,  N'Pressao',            'press',  'Meteorologica', 'hPa',   'IPMA', 'HORARIA'),
(4,  N'Vento Km',           'vkm',    'Vento',         'km/h',  'IPMA', 'HORARIA'),
(5,  N'Vento Ms',           'vms',    'Vento',         'm/s',   'IPMA', 'HORARIA'),
(6,  N'Precipitacao',       'prec',   'Meteorologica', 'mm',    'IPMA', 'HORARIA'),
(7,  N'Radiacao',           'rad',    'Meteorologica', 'W/m2',  'IPMA', 'HORARIA'),
(8,  N'Vento Direccao',     'vdir',   'Vento',         'graus', 'IPMA', 'HORARIA'),
-- SNIRH (10-15)
(10, N'Caudal Medio Diario','1850',   'Hidrologica',   'm3/s',  'SNIRH', 'DIARIA'),
(11, N'Nivel Medio Diario', '1845',   'Hidrologica',   'm',     'SNIRH', 'DIARIA'),
(12, N'Nivel Instantaneo',  '1843',   'Hidrologica',   'm',     'SNIRH', 'HORARIA'),
(14, N'Caudal Horario',     '3212219030','Hidrologica', 'm3/s',  'SNIRH', 'HORARIA'),
(15, N'Cota Ultima Hora',   '354895424', 'Hidrologica','m',     'SNIRH', 'HORARIA'),
-- ERA5 (51-68)
(51, N'Temperature 2m',        't2m',     'Meteorologica', 'K',    'ERA5', 'HORARIA'),
(52, N'Dewpoint 2m',           'd2m',     'Meteorologica', 'K',    'ERA5', 'HORARIA'),
(53, N'Total Precipitation',   'tp',      'Meteorologica', 'm',    'ERA5', 'HORARIA'),
(54, N'Surface Pressure',      'sp',      'Meteorologica', 'Pa',   'ERA5', 'HORARIA'),
(55, N'Skin Temperature',      'skt',     'Meteorologica', 'K',    'ERA5', 'HORARIA'),
(56, N'Snow Depth',            'sde',     'Meteorologica', 'm',    'ERA5', 'HORARIA'),
(57, N'Soil Temperature L1',   'stl1',    'Solo',          'K',    'ERA5', 'HORARIA'),
(58, N'Soil Temperature L2',   'stl2',    'Solo',          'K',    'ERA5', 'HORARIA'),
(59, N'Soil Temperature L3',   'stl3',    'Solo',          'K',    'ERA5', 'HORARIA'),
(60, N'Soil Temperature L4',   'stl4',    'Solo',          'K',    'ERA5', 'HORARIA'),
(61, N'Volumetric Soil Water L1','swvl1', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(62, N'Volumetric Soil Water L2','swvl2', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(63, N'Volumetric Soil Water L3','swvl3', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(64, N'Volumetric Soil Water L4','swvl4', 'Solo',          'm3/m3','ERA5', 'HORARIA'),
(65, N'Wind U 10m',            'u10',     'Vento',         'm/s',  'ERA5', 'HORARIA'),
(66, N'Wind V 10m',            'v10',     'Vento',         'm/s',  'ERA5', 'HORARIA'),
(67, N'Solar Radiation Down',  'ssrd',    'Radiacao',      'J/m2', 'ERA5', 'HORARIA'),
(68, N'Thermal Radiation Down','strd',    'Radiacao',      'J/m2', 'ERA5', 'HORARIA');
GO

PRINT 'Seed data inserido: dim_bacia (1), dim_parametro (30)';
GO
