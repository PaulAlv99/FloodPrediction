import os
import sys
import json
import pyodbc
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

try:
    import tensorflow as tf
    from tensorflow import keras
    HAS_TF = True
except ImportError:
    HAS_TF = False

from sklearn.preprocessing import RobustScaler

from preflood_config import DB_NAME, get_conn
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
MODELS_DIR = os.path.join(PROJECT_DIR, 'Models')

NATURAL_STATIONS = [229, 232, 233, 234]
DAM_STATIONS = [223, 224, 225, 226, 228, 230, 235]
FORECAST_HORIZONS = [1, 3, 6, 12, 24]
ERA5_FEATURES = ['tp', 't2m', 'swvl1', 'sp']
ERA5_EXTRA = ['swvl2', 'swvl3', 'swvl4']

PARAM_ALIAS = {
    '1843': 'NIVEL_INST', '1845': 'NIVEL_MED_DIA', '1850': 'CAUDAL_MED_DIA',
    '3212219030': 'CAUDAL_DESC_DIA', '354895424': 'CAUDAL_AFLUENTE_DIA',
    'tp': 'PRECIPITACAO', 't2m': 'TEMP_2M',
    'swvl1': 'SOLO_UM_L1', 'swvl2': 'SOLO_UM_L2',
    'swvl3': 'SOLO_UM_L3', 'swvl4': 'SOLO_UM_L4', 'sp': 'PRESSAO_SUPERFICIE',
}
PRECIP_WINDOWS = [6, 12, 24, 48, 72, 168]
ROLLING_WINDOWS = [3, 6, 12, 24]
MODEL_VERSION = 'v5.0'
LSTM_HORIZONS = [6, 12, 24]
LSTM_LOOKBACK = 48
LSTM_FEATURES = [
    'nivel', 'nivel_lag_1h', 'nivel_lag_3h', 'nivel_lag_6h',
    'nivel_delta_1h', 'nivel_delta_3h', 'nivel_delta_6h',
    'nivel_rmean_6h', 'nivel_rmean_24h', 'nivel_rstd_24h',
    'era5_precip', 'era5_precip_accum_6h', 'era5_precip_accum_24h',
    'era5_temp', 'era5_soil_l1', 'era5_pressure',
    'hour_sin', 'hour_cos', 'month_sin', 'month_cos',
]


def load_config():
    with open(os.path.join(MODELS_DIR, 'features', 'feature_list.pkl'), 'rb') as f:
        feature_list = pickle.load(f)
    with open(os.path.join(MODELS_DIR, 'features', 'station_stats.pkl'), 'rb') as f:
        station_stats = pickle.load(f)
    return feature_list, station_stats


def load_spatial_maps(conn):
    cur = conn.cursor()
    cur.execute("SELECT source_station_sk, target_station_sk "
                "FROM ctl.map_spatial_proximity WHERE is_nearest = 1")
    prox_map = {}
    ipma_prox_map = {}
    for r in cur.fetchall():
        src, tgt = r[0], r[1]
        prox_map[src] = tgt

    cur.execute("SELECT sp.source_station_sk, sp.target_station_sk "
                "FROM ctl.map_spatial_proximity sp "
                "JOIN gold.dim_estacao e ON sp.target_station_sk = e.estacao_sk "
                "WHERE sp.is_nearest = 1 AND e.sistema_origem = 'IPMA'")
    for r in cur.fetchall():
        ipma_prox_map[r[0]] = r[1]

    cur.execute("SELECT estacao_sk, latitude, longitude FROM gold.dim_estacao "
                "WHERE estacao_sk IN (" + ','.join(['?'] * len(NATURAL_STATIONS)) + ")",
                NATURAL_STATIONS)
    station_geo = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    return prox_map, ipma_prox_map, station_geo


def load_recent_snirh(conn):
    cur = conn.cursor()
    all_sks = NATURAL_STATIONS + DAM_STATIONS
    sk_ph = ','.join(['?'] * len(all_sks))
    params = ['1843', '1845', '1850', '3212219030', '354895424']
    p_ph = ','.join(['?'] * len(params))
    cur.execute("""
        SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        WHERE e.estacao_sk IN (""" + sk_ph + """)
        AND p.parametro_codigo IN (""" + p_ph + """)
        AND t.data_hora >= DATEADD(HOUR, -400, GETDATE())
        ORDER BY t.data_hora
    """, all_sks + params)
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([(r[0], r[1], r[2], r[3]) for r in rows],
                      columns=['estacao_sk', 'data_hora', 'parametro_codigo', 'valor'])
    df.dropna(subset=['valor'], inplace=True)
    df['data_hora'] = pd.to_datetime(df['data_hora'])
    pivot = df.pivot_table(index='data_hora', columns=['estacao_sk', 'parametro_codigo'],
                           values='valor', aggfunc='first')
    pivot.columns = ['SK{}_{}'.format(c[0], PARAM_ALIAS.get(c[1], c[1]).replace('_DIA', '').replace('_H', ''))
                     for c in pivot.columns]
    return pivot.sort_index()


