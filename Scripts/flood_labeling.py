import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime
import pyodbc

from preflood_config import DB_NAME, get_conn, NATURAL_STATIONS

FLOOD_HORIZONS = [6, 12, 24]
QUANTILE_THRESHOLD = 0.95
MIN_HISTORY_H = 8760

BACKTEST_EVENTS = [
    {'name': 'Cheia Jan 2001', 'start': '2001-01-25', 'end': '2001-01-30'},
    {'name': 'Cheia Jan-Fev 2016', 'start': '2016-01-01', 'end': '2016-02-29'},
    {'name': 'Cheia Dez 2019', 'start': '2019-12-01', 'end': '2019-12-31'},
    {'name': 'Cheia Fev 2026', 'start': '2026-02-01', 'end': '2026-02-28'},
]


def load_nivel_series(conn):
    print('[DATA] Loading SNIRH NIVEL_INST series...')
    query = """
        SELECT e.estacao_sk, t.data_hora, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE e.sistema_origem = 'SNIRH'
          AND e.estacao_sk IN ({})
          AND p.parametro_codigo IN ('1843')
        ORDER BY e.estacao_sk, t.data_hora
    """.format(','.join(str(s) for s in NATURAL_STATIONS))
    df = pd.read_sql(query, conn)
    df.columns = ['estacao_sk', 'data_hora', 'nivel']
    df['data_hora'] = pd.to_datetime(df['data_hora'])
    df = df.drop_duplicates(subset=['estacao_sk', 'data_hora'])
    df = df.sort_values(['estacao_sk', 'data_hora']).reset_index(drop=True)
    print('  Loaded {:,} rows for {} stations'.format(len(df), df['estacao_sk'].nunique()))
    return df


def compute_thresholds(df):
    thresholds = {}
    for sk in df['estacao_sk'].unique():
        sub = df[df['estacao_sk'] == sk]
        nivel = sub['nivel'].dropna()
        if len(nivel) < MIN_HISTORY_H:
            print('  WARNING: SK={} has only {} rows, skipping'.format(sk, len(nivel)))
            continue
        thresholds[sk] = {
            'p90': float(nivel.quantile(0.90)),
            'p95': float(nivel.quantile(0.95)),
            'p99': float(nivel.quantile(0.99)),
            'mean': float(nivel.mean()),
            'std': float(nivel.std()),
            'max': float(nivel.max()),
        }
    print('[THRESHOLDS] Computed for {} stations'.format(len(thresholds)))
    return thresholds


def build_flood_labels(df, thresholds):
    print('[LABELS] Generating binary flood labels...')
    labeled_frames = []
    for sk in df['estacao_sk'].unique():
        sub = df[df['estacao_sk'] == sk].copy()
        sub = sub.sort_values('data_hora').reset_index(drop=True)
        nivel = sub['nivel'].values
        thresh = thresholds.get(sk, {})
        p95 = thresh.get('p95', np.inf)

        for horizon in FLOOD_HORIZONS:
            col = 'flood_{}h'.format(horizon)
            labels = np.zeros(len(sub), dtype=np.int32)
            for i in range(len(sub) - horizon):
                future_max = np.max(nivel[i + 1:i + 1 + horizon])
                if future_max > p95:
                    labels[i] = 1
            sub[col] = labels
            n_pos = labels.sum()
            pct = 100.0 * n_pos / len(labels) if len(labels) > 0 else 0
            print('  SK={} {}h: {:,} flood events ({:.2f}%)'.format(sk, horizon, n_pos, pct))

        sub['nivel_p95'] = p95
        labeled_frames.append(sub)

    result = pd.concat(labeled_frames, ignore_index=True)
    total_cols = [c for c in result.columns if c.startswith('flood_')]
    for col in total_cols:
        print('  Total {}: {:,} / {:,} ({:.2f}%)'.format(
            col, result[col].sum(), len(result), 100.0 * result[col].sum() / len(result)))
    return result


