import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime
import pyodbc

from preflood_config import DB_NAME, get_conn, NATURAL_STATIONS

RISK_LEVELS = ['BAIXO', 'MODERADO', 'ALTO', 'CRITICO']


def load_thresholds(conn):
    cur = conn.cursor()
    cur.execute("SELECT estacao_sk, p50, p75, p90, p95, p99, max_hist FROM ctl.ml_risk_thresholds")
    thresholds = {}
    for row in cur:
        thresholds[row[0]] = {
            'p50': row[1], 'p75': row[2], 'p90': row[3],
            'p95': row[4], 'p99': row[5], 'max_hist': row[6],
        }
    return thresholds


def load_flood_thresholds(conn):
    cur = conn.cursor()
    cur.execute("SELECT estacao_sk, p90, p95, p99, mean_nivel, std_nivel, max_nivel FROM ctl.flood_thresholds")
    thresholds = {}
    for row in cur:
        thresholds[row[0]] = {
            'p90': row[1], 'p95': row[2], 'p99': row[3],
            'mean': row[4], 'std': row[5], 'max': row[6],
        }
    return thresholds


def classify_risk(nivel, taxa_subida_6h, precip_24h, soil_sat, thresholds_sk):
    if thresholds_sk is None:
        return 'BAIXO', 0.0

    score = 0.0
    p50 = thresholds_sk.get('p50', 0)
    p75 = thresholds_sk.get('p75', 0)
    p90 = thresholds_sk.get('p90', 0)
    p95 = thresholds_sk.get('p95', 0)
    p99 = thresholds_sk.get('p99', 0)

    if nivel >= p99:
        score += 5.0
    elif nivel >= p95:
        score += 4.0
    elif nivel >= p90:
        score += 3.0
    elif nivel >= p75:
        score += 1.5
    elif nivel >= p50:
        score += 0.5

    if taxa_subida_6h is not None:
        if taxa_subida_6h > 0.20:
            score += 4.0
        elif taxa_subida_6h > 0.10:
            score += 3.0
        elif taxa_subida_6h > 0.05:
            score += 2.0
        elif taxa_subida_6h > 0.02:
            score += 1.0

    if precip_24h is not None:
        if precip_24h > 30:
            score += 3.0
        elif precip_24h > 15:
            score += 2.0
        elif precip_24h > 5:
            score += 1.0

    if soil_sat is not None:
        if soil_sat > 0.95:
            score += 2.0
        elif soil_sat > 0.80:
            score += 1.0

    max_score = 14.0
    pct = min(score / max_score, 1.0)

    if pct >= 0.80:
        level = 'CRITICO'
    elif pct >= 0.55:
        level = 'ALTO'
    elif pct >= 0.30:
        level = 'MODERADO'
    else:
        level = 'BAIXO'

    return level, pct


def classify_from_predictions(predictions, conn):
    risk_thresholds = load_thresholds(conn)
    results = []
    for pred in predictions:
        sk = pred.get('estacao_sk')
        nivel = pred.get('predicted_value', 0)
        taxa = pred.get('taxa_subida_6h')
        precip = pred.get('precip_accum_24h')
        soil = pred.get('soil_saturation')
        ts = thresholds_sk = risk_thresholds.get(sk)
        level, pct = classify_risk(nivel, taxa, precip, soil, ts)
        results.append({
            'estacao_sk': sk,
            'nivel_alerta': level,
            'risco_percentil': pct,
            'nivel_atual': nivel,
        })
    return results


if __name__ == '__main__':
    print('Risk classifier module — import and use classify_risk()')