def load_recent_era5(conn, prox_map):
    cur = conn.cursor()
    era5_sks = list(set([prox_map[sk] for sk in NATURAL_STATIONS if sk in prox_map]))
    if not era5_sks:
        return pd.DataFrame()
    sk_ph = ','.join(['?'] * len(era5_sks))
    era5_params = ERA5_FEATURES + ERA5_EXTRA
    p_ph = ','.join(['?'] * len(era5_params))
    cur.execute("""
        SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        WHERE e.sistema_origem = 'ERA5'
        AND e.estacao_sk IN (""" + sk_ph + """)
        AND p.parametro_codigo IN (""" + p_ph + """)
        AND t.data_hora >= DATEADD(DAY, -35, GETDATE())
    """, era5_sks + era5_params)
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([(r[0], r[1], r[2], r[3]) for r in rows],
                      columns=['estacao_sk', 'data_hora', 'parametro_codigo', 'valor'])
    df.dropna(subset=['valor'], inplace=True)
    df['data_hora'] = pd.to_datetime(df['data_hora'])
    pivot = df.pivot_table(index='data_hora', columns=['estacao_sk', 'parametro_codigo'],
                           values='valor', aggfunc='first')
    pivot.columns = ['ERA5_SK{}_{}'.format(c[0], PARAM_ALIAS.get(c[1], c[1])) for c in pivot.columns]
    hourly = pivot.resample('h').mean()
    hourly.index = hourly.index + pd.Timedelta(hours=12)
    return hourly


def load_recent_ipma(conn, ipma_prox_map):
    cur = conn.cursor()
    ipma_sks = list(set([ipma_prox_map[sk] for sk in NATURAL_STATIONS if sk in ipma_prox_map]))
    if not ipma_sks:
        return pd.DataFrame()
    sk_ph = ','.join(['?'] * len(ipma_sks))
    cur.execute("""
        SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        WHERE e.sistema_origem = 'IPMA'
        AND e.estacao_sk IN (""" + sk_ph + """)
        AND p.parametro_codigo IN ('prec', 'temp', 'press')
        AND t.data_hora >= DATEADD(HOUR, -30, GETDATE())
    """, ipma_sks)
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([(r[0], r[1], r[2], r[3]) for r in rows],
                      columns=['estacao_sk', 'data_hora', 'parametro_codigo', 'valor'])
    df.dropna(subset=['valor'], inplace=True)
    df['data_hora'] = pd.to_datetime(df['data_hora'])
    pivot = df.pivot_table(index='data_hora', columns=['estacao_sk', 'parametro_codigo'],
                           values='valor', aggfunc='first')
    pivot.columns = ['IPMA_SK{}_{}'.format(c[0], c[1]) for c in pivot.columns]
    return pivot.resample('h').mean()