def validate_backtest(labeled_df, thresholds):
    print()
    print('[BACKTEST] Validating against known flood events...')
    for event in BACKTEST_EVENTS:
        start = pd.Timestamp(event['start'])
        end = pd.Timestamp(event['end'])
        mask = (labeled_df['data_hora'] >= start) & (labeled_df['data_hora'] <= end)
        event_data = labeled_df[mask]
        if len(event_data) == 0:
            print('  {}: NO DATA'.format(event['name']))
            continue
        for horizon in FLOOD_HORIZONS:
            col = 'flood_{}h'.format(horizon)
            n_flood = event_data[col].sum()
            n_total = len(event_data)
            print('  {} {}h: {:,}/{:,} timestamps flagged ({:.1f}%)'.format(
                event['name'], horizon, n_flood, n_total,
                100.0 * n_flood / n_total if n_total > 0 else 0))


def save_labels(conn, labeled_df, thresholds):
    print('[SAVE] Saving flood labels...')
    cur = conn.cursor()
    cur.execute("IF OBJECT_ID('ml.flood_labels') IS NOT NULL DROP TABLE ml.flood_labels")
    cur.execute("""
        CREATE TABLE ml.flood_labels (
            id BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
            estacao_sk INT NOT NULL,
            data_hora DATETIME2 NOT NULL,
            nivel FLOAT NOT NULL,
            nivel_p95 FLOAT NULL,
            flood_6h BIT DEFAULT 0,
            flood_12h BIT DEFAULT 0,
            flood_24h BIT DEFAULT 0
        )
    """)
    cur.execute("CREATE CLUSTERED INDEX IX_flood_labels ON ml.flood_labels (estacao_sk, data_hora)")

    insert_sql = """
        INSERT INTO ml.flood_labels (estacao_sk, data_hora, nivel, nivel_p95, flood_6h, flood_12h, flood_24h)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    batch = []
    BATCH_SIZE = 5000
    total = 0
    for _, row in labeled_df.iterrows():
        batch.append((
            int(row['estacao_sk']),
            row['data_hora'],
            float(row['nivel']),
            float(row.get('nivel_p95', 0)),
            int(row.get('flood_6h', 0)),
            int(row.get('flood_12h', 0)),
            int(row.get('flood_24h', 0)),
        ))
        if len(batch) >= BATCH_SIZE:
            cur.executemany(insert_sql, batch)
            conn.commit()
            total += len(batch)
            batch = []
    if batch:
        cur.executemany(insert_sql, batch)
        conn.commit()
        total += len(batch)
    print('  ml.flood_labels: {:,} rows'.format(total))

    cur.execute("IF OBJECT_ID('ctl.flood_thresholds') IS NOT NULL DROP TABLE ctl.flood_thresholds")
    cur.execute("""
        CREATE TABLE ctl.flood_thresholds (
            estacao_sk INT PRIMARY KEY,
            p90 FLOAT, p95 FLOAT, p99 FLOAT,
            mean_nivel FLOAT, std_nivel FLOAT, max_nivel FLOAT
        )
    """)
    for sk, t in thresholds.items():
        cur.execute(
            "INSERT INTO ctl.flood_thresholds VALUES (?, ?, ?, ?, ?, ?, ?)",
            int(sk), t['p90'], t['p95'], t['p99'], t['mean'], t['std'], t['max'])
    conn.commit()
    print('  ctl.flood_thresholds: {} rows'.format(len(thresholds)))


def main():
    start = datetime.now()
    print('=' * 80)
    print('  FLOOD LABELING v1.0')
    print('  Time: {}'.format(start))
    print('=' * 80)

    conn = get_conn()
    try:
        df = load_nivel_series(conn)
        thresholds = compute_thresholds(df)
        labeled = build_flood_labels(df, thresholds)
        validate_backtest(labeled, thresholds)
        save_labels(conn, labeled, thresholds)
        print('  Done in {}'.format(datetime.now() - start))
    except Exception as e:
        print('ERROR: {}'.format(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
