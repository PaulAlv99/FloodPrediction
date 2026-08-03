import os
import sys
import shutil
import pyodbc
from preflood_config import DB_NAME
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_DIR, 'DataLake', 'Raw')
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'Output')


def drop_database():
    print('[DROP DATABASE] {}'.format(DB_NAME))
    try:
        conn = pyodbc.connect(
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=localhost;DATABASE=master;Trusted_Connection=yes;',
            autocommit=True)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sys.databases WHERE name = ?", DB_NAME)
        if cur.fetchone():
            cur.execute("ALTER DATABASE [{}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;".format(DB_NAME))
            cur.execute("DROP DATABASE [{}];".format(DB_NAME))
            print('  Database dropped.')
        else:
            print('  Database nao existe.')
        conn.close()
    except Exception as e:
        print('  ERRO: {}'.format(e))


def clean_bronze_silver():
    print('[BRONZE/SILVER CLEANUP]')
    try:
        conn = pyodbc.connect(
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=localhost;Database={};Trusted_Connection=yes;'.format(DB_NAME),
            autocommit=True)
        cur = conn.cursor()

        cur.execute("""
            SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA IN ('brz', 'stg')
        """)
        tables = cur.fetchall()
        for schema, table in tables:
            cur.execute("TRUNCATE TABLE [{}].[{}]".format(schema, table))
            print('  TRUNCATE {}.{}'.format(schema, table))

        conn.close()
    except Exception as e:
        print('  ERRO (DB pode nao existir): {}'.format(e))


def clean_ml_tables():
    print('[ML CLEANUP]')
    try:
        conn = pyodbc.connect(
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=localhost;Database={};Trusted_Connection=yes;'.format(DB_NAME),
            autocommit=True)
        cur = conn.cursor()
        for tbl in ['results', 'model_metrics']:
            cur.execute("IF OBJECT_ID('ml.{}','U') IS NOT NULL DROP TABLE ml.{}".format(tbl, tbl))
            print('  ml.{} dropped'.format(tbl))
        conn.close()
    except Exception as e:
        print('  ERRO (DB pode nao existir): {}'.format(e))


def delete_raw():
    print('[DELETE RAW] {}'.format(RAW_DIR))
    if os.path.exists(RAW_DIR):
        shutil.rmtree(RAW_DIR)
        print('  Pasta RAW apagada.')
    else:
        print('  Pasta RAW nao existe.')


def delete_output():
    print('[DELETE OUTPUT] {}'.format(OUTPUT_DIR))
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
        print('  Pasta Output apagada.')
    else:
        print('  Pasta Output nao existe.')


def main():
    args = set(sys.argv[1:])

    if '--ml-only' in args:
        clean_ml_tables()
        delete_output()
        print('ML cleanup concluido.')
        return

    if '--db-only' in args:
        drop_database()
        print('DB cleanup concluido.')
        return

    if '--raw-only' in args:
        delete_raw()
        delete_output()
        print('RAW cleanup concluido.')
        return

    if '--bronze-silver' in args:
        clean_bronze_silver()
        print('Bronze/Silver cleanup concluido.')
        return

    drop_database()
    delete_raw()
    delete_output()
    print('\nCleanup total concluido!')


if __name__ == '__main__':
    main()