def build_features_for_station(sk, snirh, era5, ipma,
                                station_stats, prox_map, ipma_prox_map,
                                station_geo, feature_list):
    stats = station_stats.get(sk, {})
    if not stats:
        return None

    nivel_col = 'SK{}_NIVEL_INST'.format(sk)
    if nivel_col not in snirh.columns:
        return None

    nivel = snirh[nivel_col].dropna()
    if len(nivel) < 10:
        return None

    latest_ts = nivel.index[-1]
    latest_nivel = float(nivel.iloc[-1])

    feats = {}

    feats['station_sk'] = sk
    lat, lon = station_geo.get(sk, (0, 0))
    feats['station_lat'] = lat
    feats['station_lon'] = lon

    for stat_name in ['mean', 'std', 'p50', 'p75', 'p90', 'p95', 'p99', 'min', 'max',
                       'p005', 'p995']:
        feats['station_nivel_{}'.format(stat_name)] = stats.get(stat_name, 0)

    for lag in [1, 3, 6, 12, 24, 48, 72, 168, 336]:
        target_ts = latest_ts - pd.Timedelta(hours=lag)
        if target_ts in nivel.index:
            feats['nivel_lag_{}h'.format(lag)] = float(nivel.loc[target_ts])
        else:
            mask = nivel.index <= target_ts
            feats['nivel_lag_{}h'.format(lag)] = float(nivel[mask].iloc[-1]) if mask.any() else 0

    for delta in [1, 3, 6, 12, 24]:
        lag_col = 'nivel_lag_{}h'.format(delta)
        feats['nivel_delta_{}h'.format(delta)] = latest_nivel - feats.get(lag_col, latest_nivel)

    for w in ROLLING_WINDOWS:
        window = nivel.loc[nivel.index >= latest_ts - pd.Timedelta(hours=w)]
        if len(window) > 0:
            feats['nivel_rmean_{}h'.format(w)] = float(window.mean())
            feats['nivel_rmax_{}h'.format(w)] = float(window.max())
            feats['nivel_rmin_{}h'.format(w)] = float(window.min())
            feats['nivel_rstd_{}h'.format(w)] = float(window.std()) if len(window) > 1 else 0
            feats['nivel_rrange_{}h'.format(w)] = float(window.max() - window.min())
            feats['nivel_rcv_{}h'.format(w)] = feats['nivel_rstd_{}h'.format(w)] / (feats['nivel_rmean_{}h'.format(w)] + 1e-8)
        else:
            for suffix in ['rmean', 'rmax', 'rmin', 'rstd', 'rrange', 'rcv']:
                feats['nivel_{}_{}h'.format(suffix, w)] = 0

    w = 72
    window = nivel.loc[nivel.index >= latest_ts - pd.Timedelta(hours=w)]
    feats['nivel_rmean_{}h'.format(w)] = float(window.mean()) if len(window) > 0 else 0

    window_24 = nivel.loc[nivel.index >= latest_ts - pd.Timedelta(hours=24)]
    rmean_24 = float(window_24.mean()) if len(window_24) > 0 else 0
    window_24_lag = nivel.loc[(nivel.index >= latest_ts - pd.Timedelta(hours=48)) &
                               (nivel.index <= latest_ts - pd.Timedelta(hours=24))]
    feats['nivel_rmean_24h_lag24'] = float(window_24_lag.mean()) if len(window_24_lag) > 0 else rmean_24

    if stats.get('std', 0) > 0:
        feats['nivel_relativo'] = (latest_nivel - stats['mean']) / stats['std']
    else:
        feats['nivel_relativo'] = 0

    feats['flood_index'] = 0

    era5_sk = prox_map.get(sk)
    if era5_sk:
        era5_cols = [c for c in era5.columns if 'SK{}_'.format(era5_sk) in c]
        if era5_cols:
            era5_part = era5[era5_cols].copy()
            era5_part.columns = [c.replace('_SK{}_'.format(era5_sk), '_') for c in era5_part.columns]
            precip_col = 'ERA5_PRECIPITACAO'
            if precip_col in era5_part.columns:
                precip = era5_part[precip_col].dropna()
                for w in PRECIP_WINDOWS:
                    window = precip.loc[precip.index >= latest_ts - pd.Timedelta(hours=w)]
                    feats['ERA5_PRECIPITACAO_accum_{}h'.format(w)] = float(window.sum()) if len(window) > 0 else 0

                p24 = precip.loc[precip.index >= latest_ts - pd.Timedelta(hours=24)]
                p24_prev = precip.loc[(precip.index >= latest_ts - pd.Timedelta(hours=48)) &
                                       (precip.index <= latest_ts - pd.Timedelta(hours=24))]
                feats['ERA5_PRECIPITACAO_delta_24h'] = (float(p24.sum()) - float(p24_prev.sum())) if len(p24_prev) > 0 else 0

                for lag in [1, 3, 6]:
                    target_ts = latest_ts - pd.Timedelta(hours=lag)
                    if target_ts in precip.index:
                        feats['ERA5_PRECIPITACAO_lag_{}h'.format(lag)] = float(precip.loc[target_ts])
                    else:
                        mask = precip.index <= target_ts
                        feats['ERA5_PRECIPITACAO_lag_{}h'.format(lag)] = float(precip[mask].iloc[-1]) if mask.any() else 0

                for suffix, w in [('rmean', 6), ('rmax', 6), ('rmax', 24)]:
                    window = precip.loc[precip.index >= latest_ts - pd.Timedelta(hours=w)]
                    if suffix == 'rmean':
                        feats['ERA5_PRECIPITACAO_{}_{:d}h'.format(suffix, w)] = float(window.mean()) if len(window) > 0 else 0
                    else:
                        feats['ERA5_PRECIPITACAO_{}_{:d}h'.format(suffix, w)] = float(window.max()) if len(window) > 0 else 0

            for era5_col_base in ['ERA5_TEMP_2M', 'ERA5_SOLO_UM_L1', 'ERA5_PRESSAO_SUPERFICIE']:
                if era5_col_base in era5_part.columns:
                    series = era5_part[era5_col_base].dropna()
                    window = series.loc[series.index >= latest_ts - pd.Timedelta(hours=24)]
                    feats['{}_rmean_24h'.format(era5_col_base)] = float(window.mean()) if len(window) > 0 else 0
                    if 'SOLO_UM_L1' in era5_col_base:
                        target_ts = latest_ts - pd.Timedelta(hours=24)
                        mask = series.index <= target_ts
                        prev_val = float(series[mask].iloc[-1]) if mask.any() else float(series.iloc[-1]) if len(series) > 0 else 0
                        feats['{}_lag_24h'.format(era5_col_base)] = prev_val
                        feats['{}_delta_24h'.format(era5_col_base)] = feats['{}_rmean_24h'.format(era5_col_base)] - prev_val

            if 'ERA5_PRESSAO_SUPERFICIE' in era5_part.columns:
                pressao = era5_part['ERA5_PRESSAO_SUPERFICIE'].dropna()
                target_ts = latest_ts - pd.Timedelta(hours=6)
                mask = pressao.index <= target_ts
                prev_p = float(pressao[mask].iloc[-1]) if mask.any() else 0
                curr_p = float(pressao.iloc[-1]) if len(pressao) > 0 else 0
                feats['ERA5_PRESSAO_delta_6h'] = curr_p - prev_p

            if 'flood_index' in feats and feats.get('ERA5_PRECIPITACAO_accum_24h', 0) > 0:
                p95_precip = stats.get('p95', 1)
                p50 = stats.get('p50', 0)
                p95 = stats.get('p95', p50 + 0.01)
                feats['flood_index'] = ((latest_nivel - p50) / max(p95 - p50, 0.01))

    ipma_sk = ipma_prox_map.get(sk)
    if ipma_sk and not ipma.empty:
        ipma_cols = [c for c in ipma.columns if 'SK{}_'.format(ipma_sk) in c]
        if ipma_cols:
            ipma_part = ipma[ipma_cols].copy()
            ipma_part.columns = [c.replace('_SK{}_'.format(ipma_sk), '_') for c in ipma_part.columns]
            precip_col = 'IPMA_PRECIP_TOTAL'
            if precip_col in ipma_part.columns:
                precip = ipma_part[precip_col].dropna()
                for lag in [1, 3, 6]:
                    target_ts = latest_ts - pd.Timedelta(hours=lag)
                    mask = precip.index <= target_ts
                    feats['IPMA_PRECIP_lag_{}h'.format(lag)] = float(precip[mask].iloc[-1]) if mask.any() else 0
                for w in [6, 12, 24]:
                    window = precip.loc[precip.index >= latest_ts - pd.Timedelta(hours=w)]
                    feats['IPMA_PRECIP_accum_{}h'.format(w)] = float(window.sum()) if len(window) > 0 else 0

    for other_sk in NATURAL_STATIONS:
        if other_sk == sk:
            continue
        other_col = 'SK{}_NIVEL_INST'.format(other_sk)
        if other_col in snirh.columns:
            other_nivel = snirh[other_col].dropna()
            for lag in [3, 6]:
                target_ts = latest_ts - pd.Timedelta(hours=lag)
                mask = other_nivel.index <= target_ts
                feats['XSK{}_NIVEL_INST_lag_{}h'.format(other_sk, lag)] = float(other_nivel[mask].iloc[-1]) if mask.any() else 0

    for dam_sk in DAM_STATIONS:
        for caudal_type in ['CAUDAL_DESC', 'CAUDAL_AFLUENTE']:
            col = 'SK{}_{}'.format(dam_sk, caudal_type)
            if col in snirh.columns:
                series = snirh[col].dropna()
                for lag in [6, 12, 24]:
                    target_ts = latest_ts - pd.Timedelta(hours=lag)
                    mask = series.index <= target_ts
                    feats['DSK{}_{}_lag_{}h'.format(dam_sk, caudal_type, lag)] = float(series[mask].iloc[-1]) if mask.any() else 0

    caudal_col = 'SK233_CAUDAL_MED'
    if caudal_col in snirh.columns:
        series = snirh[caudal_col].dropna()
        for lag in [6, 12, 24]:
            target_ts = latest_ts - pd.Timedelta(hours=lag)
            mask = series.index <= target_ts
            feats['SK233_CAUDAL_lag_{}h'.format(lag)] = float(series[mask].iloc[-1]) if mask.any() else 0
        if 'SK233_CAUDAL_lag_6h' in feats:
            feats['SK233_CAUDAL_delta_6h'] = feats.get('SK233_CAUDAL_lag_6h', 0) - feats.get('SK233_CAUDAL_lag_12h', 0)

    desc_sum = 0
    for dam_sk in DAM_STATIONS:
        col = 'SK{}_CAUDAL_DESC'.format(dam_sk)
        if col in snirh.columns:
            series = snirh[col].dropna()
            if len(series) > 0:
                desc_sum += float(series.iloc[-1])
    feats['caudal_total_desc'] = desc_sum

    feats['hour_sin'] = np.sin(2 * np.pi * latest_ts.hour / 24)
    feats['hour_cos'] = np.cos(2 * np.pi * latest_ts.hour / 24)
    feats['month_sin'] = np.sin(2 * np.pi * latest_ts.month / 12)
    feats['month_cos'] = np.cos(2 * np.pi * latest_ts.month / 12)
    feats['day_of_week'] = latest_ts.dayofweek

    row = pd.DataFrame({k: [v] for k, v in feats.items()})
    for col in feature_list:
        if col not in row.columns:
            row[col] = 0
    row = row[feature_list]
    row = row.fillna(0).replace([np.inf, -np.inf], 0)

    return row, latest_nivel, latest_ts


