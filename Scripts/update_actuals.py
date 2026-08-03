import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from preflood_config import DB_NAME, get_conn

SNIRH_TARGET_MAP = {
    'COTA_ALBUF': 'COTA_ALBUF',
    'COTA_ULTIMA_H': 'COTA_ULTIMA_H',
    'NIVEL_INST': '1843',
}


def find_pending_predictions(conn):
    df = pd.read_sql("""
        SELECT p.prediction_id, p.estacao_sk, p.estacao_nome,
               p.target_parametro, p.horizon_hours,
               p.predicted_value, p.prediction_time, p.target_time
        FROM ml.forecast_predictions p
        WHERE p.actual_value IS NULL
          AND p.target_time < GETDATE()
        ORDER BY p.target_time DESC
    """, conn)
    return df


def resolve_parametro_sk(conn, target_parametro):
    code = SNIRH_TARGET_MAP.get(target_parametro, target_parametro)
    cur = conn.cursor()
    cur.execute(
        "SELECT parametro_sk FROM gold.dim_parametro "
        "WHERE parametro_codigo = ?", code)
    row = cur.fetchone()
    return row[0] if row else None


def update_actuals(conn, pending_df, dry_run=False):
    if pending_df.empty:
        print('  Sem predicoes para actualizadas.')
        return

    updated = 0
    not_found = 0

    targets = pending_df['target_parametro'].unique()
    param_sks = {}
    for tp in targets:
        sk = resolve_parametro_sk(conn, tp)
        if sk:
            param_sks[tp] = sk
            print('  {} -> parametro_sk={}'.format(tp, sk))
        else:
            print('  AVISO: parametro_sk nao encontrado para {}'.format(tp))

    cur = conn.cursor()

    for _, row in pending_df.iterrows():
        tp = row['target_parametro']
        if tp not in param_sks:
            not_found += 1
            continue

        psk = param_sks[tp]

        cur.execute("""
            SELECT f.valor
            FROM gold.fact_medicao f
            INNER JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
            WHERE f.estacao_sk = ?
              AND f.parametro_sk = ?
              AND t.data_hora = ?
        """, int(row['estacao_sk']), psk, row['target_time'])

        result = cur.fetchone()
        if result and result[0] is not None:
            actual = float(result[0])
            if not dry_run:
                cur.execute("""
                    UPDATE ml.forecast_predictions
                    SET actual_value = ?
                    WHERE prediction_id = ?
                """, actual, int(row['prediction_id']))
            updated += 1
        else:
            not_found += 1

    if not dry_run:
        conn.commit() if not conn.autocommit else None
        print('  {} predicoes actualizadas com valor real'.format(updated))
        if not_found > 0:
            print('  {} sem valor real disponivel (dados ainda nao ingeridos)'.format(not_found))
    else:
        print('  [DRY RUN] {} seriam actualizadas, {} sem dados'.format(updated, not_found))

    return updated


def print_accuracy_report(conn):
    metrics = pd.read_sql("""
        SELECT
            estacao_nome,
            target_parametro,
            horizon_hours,
            COUNT(*) AS n_with_actual,
            AVG(ABS(predicted_value - actual_value)) AS mae,
            AVG(ABS(predicted_value - actual_value)
                / NULLIF(ABS(actual_value), 0) * 100) AS mape_pct,
            CASE
                WHEN AVG(ABS(predicted_value - actual_value)
                    / NULLIF(ABS(actual_value), 0) * 100) < 5 THEN 'EXCELENTE'
                WHEN AVG(ABS(predicted_value - actual_value)
                    / NULLIF(ABS(actual_value), 0) * 100) < 10 THEN 'BOM'
                WHEN AVG(ABS(predicted_value - actual_value)
                    / NULLIF(ABS(actual_value), 0) * 100) < 20 THEN 'RAZOAVEL'
                ELSE 'MAU'
            END AS qualidade
        FROM ml.forecast_predictions
        WHERE actual_value IS NOT NULL
        GROUP BY estacao_nome, target_parametro, horizon_hours
        ORDER BY estacao_nome, target_parametro, horizon_hours
    """, conn)

    if metrics.empty:
        print('\n  Sem dados com actual_value para calcular metricas.')
        return

    print('\n' + '=' * 70)
    print('RELATORIO DE QUALIDADE DAS PREVISOES')
    print('=' * 70)
    for _, m in metrics.iterrows():
        print('  {:25s} {:15s} +{:>2d}h: MAE={:>8.3f} MAPE={:>5.1f}% [{}]'.format(
            m['estacao_nome'][:25], m['target_parametro'], m['horizon_hours'],
            m['mae'], m['mape_pct'] or 0, m['qualidade']))


def main():
    dry_run = '--dry-run' in sys.argv
    conn = get_conn()

    print('[1/2] Procurar predicoes sem valor real...')
    pending = find_pending_predictions(conn)
    print('  {} predicoes pendentes'.format(len(pending)))

    if not pending.empty:
        print('\n[2/2] Actualizar com valores reais...')
        update_actuals(conn, pending, dry_run)

    print_accuracy_report(conn)

    conn.close()
    print('\nupdate_actuals concluido!')


if __name__ == '__main__':
    main()
