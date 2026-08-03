import os
import sys
import numpy as np
import pandas as pd
import pickle
import json
from datetime import datetime, timedelta
import pyodbc
import warnings
warnings.filterwarnings('ignore')

from preflood_config import DB_NAME, get_conn, NATURAL_STATIONS, DAM_STATIONS, SCRIPTS_DIR, PROJECT_DIR

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, callbacks
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import (roc_auc_score, precision_score, recall_score,
                             f1_score, confusion_matrix, classification_report)

MODEL_VERSION = 'v6.0_lstm'
FLOOD_HORIZONS = [6, 12, 24]
LOOKBACK = 48
BATCH_SIZE = 512
EPOCHS = 15
PATIENCE = 3
CLASS_WEIGHT_FACTOR = 10.0
UNDERSAMPLE_RATIO = 3.0
RESAMPLE_H = 3

LSTM_FEATURES = [
    'nivel', 'nivel_lag_1h', 'nivel_lag_3h', 'nivel_lag_6h',
    'nivel_delta_1h', 'nivel_delta_3h', 'nivel_delta_6h',
    'nivel_rmean_6h', 'nivel_rmean_24h', 'nivel_rstd_24h',
    'era5_precip', 'era5_precip_accum_6h', 'era5_precip_accum_24h',
    'era5_temp', 'era5_soil_l1', 'era5_pressure',
    'hour_sin', 'hour_cos', 'month_sin', 'month_cos',
]

BACKTEST_EVENTS = [
    {'name': 'Cheia Jan 2001', 'start': '2001-01-25', 'end': '2001-01-30'},
    {'name': 'Cheia Jan-Fev 2016', 'start': '2016-01-01', 'end': '2016-02-29'},
    {'name': 'Cheia Dez 2019', 'start': '2019-12-01', 'end': '2019-12-31'},
    {'name': 'Cheia Fev 2026', 'start': '2026-02-01', 'end': '2026-02-28'},
]

MODELS_DIR = os.path.join(PROJECT_DIR, 'Models', 'lstm')


def ensure_dirs():
    os.makedirs(MODELS_DIR, exist_ok=True)


def load_data(conn):
    print('[DATA] Loading SNIRH + ERA5 data...')
    snirh_query = """
        SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE e.sistema_origem = 'SNIRH'
          AND e.estacao_sk IN ({})
          AND p.parametro_codigo IN ('1843')
    """.format(','.join(str(s) for s in NATURAL_STATIONS))
    snirh = pd.read_sql(snirh_query, conn)
    snirh.columns = ['estacao_sk', 'data_hora', 'parametro', 'valor']
    snirh['data_hora'] = pd.to_datetime(snirh['data_hora'])

    era5_query = """
        SELECT e.estacao_sk, t.data_hora, p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE e.sistema_origem = 'ERA5'
          AND p.parametro_codigo IN ('tp', 't2m', 'swvl1', 'sp')
    """
    era5 = pd.read_sql(era5_query, conn)
    era5.columns = ['estacao_sk', 'data_hora', 'parametro', 'valor']
    era5['data_hora'] = pd.to_datetime(era5['data_hora'])

    prox_query = """
        SELECT source_station_sk, target_station_sk, is_nearest
        FROM ctl.map_spatial_proximity
        WHERE is_nearest = 1 AND source_station_sk IN ({})
    """.format(','.join(str(s) for s in NATURAL_STATIONS))
    prox = pd.read_sql(prox_query, conn)

    print('  SNIRH: {:,} rows, ERA5: {:,} rows'.format(len(snirh), len(era5)))
    return snirh, era5, prox