def classify_flood_risk(nivel_atual, predictions, stats, precip_accum_24h=0,
                        taxa_subida_6h=0, solo_sat=0, fc_precip_tomorrow=0):
    score = 0

    if nivel_atual > stats.get('p99', 999):
        score += 5
    elif nivel_atual > stats.get('p95', 999):
        score += 4
    elif nivel_atual > stats.get('p90', 999):
        score += 3
    elif nivel_atual > stats.get('p75', 999):
        score += 1

    if taxa_subida_6h > 0.20:
        score += 4
    elif taxa_subida_6h > 0.10:
        score += 3
    elif taxa_subida_6h > 0.05:
        score += 2
    elif taxa_subida_6h > 0.02:
        score += 1

    if precip_accum_24h > 30:
        score += 3
    elif precip_accum_24h > 15:
        score += 2
    elif precip_accum_24h > 5:
        score += 1

    if fc_precip_tomorrow and fc_precip_tomorrow > 70:
        score += 3
    elif fc_precip_tomorrow and fc_precip_tomorrow > 40:
        score += 2

    if solo_sat > 0.95:
        score += 2
    elif solo_sat > 0.80:
        score += 1

    max_score = 18.0
    pct = min(score / max_score, 1.0)

    if score >= 10:
        nivel_risco, cat_risco = 5, 'Muito Alto'
    elif score >= 7:
        nivel_risco, cat_risco = 4, 'Alto'
    elif score >= 4:
        nivel_risco, cat_risco = 3, 'Moderado'
    elif score >= 2:
        nivel_risco, cat_risco = 2, 'Baixo'
    else:
        nivel_risco, cat_risco = 1, 'Muito Baixo'

    if pct >= 0.80:
        nivel_alerta = 'CRITICO'
    elif pct >= 0.55:
        nivel_alerta = 'ALTO'
    elif pct >= 0.30:
        nivel_alerta = 'MODERADO'
    else:
        nivel_alerta = 'BAIXO'

    return nivel_risco, cat_risco, nivel_alerta, pct


