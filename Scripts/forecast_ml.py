import os
import sys
import json
import pyodbc
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import lightgbm as lgb
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
import warnings
warnings.filterwarnings('ignore')

from preflood_config import DB_NAME, get_conn
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
MODELS_DIR = os.path.join(PROJECT_DIR, 'Models')

NATURAL_STATIONS = [229, 232, 233, 234]
DAM_STATIONS = [223, 224, 225, 226, 228, 230, 235]
ALL_SNIRH_STATIONS = NATURAL_STATIONS + DAM_STATIONS
SNIRH_TARGETS = ['1843']
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
LAG_HOURS = [1, 3, 6, 12, 24]
PRECIP_WINDOWS = [6, 12, 24, 48, 72, 168]
ROLLING_WINDOWS = [3, 6, 12, 24]
MODEL_VERSION = 'v5.0'

LGB_GLOBAL_PARAMS = {
    'objective': 'regression',
    'metric': ['mae', 'rmse'],
    'num_leaves': 127,
    'learning_rate': 0.05,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 5,
    'min_child_samples': 30,
    'lambda_l1': 0.1,
    'lambda_l2': 0.1,
    'seed': 42,
    'verbose': -1,
}

LGB_LOCAL_PARAMS = {
    'objective': 'regression',
    'metric': 'mae',
    'num_leaves': 15,
    'learning_rate': 0.01,
    'min_child_samples': 10,
    'verbose': -1,
}


def ensure_models_dir():
    for sub in ['models', 'scalers', 'features']:
        os.makedirs(os.path.join(MODELS_DIR, sub), exist_ok=True)


def model_global_path(horizon):
    return os.path.join(MODELS_DIR, 'models', 'global_NIVEL_INST_h{}.lgb'.format(horizon))


def model_local_path(sk, horizon):
    return os.path.join(MODELS_DIR, 'models', 'local_SK{}_NIVEL_INST_h{}.lgb'.format(sk, horizon))


def scaler_path():
    return os.path.join(MODELS_DIR, 'scalers', 'global_scaler.pkl')


def features_path():
    return os.path.join(MODELS_DIR, 'features', 'feature_list.pkl')


def station_stats_path():
    return os.path.join(MODELS_DIR, 'features', 'station_stats.pkl')