def build_station_features(snirh, era5, prox):
    print('[FEATURES] Building per-station feature matrices...')
    station_data = {}

    for sk in NATURAL_STATIONS:
        sub = snirh[snirh['estacao_sk'] == sk].copy()
        sub = sub.sort_values('data_hora').drop_duplicates('data_hora')
        sub = sub.set_index('data_hora')
        sub = sub.resample('1h').last().ffill()

        df = pd.DataFrame(index=sub.index)
        df['nivel'] = sub['valor']

        df['nivel_lag_1h'] = df['nivel'].shift(1)
        df['nivel_lag_3h'] = df['nivel'].shift(3)
        df['nivel_lag_6h'] = df['nivel'].shift(6)
        df['nivel_delta_1h'] = df['nivel'] - df['nivel'].shift(1)
        df['nivel_delta_3h'] = df['nivel'] - df['nivel'].shift(3)
        df['nivel_delta_6h'] = df['nivel'] - df['nivel'].shift(6)
        df['nivel_rmean_6h'] = df['nivel'].rolling(6, min_periods=1).mean()
        df['nivel_rmean_24h'] = df['nivel'].rolling(24, min_periods=1).mean()
        df['nivel_rstd_24h'] = df['nivel'].rolling(24, min_periods=1).std()

        era5_sk = prox[prox['source_station_sk'] == sk]['target_station_sk'].values
        if len(era5_sk) > 0:
            era5_sub = era5[era5['estacao_sk'] == era5_sk[0]].copy()
            era5_sub = era5_sub.sort_values('data_hora').drop_duplicates('data_hora')
            era5_sub = era5_sub.set_index('data_hora')
            era5_sub = era5_sub.resample('1h').last().ffill()

            for param_code, col_name in [('tp', 'era5_precip'), ('t2m', 'era5_temp'),
                                          ('swvl1', 'era5_soil_l1'), ('sp', 'era5_pressure')]:
                psub = era5_sub[era5_sub['parametro'] == param_code]
                if len(psub) > 0:
                    df[col_name] = psub['valor'].reindex(df.index).ffill()

        if 'era5_precip' in df.columns:
            df['era5_precip_accum_6h'] = df['era5_precip'].rolling(6, min_periods=1).sum()
            df['era5_precip_accum_24h'] = df['era5_precip'].rolling(24, min_periods=1).sum()

        df['hour_sin'] = np.sin(2 * np.pi * df.index.hour / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df.index.hour / 24)
        df['month_sin'] = np.sin(2 * np.pi * df.index.month / 12)
        df['month_cos'] = np.cos(2 * np.pi * df.index.month / 12)

        for col in LSTM_FEATURES:
            if col not in df.columns:
                df[col] = 0.0
        df = df[LSTM_FEATURES]

        station_data[sk] = df
        print('  SK={}: {:,} rows, {}-{}'.format(sk, len(df), df.index[0], df.index[-1]))

    return station_data


def load_or_build_labels(conn, station_data):
    print('[LABELS] Loading flood labels...')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='ml' AND TABLE_NAME='flood_labels'")
    if cur.fetchone()[0] == 0:
        print('  ml.flood_labels not found. Run flood_labeling.py first.')
        sys.exit(1)

    labels_query = """
        SELECT estacao_sk, data_hora, flood_6h, flood_12h, flood_24h, nivel_p95
        FROM ml.flood_labels
    """
    labels = pd.read_sql(labels_query, conn)
    labels['data_hora'] = pd.to_datetime(labels['data_hora'])
    return labels


def build_sequences(station_data, labels, horizon):
    print('[SEQ] Building sequences for horizon={}h...'.format(horizon))
    flood_col = 'flood_{}h'.format(horizon)
    X_flood, y_flood, sk_flood, ts_flood = [], [], [], []
    X_normal, y_normal, sk_normal, ts_normal = [], [], [], []

    for sk in NATURAL_STATIONS:
        if sk not in station_data:
            continue
        df = station_data[sk].copy()
        sk_labels = labels[labels['estacao_sk'] == sk].copy()
        sk_labels = sk_labels.set_index('data_hora').sort_index()
        sk_labels = sk_labels.reindex(df.index)
        sk_labels = sk_labels.fillna(0)

        df = df.fillna(0)
        vals = df.values.astype(np.float32)
        label_vals = sk_labels[flood_col].values.astype(np.float32) if flood_col in sk_labels.columns else np.zeros(len(df))

        for i in range(LOOKBACK, len(vals), RESAMPLE_H):
            if np.any(np.isnan(vals[i - LOOKBACK:i])):
                continue
            seq = vals[i - LOOKBACK:i]
            lbl = label_vals[i]
            if lbl >= 1:
                X_flood.append(seq)
                y_flood.append(lbl)
                sk_flood.append(sk)
                ts_flood.append(df.index[i])
            else:
                X_normal.append(seq)
                y_normal.append(lbl)
                sk_normal.append(sk)
                ts_normal.append(df.index[i])

    n_flood = len(y_flood)
    n_normal_keep = min(len(y_normal), int(n_flood * UNDERSAMPLE_RATIO))
    rng = np.random.default_rng(42)
    normal_idx = rng.choice(len(y_normal), size=n_normal_keep, replace=False)
    normal_idx = np.sort(normal_idx)

    X_normal = [X_normal[i] for i in normal_idx]
    y_normal = [y_normal[i] for i in normal_idx]
    sk_normal = [sk_normal[i] for i in normal_idx]
    ts_normal = [ts_normal[i] for i in normal_idx]

    X_all = X_flood + X_normal
    y_all = y_flood + y_normal
    sk_all = sk_flood + sk_normal
    ts_all = ts_flood + ts_normal

    X = np.array(X_all, dtype=np.float32)
    y = np.array(y_all, dtype=np.float32)
    sk_arr = np.array(sk_all)
    ts_arr = np.array(ts_all)

    sort_idx = np.argsort(ts_arr)
    X = X[sort_idx]
    y = y[sort_idx]
    sk_arr = sk_arr[sort_idx]
    ts_arr = ts_arr[sort_idx]

    print('  Sequences: {:,} total (flood: {:,}, normal: {:,}, ratio 1:{:.0f})'.format(
        len(y), n_flood, n_normal_keep, n_normal_keep / max(n_flood, 1)))
    return X, y, sk_arr, ts_arr