def build_lstm_sequence(sk, snirh, era5, prox_map):
    nivel_col = 'SK{}_NIVEL_INST'.format(sk)
    if nivel_col not in snirh.columns:
        return None
    nivel = snirh[nivel_col].dropna()
    if len(nivel) < LSTM_LOOKBACK:
        return None

    idx = nivel.index
    df = pd.DataFrame(index=idx)
    df['nivel'] = nivel.reindex(idx)

    df['nivel_lag_1h'] = df['nivel'].shift(1)
    df['nivel_lag_3h'] = df['nivel'].shift(3)
    df['nivel_lag_6h'] = df['nivel'].shift(6)
    df['nivel_delta_1h'] = df['nivel'] - df['nivel'].shift(1)
    df['nivel_delta_3h'] = df['nivel'] - df['nivel'].shift(3)
    df['nivel_delta_6h'] = df['nivel'] - df['nivel'].shift(6)
    df['nivel_rmean_6h'] = df['nivel'].rolling(6, min_periods=1).mean()
    df['nivel_rmean_24h'] = df['nivel'].rolling(24, min_periods=1).mean()
    df['nivel_rstd_24h'] = df['nivel'].rolling(24, min_periods=1).std()

    era5_sk = prox_map.get(sk)
    if era5_sk:
        era5_tp = [c for c in era5.columns if 'SK{}_'.format(era5_sk) in c and 'PRECIPITACAO' in c.upper()]
        if era5_tp:
            precip = era5[era5_tp[0]].reindex(idx).ffill().fillna(0)
            df['era5_precip'] = precip
            df['era5_precip_accum_6h'] = precip.rolling(6, min_periods=1).sum()
            df['era5_precip_accum_24h'] = precip.rolling(24, min_periods=1).sum()

        era5_temp = [c for c in era5.columns if 'SK{}_'.format(era5_sk) in c and 'TEMP_2M' in c.upper()]
        if era5_temp:
            df['era5_temp'] = era5[era5_temp[0]].reindex(idx).ffill().fillna(0)

        era5_soil = [c for c in era5.columns if 'SK{}_'.format(era5_sk) in c and 'SOLO_UM_L1' in c.upper()]
        if era5_soil:
            df['era5_soil_l1'] = era5[era5_soil[0]].reindex(idx).ffill().fillna(0)

        era5_press = [c for c in era5.columns if 'SK{}_'.format(era5_sk) in c and 'PRESSAO' in c.upper()]
        if era5_press:
            df['era5_pressure'] = era5[era5_press[0]].reindex(idx).ffill().fillna(0)

    df['hour_sin'] = np.sin(2 * np.pi * idx.hour / 24)
    df['hour_cos'] = np.cos(2 * np.pi * idx.hour / 24)
    df['month_sin'] = np.sin(2 * np.pi * idx.month / 12)
    df['month_cos'] = np.cos(2 * np.pi * idx.month / 12)

    for col in LSTM_FEATURES:
        if col not in df.columns:
            df[col] = 0.0

    df = df[LSTM_FEATURES].ffill().fillna(0)
    return df


