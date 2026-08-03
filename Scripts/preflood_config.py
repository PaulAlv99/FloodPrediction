import os

DB_SERVER = os.environ.get('PRE_FLOOD_DB_SERVER', 'localhost')
DB_NAME   = os.environ.get('PRE_FLOOD_DB_NAME', 'PreFlood_DW')
DB_DRIVER = '{ODBC Driver 17 for SQL Server}'

SCRIPTS_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR  = os.path.dirname(SCRIPTS_DIR)
RAW_DIR      = os.path.join(PROJECT_DIR, 'DataLake', 'Raw')
LANDING_DIR  = os.path.join(PROJECT_DIR, 'Landing')
LOGS_DIR     = os.path.join(PROJECT_DIR, 'Logs')
MODELS_DIR   = os.path.join(PROJECT_DIR, 'Models')

SCHEMA_MAP = {
    'brz': 'brz',
    'silver': 'silver',
    'gold': 'gold',
    'logs': 'logs',
    'ml': 'ml',
    'quarentena': 'quarentena',
    'ctl': 'ctl',
}

NATURAL_STATIONS = [229, 232, 233, 234]
DAM_STATIONS     = [223, 224, 225, 226, 228, 230, 235]
ALL_SNIRH_STATIONS = NATURAL_STATIONS + DAM_STATIONS

IPMA_URL_OBS = 'https://api.ipma.pt/open-data/observation/meteorology/stations/observations.json'
IPMA_URL_EST = 'https://api.ipma.pt/open-data/observation/meteorology/stations/stations.json'
SNIRH_BACIA  = 47


def get_conn(autocommit: bool = True):
    import pyodbc
    conn_str = (
        f'DRIVER={DB_DRIVER};'
        f'SERVER={DB_SERVER};'
        f'DATABASE={DB_NAME};'
        f'Trusted_Connection=yes;'
    )
    return pyodbc.connect(conn_str, autocommit=autocommit)


def get_conn_str() -> str:
    return (
        f'DRIVER={DB_DRIVER};'
        f'SERVER={DB_SERVER};'
        f'DATABASE={DB_NAME};'
        f'Trusted_Connection=yes;'
    )