def temporal_split(X, y, sk_arr, ts_arr, train_pct=0.7, val_pct=0.15):
    n = len(X)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + val_pct))
    return (X[:train_end], y[:train_end], sk_arr[:train_end], ts_arr[:train_end],
            X[train_end:val_end], y[train_end:val_end], sk_arr[train_end:val_end], ts_arr[train_end:val_end],
            X[val_end:], y[val_end:], sk_arr[val_end:], ts_arr[val_end:])


def build_lstm_model(input_shape):
    model = keras.Sequential([
        layers.Input(shape=input_shape),
        layers.LSTM(64, return_sequences=True, recurrent_dropout=0.0),
        layers.Dropout(0.2),
        layers.LSTM(32, recurrent_dropout=0.0),
        layers.Dropout(0.2),
        layers.Dense(16, activation='relu'),
        layers.Dense(1, activation='sigmoid'),
    ])
    model.compile(
        optimizer=keras.optimizers.Adam(1e-3, clipnorm=1.0),
        loss='binary_crossentropy',
        metrics=[
            keras.metrics.AUC(name='auc'),
            keras.metrics.Precision(name='precision'),
            keras.metrics.Recall(name='recall'),
        ],
    )
    return model


def find_best_threshold(y_true, y_prob):
    best_f1 = 0
    best_th = 0.5
    for th in np.arange(0.1, 0.9, 0.05):
        y_pred = (y_prob >= th).astype(int)
        if y_pred.sum() == 0:
            continue
        f1 = f1_score(y_true, y_pred)
        if f1 > best_f1:
            best_f1 = f1
            best_th = th
    return best_th, best_f1


def backtest_event(y_prob, ts_arr, sk_arr, event, horizon):
    start = pd.Timestamp(event['start'])
    end = pd.Timestamp(event['end'])
    mask = (ts_arr >= start) & (ts_arr <= end)
    if mask.sum() == 0:
        print('  {} {}h: NO DATA'.format(event['name'], horizon))
        return
    event_prob = y_prob[mask]
    event_ts = ts_arr[mask]
    print('  {} {}h: max_prob={:.3f}, mean_prob={:.3f}, n={:,}'.format(
        event['name'], horizon, event_prob.max(), event_prob.mean(), mask.sum()))
    for th in [0.3, 0.5, 0.7]:
        flagged = (event_prob >= th).sum()
        print('    threshold={:.1f}: {:,}/{:,} flagged'.format(th, flagged, mask.sum()))