def predict_lstm(conn, snirh, era5, prox_map, dry_run=False):
    if not HAS_TF:
        print('[LSTM] TensorFlow not available, skipping')
        return
    if dry_run:
        return

    lstm_dir = os.path.join(MODELS_DIR, 'lstm')
    if not os.path.exists(lstm_dir):
        print('[LSTM] No LSTM models directory')
        return

    lstm_results = []
    for horizon in LSTM_HORIZONS:
        model_path = os.path.join(lstm_dir, 'lstm_flood_h{}.keras'.format(horizon))
        scaler_path = os.path.join(lstm_dir, 'scaler_h{}.pkl'.format(horizon))
        config_path = os.path.join(lstm_dir, 'config_h{}.json'.format(horizon))

        if not os.path.exists(model_path):
            print('  LSTM h={}: model not found'.format(horizon))
            continue

        model = keras.models.load_model(model_path)
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        with open(config_path, 'r') as f:
            config = json.load(f)

        threshold = config.get('threshold', 0.5)
        print('  LSTM h={}: threshold={:.4f}'.format(horizon, threshold))

        for sk in NATURAL_STATIONS:
            seq = build_lstm_sequence(sk, snirh, era5, prox_map)
            if seq is None:
                continue

            if len(seq) < LSTM_LOOKBACK:
                continue

            window = seq.iloc[-LSTM_LOOKBACK:].values
            window_flat = window.reshape(-1, window.shape[-1])
            window_scaled = scaler.transform(window_flat).reshape(1, LSTM_LOOKBACK, len(LSTM_FEATURES))

            prob = float(model.predict(window_scaled, verbose=0).flatten()[0])
            alert = int(prob >= threshold)

            latest_ts = snirh['SK{}_NIVEL_INST'.format(sk)].dropna().index[-1]

            lstm_results.append({
                'estacao_sk': sk,
                'horizonte_h': horizon,
                'ts_previsao': latest_ts,
                'prob_cheia': prob,
                'flood_alert': alert,
                'threshold_used': threshold,
                'model_version': MODEL_VERSION,
            })

            label = 'FLOOD' if alert else 'OK'
            print('    SK={} h={}: prob={:.4f} [{}]'.format(sk, horizon, prob, label))

    if lstm_results:
        cur = conn.cursor()
        cur.execute("IF OBJECT_ID('ml.lstm_predictions') IS NOT NULL DROP TABLE ml.lstm_predictions")
        cur.execute("""
            CREATE TABLE ml.lstm_predictions (
                id INT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
                estacao_sk INT NOT NULL,
                ts_previsao DATETIME2 NOT NULL,
                horizonte_h INT NOT NULL,
                prob_cheia FLOAT NOT NULL,
                flood_alert BIT NOT NULL,
                threshold_used FLOAT NOT NULL,
                model_version NVARCHAR(20),
                created_at DATETIME DEFAULT GETDATE()
            )
        """)
        cur.execute("CREATE CLUSTERED INDEX IX_lstm_pred ON ml.lstm_predictions (estacao_sk, horizonte_h, ts_previsao)")

        for r in lstm_results:
            cur.execute("""
                INSERT INTO ml.lstm_predictions
                (estacao_sk, ts_previsao, horizonte_h, prob_cheia, flood_alert, threshold_used, model_version)
                VALUES (?,?,?,?,?,?,?)
            """, r['estacao_sk'], r['ts_previsao'], r['horizonte_h'],
                   r['prob_cheia'], r['flood_alert'], r['threshold_used'], r['model_version'])

        conn.commit()
        print('  LSTM predictions saved: {} rows'.format(len(lstm_results)))