def load_and_merge(conn):
    print('[DATA] Loading and merging all sources...')
    cur = conn.cursor()

    snirh_codes = ['1843', '1845', '1850', '3212219030', '354895424']
    ph = ','.join(['?'] * len(snirh_codes))
    sks = ALL_SNIRH_STATIONS
    sk_ph = ','.join(['?'] * len(sks))
    cur.execute("""
        SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        WHERE e.sistema_origem = 'SNIRH'
        AND p.parametro_codigo IN (""" + ph + """)
        AND e.estacao_sk IN (""" + sk_ph + """)
    """, snirh_codes + sks)
    snirh_rows = cur.fetchall()
    print('  SNIRH raw rows: {:,}'.format(len(snirh_rows)))
    snirh = pd.DataFrame(
        [(r[0], r[1], r[2], r[3]) for r in snirh_rows],
        columns=['estacao_sk', 'data_hora', 'parametro_codigo', 'valor'])
    snirh.dropna(subset=['valor'], inplace=True)
    snirh['data_hora'] = pd.to_datetime(snirh['data_hora'])
    snirh_pivot = snirh.pivot_table(
        index='data_hora', columns=['estacao_sk', 'parametro_codigo'],
        values='valor', aggfunc='first')
    snirh_pivot.columns = ['SNIRH_SK{}_{}'.format(c[0], PARAM_ALIAS.get(c[1], c[1]).replace('_DIA', '').replace('_H', ''))
                           for c in snirh_pivot.columns]
    snirh_pivot = snirh_pivot.sort_index()

    cur.execute("SELECT source_station_sk, target_station_sk, distance_meters, is_nearest "
                "FROM ctl.map_spatial_proximity WHERE is_nearest = 1")
    prox_rows = cur.fetchall()
    prox_map = {}
    for r in prox_rows:
        prox_map[r[0]] = r[1]

    era5_all = ERA5_FEATURES + ERA5_EXTRA
    era5_ph = ','.join(['?'] * len(era5_all))
    era5_target_sks = [prox_map[sk] for sk in NATURAL_STATIONS if sk in prox_map]
    era5_sk_ph = ','.join(['?'] * len(era5_target_sks))
    if era5_target_sks:
        cur.execute("""
            SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
            FROM gold.fact_medicao f
            JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
            JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
            JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
            WHERE e.sistema_origem = 'ERA5'
            AND p.parametro_codigo IN (""" + era5_ph + """)
            AND e.estacao_sk IN (""" + era5_sk_ph + """)
        """, era5_all + era5_target_sks)
        era5_rows = cur.fetchall()
        print('  ERA5 raw rows: {:,}'.format(len(era5_rows)))
        era5 = pd.DataFrame(
            [(r[0], r[1], r[2], r[3]) for r in era5_rows],
            columns=['estacao_sk', 'data_hora', 'parametro_codigo', 'valor'])
        era5.dropna(subset=['valor'], inplace=True)
        era5['data_hora'] = pd.to_datetime(era5['data_hora'])
        era5_pivot = era5.pivot_table(
            index='data_hora', columns=['estacao_sk', 'parametro_codigo'],
            values='valor', aggfunc='first')
        era5_pivot.columns = ['ERA5_SK{}_{}'.format(c[0], PARAM_ALIAS.get(c[1], c[1])) for c in era5_pivot.columns]
        era5_pivot = era5_pivot.sort_index()
        era5_hourly = era5_pivot.resample('h').mean()
        era5_hourly.index = era5_hourly.index + pd.Timedelta(hours=12)
        reverse_prox = {v: k for k, v in prox_map.items()}
    else:
        era5_hourly = pd.DataFrame()
        reverse_prox = {}

    ipma_codes = ['prec', 'temp', 'press']
    ipma_ph = ','.join(['?'] * len(ipma_codes))
    ipma_prox_map = {}
    cur.execute("""
        SELECT sp.source_station_sk, sp.target_station_sk
        FROM ctl.map_spatial_proximity sp
        JOIN gold.dim_estacao e ON sp.target_station_sk = e.estacao_sk
        WHERE sp.is_nearest = 1 AND e.sistema_origem = 'IPMA'
    """)
    for r in cur.fetchall():
        ipma_prox_map[r[0]] = r[1]
    ipma_target_sks = list(set([ipma_prox_map[sk] for sk in NATURAL_STATIONS if sk in ipma_prox_map]))
    ipma_sk_ph = ','.join(['?'] * len(ipma_target_sks))
    ipma_hourly = pd.DataFrame()
    if ipma_target_sks:
        cur.execute("""
            SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
            FROM gold.fact_medicao f
            JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
            JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
            JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
            WHERE e.sistema_origem = 'IPMA'
            AND p.parametro_codigo IN (""" + ipma_ph + """)
            AND e.estacao_sk IN (""" + ipma_sk_ph + """)
        """, ipma_codes + ipma_target_sks)
        ipma_rows = cur.fetchall()
        print('  IPMA obs raw rows: {:,}'.format(len(ipma_rows)))
        if ipma_rows:
            ipma = pd.DataFrame(
                [(r[0], r[1], r[2], r[3]) for r in ipma_rows],
                columns=['estacao_sk', 'data_hora', 'parametro_codigo', 'valor'])
            ipma.dropna(subset=['valor'], inplace=True)
            ipma['data_hora'] = pd.to_datetime(ipma['data_hora'])
            ipma_pivot = ipma.pivot_table(
                index='data_hora', columns=['estacao_sk', 'parametro_codigo'],
                values='valor', aggfunc='first')
            ipma_pivot.columns = ['IPMA_SK{}_{}'.format(c[0], c[1]) for c in ipma_pivot.columns]
            ipma_hourly = ipma_pivot.resample('h').mean()
    ipma_reverse = {v: k for k, v in ipma_prox_map.items()}

    print('[DATA] Building per-station merged frames...')
    station_frames = {}
    for sk in NATURAL_STATIONS:
        parts = [snirh_pivot.filter(like='SNIRH_SK{}_'.format(sk))]

        era5_sk = prox_map.get(sk)
        if era5_sk and era5_sk in reverse_prox:
            era5_cols = [c for c in era5_hourly.columns if 'SK{}_'.format(era5_sk) in c]
            if era5_cols:
                era5_part = era5_hourly[era5_cols].copy()
                era5_part.columns = [c.replace('_SK{}_'.format(era5_sk), '_') for c in era5_part.columns]
                parts.append(era5_part)

        ipma_sk = ipma_prox_map.get(sk)
        if ipma_sk and not ipma_hourly.empty:
            ipma_cols = [c for c in ipma_hourly.columns if 'SK{}_'.format(ipma_sk) in c]
            if ipma_cols:
                ipma_part = ipma_hourly[ipma_cols].copy()
                ipma_part.columns = [c.replace('_SK{}_'.format(ipma_sk), '_') for c in ipma_part.columns]
                parts.append(ipma_part)

        for other_sk in NATURAL_STATIONS:
            if other_sk == sk:
                continue
            other_cols = [c for c in snirh_pivot.columns
                          if c.startswith('SNIRH_SK{}_NIVEL_INST'.format(other_sk))]
            if other_cols:
                other_part = snirh_pivot[other_cols].copy()
                other_part.columns = ['XSK{}_NIVEL_INST'.format(other_sk)]
                parts.append(other_part)

        for dam_sk in DAM_STATIONS:
            for caudal_type in ['CAUDAL_DESC', 'CAUDAL_AFLUENTE', 'CAUDAL_EFL']:
                dam_cols = [c for c in snirh_pivot.columns
                            if c.startswith('SNIRH_SK{}_{}'.format(dam_sk, caudal_type))]
                if dam_cols:
                    dam_part = snirh_pivot[dam_cols].copy()
                    dam_part.columns = ['DSK{}_{}'.format(dam_sk, caudal_type)]
                    parts.append(dam_part)

        merged = pd.concat(parts, axis=1, join='outer').sort_index()
        merged['station_sk'] = sk
        station_frames[sk] = merged

    print('[DATA] Loaded {} stations'.format(len(station_frames)))
    for sk, df in station_frames.items():
        n_rows = len(df)
        n_cols = len(df.columns)
        dt_range = '{} to {}'.format(df.index.min(), df.index.max()) if n_rows > 0 else 'empty'
        print('  SK={}: {:,} rows, {} cols | {}'.format(sk, n_rows, n_cols, dt_range))

    return station_frames, prox_map