def save_results(conn, horizon, metrics, model, scaler, best_threshold):
    print('[SAVE] Saving LSTM results for horizon={}h...'.format(horizon))
    model_path = os.path.join(MODELS_DIR, 'lstm_flood_h{}.keras'.format(horizon))
    model.save(model_path)
    scaler_path = os.path.join(MODELS_DIR, 'scaler_h{}.pkl'.format(horizon))
    with open(scaler_path, 'wb') as f:
        pickle.dump(scaler, f)
    config_path = os.path.join(MODELS_DIR, 'config_h{}.json'.format(horizon))
    config = {
        'horizon': horizon, 'lookback': LOOKBACK,
        'features': LSTM_FEATURES, 'threshold': float(best_threshold),
        'version': MODEL_VERSION,
    }
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    cur = conn.cursor()
    cur.execute("""
        IF OBJECT_ID('ml.lstm_predictions') IS NOT NULL DROP TABLE ml.lstm_predictions
    """)
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

    cur.execute("DELETE FROM ctl.ml_models WHERE algorithm = 'LSTM_Flood' AND horizon_hours = ?", horizon)
    for sk in NATURAL_STATIONS:
        cur.execute("""
            INSERT INTO ctl.ml_models
            (estacao_sk, target_parametro, horizon_hours, algorithm, model_path,
             scaler_path, n_features, mae, r2, versao, modelo_tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, sk, 'FLOOD_BINARY', horizon, 'LSTM_Flood', model_path,
             scaler_path, len(LSTM_FEATURES),
             metrics.get('auc', 0), metrics.get('f1', 0),
             MODEL_VERSION, 'LSTM_BINARY')
    conn.commit()
    print('  Saved model, scaler, config, and DB records')


def main():
    start = datetime.now()
    print('=' * 80)
    print('  LSTM FLOOD PREDICTION {}'.format(MODEL_VERSION))
    print('  Time: {}'.format(start))
    print('  TF version: {}'.format(tf.__version__))
    print('  GPU: {}'.format(tf.config.list_physical_devices('GPU')))
    print('=' * 80)

    ensure_dirs()
    conn = get_conn()

    try:
        snirh, era5, prox = load_data(conn)
        station_data = build_station_features(snirh, era5, prox)
        labels = load_or_build_labels(conn, station_data)

        for horizon in FLOOD_HORIZONS:
            print()
            print('=' * 60)
            print('  HORIZON: {}h'.format(horizon))
            print('=' * 60)

            X, y, sk_arr, ts_arr = build_sequences(station_data, labels, horizon)

            X_tr, y_tr, sk_tr, ts_tr, X_va, y_va, sk_va, ts_va, X_te, y_te, sk_te, ts_te = \
                temporal_split(X, y, sk_arr, ts_arr)

            scaler = RobustScaler()
            X_tr_flat = X_tr.reshape(-1, X_tr.shape[-1])
            scaler.fit(X_tr_flat)
            X_tr_scaled = scaler.transform(X_tr_flat).reshape(X_tr.shape)
            X_va_scaled = scaler.transform(X_va.reshape(-1, X_va.shape[-1])).reshape(X_va.shape)
            X_te_scaled = scaler.transform(X_te.reshape(-1, X_te.shape[-1])).reshape(X_te.shape)

            n_pos = int(y_tr.sum())
            n_neg = len(y_tr) - n_pos
            class_weight = {0: 1.0, 1: min(CLASS_WEIGHT_FACTOR, n_neg / max(n_pos, 1))}
            print('  Train: {:,} (flood: {:,}, {:.1f}%), class_weight: {}'.format(
                len(y_tr), n_pos, 100.0 * n_pos / len(y_tr), class_weight))

            model = build_lstm_model((LOOKBACK, X_tr.shape[-1]))

            lr_schedule = keras.optimizers.schedules.CosineDecay(
                initial_learning_rate=1e-3, decay_steps=EPOCHS * len(X_tr) // BATCH_SIZE,
                alpha=1e-5)
            model.optimizer = keras.optimizers.Adam(learning_rate=lr_schedule, clipnorm=1.0)

            cb = [
                callbacks.EarlyStopping(monitor='val_auc', mode='max', patience=PATIENCE,
                                        restore_best_weights=True),
            ]

            history = model.fit(
                X_tr_scaled, y_tr,
                validation_data=(X_va_scaled, y_va),
                epochs=EPOCHS, batch_size=BATCH_SIZE,
                class_weight=class_weight,
                callbacks=cb, verbose=2,
            )

            y_prob = model.predict(X_te_scaled, batch_size=BATCH_SIZE).flatten()
            best_th, best_f1 = find_best_threshold(y_te, y_prob)
            y_pred = (y_prob >= best_th).astype(int)

            auc = roc_auc_score(y_te, y_prob) if len(np.unique(y_te)) > 1 else 0
            prec = precision_score(y_te, y_pred, zero_division=0)
            rec = recall_score(y_te, y_pred, zero_division=0)
            f1 = f1_score(y_te, y_pred, zero_division=0)

            if y_pred.sum() > 0 and y_te.sum() > 0:
                tp = ((y_pred == 1) & (y_te == 1)).sum()
                fp = ((y_pred == 1) & (y_te == 0)).sum()
                fn = ((y_pred == 0) & (y_te == 1)).sum()
                csi = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0
            else:
                csi = 0

            print()
            print('  RESULTS (horizon={}h, threshold={:.2f}):'.format(horizon, best_th))
            print('    AUC:       {:.4f}'.format(auc))
            print('    Precision: {:.4f}'.format(prec))
            print('    Recall:    {:.4f}'.format(rec))
            print('    F1:        {:.4f}'.format(f1))
            print('    CSI:       {:.4f}'.format(csi))
            print('    Confusion:')
            print('    {}'.format(confusion_matrix(y_te, y_pred)))

            print()
            print('  Backtesting against known events:')
            y_prob_va = model.predict(X_va_scaled, batch_size=BATCH_SIZE).flatten()
            y_prob_all = np.concatenate([y_prob_va, y_prob])
            ts_all_bt = np.concatenate([ts_va, ts_te])
            sk_all_bt = np.concatenate([sk_va, sk_te])
            for event in BACKTEST_EVENTS:
                backtest_event(y_prob_all, ts_all_bt, sk_all_bt, event, horizon)

            metrics = {'auc': auc, 'precision': prec, 'recall': rec,
                       'f1': f1, 'csi': csi, 'threshold': best_th}
            save_results(conn, horizon, metrics, model, scaler, best_th)

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