def predict_all(conn, feature_list, station_stats, prox_map, ipma_prox_map,
                station_geo, snirh, era5, ipma, dry_run=False):
    print('[PREDICT] Running predictions...')
    predictions = []
    risk_rows = []

    for sk in NATURAL_STATIONS:
        result = build_features_for_station(
            sk, snirh, era5, ipma,
            station_stats, prox_map, ipma_prox_map,
            station_geo, feature_list)
        if result is None:
            print('  SK={}: no data, skipping'.format(sk))
            continue

        feat_row, nivel_atual, latest_ts = result
        stats = station_stats[sk]

        taxa_1h = feat_row.get('nivel_delta_1h', pd.Series([0])).iloc[0]
        taxa_6h = feat_row.get('nivel_delta_6h', pd.Series([0])).iloc[0] / 6 if abs(feat_row.get('nivel_delta_6h', pd.Series([0])).iloc[0]) > 0 else 0
        precip_24h = feat_row.get('ERA5_PRECIPITACAO_accum_24h', pd.Series([0])).iloc[0]
        solo_sat = feat_row.get('ERA5_SOLO_UM_L1_rmean_24h', pd.Series([0])).iloc[0]
        fc_prob_tomorrow = 0

        station_preds = {}
        for horizon in FORECAST_HORIZONS:
            global_model_path = os.path.join(MODELS_DIR, 'models',
                                              'global_NIVEL_INST_h{}.lgb'.format(horizon))
            local_model_path = os.path.join(MODELS_DIR, 'models',
                                             'local_SK{}_NIVEL_INST_h{}.lgb'.format(sk, horizon))
            if not os.path.exists(global_model_path):
                continue

            global_model = lgb.Booster(model_file=global_model_path)
            pred_global = float(global_model.predict(feat_row)[0])

            pred_local = 0
            if os.path.exists(local_model_path):
                local_model = lgb.Booster(model_file=local_model_path)
                pred_local = float(local_model.predict(feat_row)[0])

            pred_final = pred_global + pred_local
            pred_final = max(pred_final, stats.get('min', 0))
            station_preds[horizon] = pred_final

            predictions.append({
                'estacao_sk': sk,
                'target_parametro': 'NIVEL_INST',
                'horizon_hours': horizon,
                'predicted_value': pred_final,
                'actual_value': None,
                'prediction_time': datetime.now(),
                'target_time': latest_ts + timedelta(hours=horizon),
                'modelo_versao': MODEL_VERSION,
            })

            print('  SK={} h={:2d}: pred={:.3f}m (global={:.3f} + local={:.3f})'.format(
                sk, horizon, pred_final, pred_global, pred_local))

        if station_preds:
            nivel_risco, cat_risco, nivel_alerta, risco_pct = classify_flood_risk(
                nivel_atual, station_preds, stats,
                precip_accum_24h=precip_24h,
                taxa_subida_6h=taxa_6h,
                solo_sat=solo_sat,
                fc_precip_tomorrow=fc_prob_tomorrow)

            risk_rows.append({
                'estacao_sk': sk,
                'nivel_inst_atual': nivel_atual,
                'nivel_inst_pred_1h': station_preds.get(1),
                'nivel_inst_pred_3h': station_preds.get(3),
                'nivel_inst_pred_6h': station_preds.get(6),
                'nivel_inst_pred_12h': station_preds.get(12),
                'nivel_inst_pred_24h': station_preds.get(24),
                'taxa_subida_1h': taxa_1h,
                'taxa_subida_6h': taxa_6h,
                'precip_accum_24h': precip_24h,
                'solo_saturacao_pct': solo_sat,
                'fc_precip_prob_tomorrow': fc_prob_tomorrow,
                'nivel_risco': nivel_risco,
                'categoria_risco': cat_risco,
                'modelo_tipo': 'GLOBAL_HYBRID',
                'estacao_nome': '',
                'nivel_alerta': nivel_alerta,
                'risco_percentil': risco_pct,
            })

            print('  SK={} RISCO: {} ({}) alerta={} pct={:.2f} nivel={:.3f}m'.format(
                sk, nivel_risco, cat_risco, nivel_alerta, risco_pct, nivel_atual))

    return predictions, risk_rows