def compute_station_stats(station_frames, until_idx=None):
    stats = {}
    for sk in NATURAL_STATIONS:
        df = station_frames[sk]
        nivel_col = 'SNIRH_SK{}_NIVEL_INST'.format(sk)
        if nivel_col not in df.columns:
            continue
        s = df[nivel_col].dropna()
        if until_idx is not None:
            s = s[s.index <= until_idx]
        if len(s) < 100:
            continue
        stats[sk] = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'p50': float(s.quantile(0.50)),
            'p75': float(s.quantile(0.75)),
            'p90': float(s.quantile(0.90)),
            'p95': float(s.quantile(0.95)),
            'p99': float(s.quantile(0.99)),
            'p005': float(s.quantile(0.005)),
            'p995': float(s.quantile(0.995)),
            'min': float(s.min()),
            'max': float(s.max()),
        }
    return stats


def engineer_features(station_frames, station_stats):
    print('[FEATURES] Engineering features...')
    all_frames = []

    for sk in NATURAL_STATIONS:
        df = station_frames[sk].copy()
        nivel_col = 'SNIRH_SK{}_NIVEL_INST'.format(sk)

        if nivel_col not in df.columns:
            continue

        stats = station_stats.get(sk, {})
        df['station_sk'] = sk

        cur = get_conn().cursor()
        cur.execute('SELECT latitude, longitude FROM gold.dim_estacao WHERE estacao_sk = ?', sk)
        row = cur.fetchone()
        if row:
            df['station_lat'] = row[0]
            df['station_lon'] = row[1]

        nivel = df[nivel_col]
        for lag in [1, 3, 6, 12, 24, 48, 72, 168, 336]:
            df['nivel_lag_{}h'.format(lag)] = nivel.shift(lag)

        for delta in [1, 3, 6, 12, 24]:
            df['nivel_delta_{}h'.format(delta)] = nivel - nivel.shift(delta)

        for w in ROLLING_WINDOWS:
            r = nivel.rolling(window=w, min_periods=1)
            df['nivel_rmean_{}h'.format(w)] = r.mean()
            df['nivel_rmax_{}h'.format(w)] = r.max()
            df['nivel_rmin_{}h'.format(w)] = r.min()
            df['nivel_rstd_{}h'.format(w)] = r.std()
            df['nivel_rrange_{}h'.format(w)] = r.max() - r.min()
            df['nivel_rcv_{}h'.format(w)] = r.std() / (r.mean() + 1e-8)

        for w in [72]:
            df['nivel_rmean_{}h'.format(w)] = nivel.rolling(window=w, min_periods=1).mean()

        df['nivel_rmean_24h_lag24'] = nivel.rolling(24, min_periods=1).mean().shift(24)

        for era5_prefix in ['ERA5_PRECIPITACAO', 'ERA5_SOLO_UM_L1']:
            col = era5_prefix
            if col in df.columns:
                for w in PRECIP_WINDOWS:
                    df['{}_accum_{}h'.format(col, w)] = df[col].rolling(window=w, min_periods=1).sum()

        precip_col = 'ERA5_PRECIPITACAO'
        if precip_col in df.columns:
            df['ERA5_PRECIP_delta_24h'] = df[precip_col] - df[precip_col].shift(24)
            for lag in [1, 3, 6]:
                df['ERA5_PRECIP_lag_{}h'.format(lag)] = df[precip_col].shift(lag)
            df['ERA5_PRECIP_rmean_6h'] = df[precip_col].rolling(6, min_periods=1).mean()
            df['ERA5_PRECIP_rmax_6h'] = df[precip_col].rolling(6, min_periods=1).max()
            df['ERA5_PRECIP_rmax_24h'] = df[precip_col].rolling(24, min_periods=1).max()

        for era5_col in ['ERA5_TEMP_2M', 'ERA5_SOLO_UM_L1', 'ERA5_PRESSAO_SUPERFICIE']:
            if era5_col in df.columns:
                df['{}_rmean_24h'.format(era5_col)] = df[era5_col].rolling(24, min_periods=1).mean()
                if era5_col in ['ERA5_SOLO_UM_L1']:
                    df['{}_lag_24h'.format(era5_col)] = df[era5_col].shift(24)
                    df['{}_delta_24h'.format(era5_col)] = df[era5_col] - df[era5_col].shift(24)

        if 'ERA5_PRESSAO_SUPERFICIE' in df.columns:
            df['ERA5_PRESSAO_delta_6h'] = df['ERA5_PRESSAO_SUPERFICIE'] - df['ERA5_PRESSAO_SUPERFICIE'].shift(6)

        ipma_precip = 'IPMA_PRECIP_TOTAL'
        if ipma_precip in df.columns:
            for lag in [1, 3, 6]:
                df['IPMA_PRECIP_lag_{}h'.format(lag)] = df[ipma_precip].shift(lag)
            for w in [6, 12, 24]:
                df['IPMA_PRECIP_accum_{}h'.format(w)] = df[ipma_precip].rolling(w, min_periods=1).sum()

        for dam_sk in DAM_STATIONS:
            for caudal_type in ['CAUDAL_DESC', 'CAUDAL_AFLUENTE']:
                col = 'DSK{}_{}'.format(dam_sk, caudal_type)
                if col in df.columns:
                    for lag in [6, 12, 24]:
                        df['{}_lag_{}h'.format(col, lag)] = df[col].shift(lag)

        for other_sk in NATURAL_STATIONS:
            if other_sk == sk:
                continue
            col = 'XSK{}_NIVEL_INST'.format(other_sk)
            if col in df.columns:
                for lag in [3, 6]:
                    df['{}_lag_{}h'.format(col, lag)] = df[col].shift(lag)

        caudal_col = 'SNIRH_SK233_CAUDAL_MED'
        if caudal_col in df.columns:
            for lag in [6, 12, 24]:
                df['SK233_CAUDAL_lag_{}h'.format(lag)] = df[caudal_col].shift(lag)
            df['SK233_CAUDAL_delta_6h'] = df[caudal_col] - df[caudal_col].shift(6)

        desc_cols = [c for c in df.columns if c.startswith('DSK') and 'CAUDAL_DESC' in c and '_lag_' not in c]
        if desc_cols:
            df['caudal_total_desc'] = df[desc_cols].sum(axis=1, min_count=1)

        df['hour_sin'] = np.sin(2 * np.pi * df.index.hour / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df.index.hour / 24)
        df['month_sin'] = np.sin(2 * np.pi * df.index.month / 12)
        df['month_cos'] = np.cos(2 * np.pi * df.index.month / 12)
        df['day_of_week'] = df.index.dayofweek

        all_frames.append(df)

    combined = pd.concat(all_frames, axis=0).sort_index()
    combined['station_sk'] = combined['station_sk'].astype(int)

    target_col_candidates = ['SNIRH_SK{}_NIVEL_INST'.format(sk) for sk in NATURAL_STATIONS]
    feature_cols = ['station_sk']
    feature_cols += [c for c in combined.columns
                     if c not in target_col_candidates
                     and c != 'station_sk'
                     and c != 'nivel_atual'
                     and not c.startswith('SNIRH_SK')
                     and not c.startswith('XSK')
                     and not c.startswith('DSK')
                     and not c.startswith('IPMA_SK')
                     and not c.startswith('ERA5_SK')
                     and not c.startswith('FC_SK')]

    for other_sk in NATURAL_STATIONS:
        base = 'XSK{}_NIVEL_INST'.format(other_sk)
        for lag in [3, 6]:
            col = '{}_lag_{}h'.format(base, lag)
            if col in combined.columns:
                feature_cols.append(col)

    for dam_sk in DAM_STATIONS:
        for caudal_type in ['CAUDAL_DESC', 'CAUDAL_AFLUENTE']:
            base = 'DSK{}_{}'.format(dam_sk, caudal_type)
            for lag in [6, 12, 24]:
                col = '{}_lag_{}h'.format(base, lag)
                if col in combined.columns:
                    feature_cols.append(col)

    for col in combined.columns:
        if col in target_col_candidates or col == 'nivel_atual':
            continue
        if col in feature_cols:
            continue
        if col.startswith('nivel_') or col.startswith('ERA5_') or col.startswith('IPMA_'):
            feature_cols.append(col)
        elif col.startswith('fc_') or col.startswith('FC_'):
            feature_cols.append(col)
        elif col.startswith('SK233_'):
            feature_cols.append(col)
        elif col.startswith('station_'):
            feature_cols.append(col)
        elif col.startswith('flood_') or col.startswith('caudal_total'):
            feature_cols.append(col)

    feature_cols = list(dict.fromkeys(feature_cols))

    stat_cols = ['station_nivel_mean', 'station_nivel_std', 'station_nivel_p50',
                 'station_nivel_p75', 'station_nivel_p90', 'station_nivel_p95',
                 'station_nivel_p99', 'station_nivel_p005', 'station_nivel_p995',
                 'station_nivel_min', 'station_nivel_max', 'nivel_relativo']
    for col in stat_cols:
        combined[col] = 0.0
        if col not in feature_cols:
            feature_cols.append(col)

    existing_features = [c for c in feature_cols if c in combined.columns]
    print('  Total features: {}'.format(len(existing_features)))

    for col in existing_features:
        if combined[col].dtype in [np.float64, np.float32, np.int64, np.int32]:
            combined[col] = combined[col].fillna(0)

    return combined, existing_features