def save_predictions(conn, predictions, risk_rows, dry_run=False):
    if dry_run:
        print('[SAVE] Dry run - not saving')
        return

    cur = conn.cursor()
    print('[SAVE] Writing {} predictions and {} risk rows...'.format(
        len(predictions), len(risk_rows)))

    for p in predictions:
        cur.execute("""
            INSERT INTO ml.forecast_predictions
            (estacao_sk, target_parametro, horizon_hours, predicted_value,
             actual_value, prediction_time, target_time, modelo_versao)
            VALUES (?,?,?,?,?,?,?,?)
        """, p.get('estacao_sk'), p.get('target_parametro'),
           p.get('horizon_hours'), p.get('predicted_value'),
           p.get('actual_value'), p.get('prediction_time'),
           p.get('target_time'), p.get('modelo_versao'))

    cur.execute("IF OBJECT_ID('ml.flood_risk_current') IS NOT NULL DROP TABLE ml.flood_risk_current")
    cur.execute("""
        CREATE TABLE ml.flood_risk_current (
            risk_id INT IDENTITY(1,1),
            estacao_sk INT NOT NULL,
            estacao_nome NVARCHAR(100),
            cota_albuf_atual FLOAT, cota_ultima_h_atual FLOAT,
            cota_albuf_pred_1h FLOAT, cota_albuf_pred_6h FLOAT,
            cota_albuf_pred_12h FLOAT, cota_albuf_pred_24h FLOAT,
            cota_ultima_h_pred_1h FLOAT, cota_ultima_h_pred_6h FLOAT,
            cota_ultima_h_pred_12h FLOAT, cota_ultima_h_pred_24h FLOAT,
            precip_ipma_1h FLOAT, precip_ipma_24h FLOAT,
            temp_ipma_atual FLOAT, humidade_ipma_atual FLOAT,
            vento_ipma_atual FLOAT, pressao_ipma_atual FLOAT,
            nivel_risco INT, categoria_risco NVARCHAR(20),
            nivel_inst_atual FLOAT,
            nivel_inst_pred_1h FLOAT, nivel_inst_pred_3h FLOAT,
            nivel_inst_pred_6h FLOAT, nivel_inst_pred_12h FLOAT,
            nivel_inst_pred_24h FLOAT,
            taxa_subida_1h FLOAT, taxa_subida_6h FLOAT,
            precip_accum_24h FLOAT, solo_saturacao_pct FLOAT,
            modelo_tipo VARCHAR(20) DEFAULT 'GLOBAL_HYBRID',
            nivel_alerta NVARCHAR(10) NULL,
            risco_percentil FLOAT NULL,
            data_atualizacao DATETIME DEFAULT GETDATE()
        )
    """)
    cur.execute("CREATE UNIQUE CLUSTERED INDEX IX_risk_current ON ml.flood_risk_current (estacao_sk)")

    for r in risk_rows:
        sk = r['estacao_sk']
        cur.execute("SELECT estacao_nome FROM gold.dim_estacao WHERE estacao_sk = ?", sk)
        name_row = cur.fetchone()
        r['estacao_nome'] = name_row[0] if name_row else ''

        cur.execute("""
            INSERT INTO ml.flood_risk_current
            (estacao_sk, estacao_nome, nivel_risco, categoria_risco,
             nivel_inst_atual, nivel_inst_pred_1h, nivel_inst_pred_3h,
             nivel_inst_pred_6h, nivel_inst_pred_12h, nivel_inst_pred_24h,
             taxa_subida_1h, taxa_subida_6h, precip_accum_24h,
             solo_saturacao_pct, modelo_tipo, nivel_alerta, risco_percentil)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, int(sk), r['estacao_nome'], int(r['nivel_risco']), r['categoria_risco'],
           float(r['nivel_inst_atual']), float(r.get('nivel_inst_pred_1h') or 0),
           float(r.get('nivel_inst_pred_3h') or 0), float(r.get('nivel_inst_pred_6h') or 0),
           float(r.get('nivel_inst_pred_12h') or 0), float(r.get('nivel_inst_pred_24h') or 0),
           float(r.get('taxa_subida_1h') or 0), float(r.get('taxa_subida_6h') or 0),
           float(r.get('precip_accum_24h') or 0), float(r.get('solo_saturacao_pct') or 0),
           r.get('modelo_tipo', 'GLOBAL_HYBRID'),
           r.get('nivel_alerta', 'BAIXO'),
           float(r.get('risco_percentil') or 0))

    print('  Predictions: {} rows'.format(len(predictions)))
    print('  Risk current: {} rows'.format(len(risk_rows)))


def main():
    start = datetime.now()
    print('=' * 80)
    print('  PREDICT NOW {} — STARTING'.format(MODEL_VERSION))
    print('  Time: {}'.format(start))
    print('=' * 80)

    dry_run = '--dry-run' in sys.argv

    conn = get_conn()
    try:
        feature_list, station_stats = load_config()
        prox_map, ipma_prox_map, station_geo = load_spatial_maps(conn)

        print('[DATA] Loading recent data...')
        snirh = load_recent_snirh(conn)
        print('  SNIRH: {} rows'.format(len(snirh)))
        era5 = load_recent_era5(conn, prox_map)
        print('  ERA5: {} rows'.format(len(era5)))
        ipma = load_recent_ipma(conn, ipma_prox_map)
        print('  IPMA obs: {} rows'.format(len(ipma)))

        predictions, risk_rows = predict_all(
            conn, feature_list, station_stats,
            prox_map, ipma_prox_map, station_geo,
            snirh, era5, ipma, dry_run)

        save_predictions(conn, predictions, risk_rows, dry_run)

        print('[LSTM] Running LSTM flood predictions...')
        predict_lstm(conn, snirh, era5, prox_map, dry_run)

        elapsed = datetime.now() - start
        print()
        print('  Total time: {}'.format(elapsed))

    except Exception as e:
        print('ERROR: {}'.format(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