def build_and_train(combined, feature_cols, station_stats, station_frames):
    print('[TRAIN] Building hybrid global+local models...')

    target_col = 'nivel_atual'
    metrics_all = []
    models_info = []
    thresholds = []

    for sk in NATURAL_STATIONS:
        nivel_col = 'SNIRH_SK{}_NIVEL_INST'.format(sk)
        if nivel_col not in combined.columns:
            continue
        sk_data = combined[combined['station_sk'] == sk].copy()
        sk_data = sk_data.dropna(subset=[nivel_col])
        sk_data[target_col] = sk_data[nivel_col]
        if sk in combined.columns:
            combined.loc[combined['station_sk'] == sk, target_col] = sk_data[target_col]

    for sk in NATURAL_STATIONS:
        nivel_col = 'SNIRH_SK{}_NIVEL_INST'.format(sk)
        if nivel_col not in combined.columns:
            continue
        mask = combined['station_sk'] == sk
        combined.loc[mask, target_col] = combined.loc[mask, nivel_col]

    combined.dropna(subset=[target_col], inplace=True)
    combined[target_col] = combined[target_col].astype(float)

    for sk in NATURAL_STATIONS:
        stats = station_stats.get(sk, {})
        if not stats:
            continue
        mask = combined['station_sk'] == sk
        p005 = stats.get('p005', stats.get('min', 0))
        p995 = stats.get('p995', stats.get('max', 100))
        combined.loc[mask & (combined[target_col] < p005), target_col] = p005
        combined.loc[mask & (combined[target_col] > p995), target_col] = p995

    for horizon in FORECAST_HORIZONS:
        print()
        print('=== Horizon: {}h ==='.format(horizon))

        df_model = combined.copy()
        df_model['target'] = df_model.groupby('station_sk')[target_col].shift(-horizon)
        df_model = df_model.dropna(subset=['target'])

        existing_feats = [c for c in feature_cols if c in df_model.columns]
        X = df_model[existing_feats].copy()
        y = df_model['target'].copy()

        X['station_sk'] = X['station_sk'].astype(int)

        tscv = TimeSeriesSplit(n_splits=5)
        fold_metrics = []

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_train, X_val = X.iloc[train_idx].copy(), X.iloc[val_idx].copy()
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

            train_end_ts = X_train.index[-1]
            fold_stats = compute_station_stats(station_frames, until_idx=train_end_ts)

            for sk in NATURAL_STATIONS:
                fs = fold_stats.get(sk, {})
                if not fs:
                    continue
                mask_tr = X_train['station_sk'] == sk
                mask_va = X_val['station_sk'] == sk
                for stat_name, stat_val in fs.items():
                    col = 'station_nivel_{}'.format(stat_name)
                    X_train.loc[mask_tr, col] = stat_val
                    if col in X_val.columns:
                        X_val.loc[mask_va, col] = stat_val

                nivel_tr = y_train[mask_tr]
                if 'mean' in fs and 'std' in fs and fs['std'] > 0:
                    col_nr = 'nivel_relativo'
                    nivel_feat = X_train.loc[mask_tr, 'nivel_lag_1h'] if 'nivel_lag_1h' in X_train.columns else nivel_tr
                    X_train.loc[mask_tr, col_nr] = (nivel_feat - fs['mean']) / fs['std']
                    if col_nr in X_val.columns:
                        nivel_feat_v = X_val.loc[mask_va, 'nivel_lag_1h'] if 'nivel_lag_1h' in X_val.columns else y_val[mask_va]
                        X_val.loc[mask_va, col_nr] = (nivel_feat_v - fs['mean']) / fs['std']

            X_train = X_train.fillna(0)
            X_val = X_val.fillna(0)

            weights = np.ones(len(y_train))
            for sk in NATURAL_STATIONS:
                mask = X_train['station_sk'] == sk
                fs = fold_stats.get(sk, {})
                p90 = fs.get('p90', 0)
                if p90 > 0:
                    weights[mask & (y_train > p90).values] = 3.0

            cat_features = ['station_sk']
            dtrain = lgb.Dataset(X_train, label=y_train, weight=weights,
                                 categorical_feature=cat_features, free_raw_data=False)
            dval = lgb.Dataset(X_val, label=y_val, reference=dtrain, free_raw_data=False)

            global_model = lgb.train(
                LGB_GLOBAL_PARAMS, dtrain,
                num_boost_round=2000,
                valid_sets=[dval],
                callbacks=[lgb.early_stopping(50, verbose=False),
                           lgb.log_evaluation(200)])

            val_pred_global = global_model.predict(X_val)

            val_pred_final = val_pred_global.copy()
            local_models_fold = {}

            for sk in NATURAL_STATIONS:
                mask_tr = X_train['station_sk'] == sk
                mask_va = X_val['station_sk'] == sk
                if mask_tr.sum() < 50 or mask_va.sum() < 10:
                    continue
                residuals = y_train[mask_tr] - global_model.predict(X_train[mask_tr])
                dtrain_local = lgb.Dataset(X_train[mask_tr], label=residuals)
                local_model = lgb.train(
                    {**LGB_LOCAL_PARAMS, 'num_leaves': 15},
                    dtrain_local, num_boost_round=20)
                local_models_fold[sk] = local_model
                val_pred_final[mask_va] += local_model.predict(X_val[mask_va])

            mae_val = mean_absolute_error(y_val, val_pred_final)
            rmse_val = np.sqrt(mean_squared_error(y_val, val_pred_final))
            r2_val = r2_score(y_val, val_pred_final)
            ss_res = np.sum((y_val - val_pred_final) ** 2)
            ss_tot = np.sum((y_val - y_val.mean()) ** 2)
            nse_val = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            fold_metrics.append({
                'mae': mae_val, 'rmse': rmse_val,
                'r2': r2_val, 'nse': nse_val})
            print('  Fold {}: MAE={:.4f} RMSE={:.4f} R2={:.4f} NSE={:.4f}'.format(
                fold + 1, mae_val, rmse_val, r2_val, nse_val))

        avg = {k: np.mean([m[k] for m in fold_metrics]) for k in fold_metrics[0]}
        print('  AVG: MAE={:.4f} RMSE={:.4f} R2={:.4f} NSE={:.4f}'.format(
            avg['mae'], avg['rmse'], avg['r2'], avg['nse']))

        p90_global = combined.groupby('station_sk')[target_col].transform(
            lambda x: x.quantile(0.90))
        weights_all = np.where(combined[target_col] > p90_global, 3.0, 1.0)

        df_full = combined.dropna(subset=[target_col]).copy()
        df_full['target'] = df_full.groupby('station_sk')[target_col].shift(-horizon)
        df_full = df_full.dropna(subset=['target'])
        X_full = df_full[existing_feats].copy()
        y_full = df_full['target'].copy()
        X_full['station_sk'] = X_full['station_sk'].astype(int)

        p90_full = df_full.groupby('station_sk')['target'].transform(
            lambda x: x.quantile(0.90))
        weights_full = np.where(df_full['target'] > p90_full, 3.0, 1.0)

        dtrain_full = lgb.Dataset(X_full, label=y_full, weight=weights_full,
                                  categorical_feature=['station_sk'])
        global_model_final = lgb.train(LGB_GLOBAL_PARAMS, dtrain_full, num_boost_round=global_model.best_iteration)

        global_model_final.save_model(model_global_path(horizon))
        print('  Global model saved: {}'.format(model_global_path(horizon)))

        for sk in NATURAL_STATIONS:
            mask_sk = X_full['station_sk'] == sk
            if mask_sk.sum() < 50:
                continue
            residuals = y_full[mask_sk] - global_model_final.predict(X_full[mask_sk])
            dtrain_local = lgb.Dataset(X_full[mask_sk], label=residuals)
            local_model = lgb.train(LGB_LOCAL_PARAMS, dtrain_local, num_boost_round=20)
            local_model.save_model(model_local_path(sk, horizon))
            print('  Local model saved: {}'.format(model_local_path(sk, horizon)))

        imp = global_model_final.feature_importance(importance_type='gain')
        feat_names = global_model_final.feature_name()
        top10 = sorted(zip(feat_names, imp), key=lambda x: -x[1])[:10]
        top10_json = json.dumps([{ 'feature': f, 'importance': int(i) } for f, i in top10])

        for sk in NATURAL_STATIONS:
            stats = station_stats.get(sk, {})
            mask_sk = df_full['station_sk'] == sk
            n_train = mask_sk.sum()
            metrics_all.append({
                'estacao_sk': sk, 'target_parametro': 'NIVEL_INST',
                'horizon_hours': horizon, 'modelo_tipo': 'GLOBAL_HYBRID',
                'train_samples': int(n_train),
                'test_samples': int(n_train * 0.2),
                'n_estimators': global_model_final.num_trees(),
                'n_features': len(existing_feats),
                'mae': float(avg['mae']),
                'rmse': float(avg['rmse']),
                'r2': float(avg['r2']),
                'nse': float(avg['nse']),
                'mean_actual': float(stats.get('mean', 0)),
                'mean_predicted': float(stats.get('mean', 0)),
                'feature_importance_top10': top10_json,
            })
            models_info.append({
                'estacao_sk': sk, 'target_parametro': 'NIVEL_INST',
                'horizon_hours': horizon, 'algorithm': 'LightGBM_GlobalHybrid',
                'model_path': model_global_path(horizon),
                'scaler_path': scaler_path(),
                'feature_list_path': features_path(),
                'n_features': len(existing_feats),
                'n_train_samples': int(n_train),
                'n_estimators': global_model_final.num_trees(),
                'mae': float(avg['mae']),
                'r2': float(avg['r2']),
                'versao': MODEL_VERSION,
                'modelo_tipo': 'GLOBAL_HYBRID',
            })

        if horizon == FORECAST_HORIZONS[0]:
            for sk in NATURAL_STATIONS:
                stats = station_stats.get(sk, {})
                thresholds.append({
                    'estacao_sk': sk,
                    'target_parametro': 'NIVEL_INST',
                    'p50': stats.get('p50', 0),
                    'p75': stats.get('p75', 0),
                    'p90': stats.get('p90', 0),
                    'p95': stats.get('p95', 0),
                    'p99': stats.get('p99', 0),
                    'max_hist': stats.get('max', 0),
                })

    return metrics_all, models_info, thresholds, existing_feats


def save_scaler_and_features(combined, feature_cols):
    existing = [c for c in feature_cols if c in combined.columns]
    numeric_cols = [c for c in existing if combined[c].dtype in [np.float64, np.float32, np.int64, np.int32]]
    scaler = RobustScaler()
    valid_data = combined[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
    scaler.fit(valid_data)
    with open(scaler_path(), 'wb') as f:
        pickle.dump(scaler, f)
    with open(features_path(), 'wb') as f:
        pickle.dump(existing, f)
    print('[SAVE] Scaler and feature list saved')


def save_results(conn, metrics, models_info, thresholds, feature_cols):
    print('[SAVE] Writing results to DB...')
    cur = conn.cursor()

    cur.execute("IF OBJECT_ID('ml.forecast_metrics') IS NOT NULL DROP TABLE ml.forecast_metrics")
    cur.execute("""
        CREATE TABLE ml.forecast_metrics (
            metric_id BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
            estacao_sk INT NOT NULL,
            target_parametro VARCHAR(50) NOT NULL,
            horizon_hours INT NOT NULL,
            modelo_tipo VARCHAR(20),
            train_samples INT,
            test_samples INT,
            n_estimators INT,
            n_features INT,
            mae FLOAT, rmse FLOAT, r2 FLOAT, nse FLOAT,
            mean_actual FLOAT, mean_predicted FLOAT,
            feature_importance_top10 NVARCHAR(MAX),
            data_treino DATETIME DEFAULT GETDATE()
        )
    """)
    cur.execute("CREATE CLUSTERED INDEX IX_ml_forecast_metrics ON ml.forecast_metrics (estacao_sk, horizon_hours)")
    for m in metrics:
        cols = list(m.keys())
        vals = list(m.values())
        ph = ','.join(['?'] * len(cols))
        cur.execute("INSERT INTO ml.forecast_metrics ({}) VALUES ({})".format(','.join(cols), ph), vals)
    print('  ml.forecast_metrics: {} rows'.format(len(metrics)))

    cur.execute("DELETE FROM ctl.ml_models")
    for mi in models_info:
        cols = list(mi.keys())
        vals = list(mi.values())
        ph = ','.join(['?'] * len(cols))
        cur.execute("INSERT INTO ctl.ml_models ({}) VALUES ({})".format(','.join(cols), ph), vals)
    print('  ctl.ml_models: {} rows'.format(len(models_info)))

    cur.execute("DELETE FROM ctl.ml_risk_thresholds")
    for t in thresholds:
        cur.execute("""
            INSERT INTO ctl.ml_risk_thresholds
            (estacao_sk, target_parametro, p50, p75, p90, p95, p99, max_hist)
            VALUES (?,?,?,?,?,?,?,?)
        """, t['estacao_sk'], t['target_parametro'],
           t['p50'], t['p75'], t['p90'], t['p95'], t['p99'], t['max_hist'])
    print('  ctl.ml_risk_thresholds: {} rows'.format(len(thresholds)))

    print('[SAVE] Results saved successfully')


def print_summary(metrics):
    print()
    print('=' * 80)
    print('  FORECAST ML {} — TRAINING SUMMARY'.format(MODEL_VERSION))
    print('=' * 80)
    print('  Model type: Hybrid Global+Local (LightGBM)')
    print('  Targets: NIVEL_INST at {} natural stations'.format(len(NATURAL_STATIONS)))
    print('  Horizons: {}h'.format(FORECAST_HORIZONS))
    print()
    print('  {:8s} {:8s} {:>8s} {:>8s} {:>8s} {:>8s}'.format(
        'Station', 'Horizon', 'MAE', 'RMSE', 'R2', 'NSE'))
    print('  ' + '-' * 56)
    for m in metrics:
        print('  SK={:<5d} {:>5d}h   {:.4f}   {:.4f}   {:.4f}   {:.4f}'.format(
            m['estacao_sk'], m['horizon_hours'],
            m['mae'], m['rmse'], m['r2'], m['nse']))
    print()


def main():
    start = datetime.now()
    print('=' * 80)
    print('  FORECAST ML {} — STARTING'.format(MODEL_VERSION))
    print('  Time: {}'.format(start))
    print('=' * 80)

    ensure_models_dir()
    conn = get_conn()

    try:
        station_frames, prox_map = load_and_merge(conn)
        station_stats = compute_station_stats(station_frames)
        print('[STATS] Computed stats for {} stations'.format(len(station_stats)))

        combined, feature_cols = engineer_features(station_frames, station_stats)
        print('[DATA] Combined frame: {:,} rows x {} features'.format(len(combined), len(feature_cols)))

        save_scaler_and_features(combined, feature_cols)

        with open(station_stats_path(), 'wb') as f:
            pickle.dump(station_stats, f)

        metrics, models_info, thresholds, final_features = build_and_train(
            combined, feature_cols, station_stats, station_frames)

        save_results(conn, metrics, models_info, thresholds, final_features)
        print_summary(metrics)

        elapsed = datetime.now() - start
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
