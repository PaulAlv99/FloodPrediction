import os
import sys
import json
import pyodbc
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import silhouette_score, calinski_harabasz_score, davies_bouldin_score
import hdbscan
import warnings
warnings.filterwarnings('ignore')

from preflood_config import DB_NAME, get_conn
DEFAULT_SAMPLE = 50000
MAX_K = 8
MODEL_VERSION = 'v5.0'

NATURAL_STATIONS = [229, 232, 233, 234]
SNIRH_PARAMS = ['1843', '1845', '1850', '3212219030', '354895424']
ERA5_PARAMS = ['tp', 't2m', 'swvl1', 'swvl2', 'sp']

PARAM_ALIAS = {
    '1843': 'NIVEL_INST', '1845': 'NIVEL_MED_DIA', '1850': 'CAUDAL_MED_DIA',
    '3212219030': 'CAUDAL_DESC_DIA', '354895424': 'CAUDAL_AFLUENTE_DIA',
    'tp': 'PRECIPITACAO', 't2m': 'TEMP_2M',
    'swvl1': 'SOLO_UM_L1', 'swvl2': 'SOLO_UM_L2', 'sp': 'PRESSAO_SUPERFICIE',
}


def extract_features(conn, sample_size=None):
    print('[EXTRACT] Loading data for natural river stations...')
    cur = conn.cursor()

    all_params = SNIRH_PARAMS + ERA5_PARAMS
    ph = ','.join(['?'] * len(all_params))
    sk_ph = ','.join(['?'] * len(NATURAL_STATIONS))
    cur.execute("""
        SELECT e.estacao_sk, e.estacao_nome, t.data_hora, t.ano, t.mes, t.hora,
               p.parametro_codigo, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_estacao e ON f.estacao_sk = e.estacao_sk
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE e.estacao_sk IN (""" + sk_ph + """)
        AND p.parametro_codigo IN (""" + ph + """)
    """, NATURAL_STATIONS + all_params)
    rows = cur.fetchall()
    print('  Raw rows: {:,}'.format(len(rows)))

    df = pd.DataFrame(
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows],
        columns=['estacao_sk', 'estacao_nome', 'data_hora', 'ano', 'mes', 'hora',
                 'parametro_codigo', 'valor'])
    df.dropna(subset=['valor'], inplace=True)
    df['data_hora'] = pd.to_datetime(df['data_hora'])

    pivot = df.pivot_table(
        index=['estacao_sk', 'estacao_nome', 'data_hora', 'ano', 'mes', 'hora'],
        columns='parametro_codigo', values='valor', aggfunc='first')
    pivot = pivot.reset_index()
    pivot = pivot.rename(columns=PARAM_ALIAS)
    pivot = pivot.sort_values(['estacao_sk', 'data_hora']).reset_index(drop=True)

    if sample_size and len(pivot) > sample_size:
        n_per = sample_size // len(NATURAL_STATIONS)
        parts = []
        for sk in NATURAL_STATIONS:
            sub = pivot[pivot['estacao_sk'] == sk]
            if len(sub) > n_per:
                sub = sub.sample(n=n_per, random_state=42)
            parts.append(sub)
        pivot = pd.concat(parts).sort_values('data_hora').reset_index(drop=True)
        print('  Sampled to {:,} rows'.format(len(pivot)))

    print('  Pivot shape: {}'.format(pivot.shape))
    return pivot


def compute_lagged_features(df):
    print('[FEATURES] Computing lagged and derived features...')
    result_frames = []

    for sk in NATURAL_STATIONS:
        mask = df['estacao_sk'] == sk
        station = df[mask].copy().sort_values('data_hora')

        if 'NIVEL_INST' not in station.columns:
            continue

        nivel = station['NIVEL_INST']
        station_stats = {
            'mean': nivel.mean(),
            'std': nivel.std(),
            'p50': nivel.quantile(0.50),
            'p90': nivel.quantile(0.90),
            'p95': nivel.quantile(0.95),
            'p99': nivel.quantile(0.99),
        }

        station['taxa_subida_1h'] = nivel - nivel.shift(1)
        station['taxa_subida_3h'] = (nivel - nivel.shift(3)) / 3
        station['taxa_subida_6h'] = (nivel - nivel.shift(6)) / 6
        station['taxa_subida_12h'] = (nivel - nivel.shift(12)) / 12
        station['taxa_subida_24h'] = (nivel - nivel.shift(24)) / 24

        if station_stats['std'] > 0:
            station['nivel_zscore'] = (nivel - station_stats['mean']) / station_stats['std']
            station['nivel_relativo_pct'] = nivel.rank(pct=True)
        else:
            station['nivel_zscore'] = 0
            station['nivel_relativo_pct'] = 0.5

        for w in [3, 6, 12, 24]:
            r = nivel.rolling(window=w, min_periods=1)
            station['nivel_rmean_{}h'.format(w)] = r.mean()
            station['nivel_rstd_{}h'.format(w)] = r.std()
            station['nivel_rmax_{}h'.format(w)] = r.max()
            station['nivel_rrange_{}h'.format(w)] = r.max() - r.min()

        for w in [6, 12, 24]:
            rmean = nivel.rolling(window=w, min_periods=1).mean()
            rstd = nivel.rolling(window=w, min_periods=1).std()
            station['nivel_rcv_{}h'.format(w)] = rstd / (rmean + 1e-8)

        if 'PRECIPITACAO' in station.columns:
            precip = station['PRECIPITACAO'].fillna(0)
            for w in [6, 12, 24, 48]:
                station['precip_accum_{}h'.format(w)] = precip.rolling(window=w, min_periods=1).sum()
            station['precip_delta_6h'] = precip - precip.shift(6)

            p6 = precip.rolling(6, min_periods=1).sum()
            p6_prev = p6.shift(6)
            station['precip_acceleration'] = p6 / (p6_prev + 0.1)

            monthly_precip_mean = station.groupby('mes')['PRECIPITACAO'].transform('mean')
            station['precip_rel'] = precip / (monthly_precip_mean + 0.1)

        if 'SOLO_UM_L1' in station.columns:
            soil = station['SOLO_UM_L1'].fillna(0)
            soil_max = soil.max()
            if soil_max > 0:
                station['soil_saturacao_ratio'] = soil / soil_max
            else:
                station['soil_saturacao_ratio'] = 0
            station['soil_delta_24h'] = soil - soil.shift(24)

        if 'TEMP_2M' in station.columns:
            station['temp_delta_6h'] = station['TEMP_2M'] - station['TEMP_2M'].shift(6)

        if 'PRESSAO_SUPERFICIE' in station.columns:
            station['pressao_delta_6h'] = station['PRESSAO_SUPERFICIE'] - station['PRESSAO_SUPERFICIE'].shift(6)
            station['pressao_delta_12h'] = station['PRESSAO_SUPERFICIE'] - station['PRESSAO_SUPERFICIE'].shift(12)

        station['hour_sin'] = np.sin(2 * np.pi * station['hora'] / 24)
        station['hour_cos'] = np.cos(2 * np.pi * station['hora'] / 24)
        station['month_sin'] = np.sin(2 * np.pi * station['mes'] / 12)
        station['month_cos'] = np.cos(2 * np.pi * station['mes'] / 12)

        if 'precip_accum_24h' in station.columns and station_stats.get('p95', 0) > station_stats.get('p50', 0):
            denom = station_stats['p95'] - station_stats['p50']
            station['flood_index'] = ((nivel - station_stats['p50']) / max(denom, 0.01)) * \
                                     (station['precip_accum_24h'].fillna(0) / max(station['precip_accum_24h'].quantile(0.95), 0.1))

        result_frames.append(station)

    result = pd.concat(result_frames, axis=0).reset_index(drop=True)
    print('  Features computed: {} rows x {} cols'.format(result.shape[0], result.shape[1]))
    return result


def select_features(df):
    feature_keywords = [
        'taxa_subida', 'nivel_zscore', 'nivel_relativo_pct',
        'nivel_rmean', 'nivel_rstd', 'nivel_rmax', 'nivel_rrange', 'nivel_rcv',
        'precip_accum', 'precip_delta', 'precip_acceleration', 'precip_rel',
        'soil_saturacao', 'soil_delta',
        'temp_delta', 'pressao_delta',
        'hour_sin', 'hour_cos', 'month_sin', 'month_cos',
        'flood_index', 'SOLO_UM_L1', 'SOLO_UM_L2', 'TEMP_2M', 'PRESSAO_SUPERFICIE',
        'NIVEL_INST',
    ]
    selected = []
    for col in df.columns:
        if any(kw in col for kw in feature_keywords):
            if df[col].notna().sum() > 100:
                selected.append(col)

    numeric_cols = [c for c in selected if df[c].dtype in [np.float64, np.float32, np.int64, np.int32]]
    return numeric_cols


def drop_correlated(df, features, threshold=0.90):
    if len(features) < 2:
        return features
    corr = df[features].corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    to_drop = [c for c in upper.columns if any(upper[c] > threshold)]
    remaining = [f for f in features if f not in to_drop]
    print('  Dropped {} highly correlated features (>{}), kept {}'.format(
        len(to_drop), threshold, len(remaining)))
    return remaining


def elbow_and_silhouette(X_train, max_k):
    inertias = []
    silhouettes = []
    ch_scores = []
    db_scores = []
    k_range = range(2, max_k + 1)

    print('  Testing k from 2 to {}...'.format(max_k))
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        labels = km.fit_predict(X_train)
        inertias.append(km.inertia_)
        n_unique = len(set(labels))
        try:
            if n_unique > 1:
                silhouettes.append(silhouette_score(X_train, labels, sample_size=min(10000, len(X_train))))
                ch_scores.append(calinski_harabasz_score(X_train, labels))
                db_scores.append(davies_bouldin_score(X_train, labels))
            else:
                silhouettes.append(0)
                ch_scores.append(0)
                db_scores.append(10)
        except Exception:
            silhouettes.append(0)
            ch_scores.append(0)
            db_scores.append(10)

    print('  k  | Inertia    | Silhouette | CH Score   | DB Score')
    print('  ---|------------|------------|------------|----------')
    for i, k in enumerate(k_range):
        print('  {:2d} | {:10.1f} | {:10.4f} | {:10.1f} | {:.4f}'.format(
            k, inertias[i], silhouettes[i], ch_scores[i], db_scores[i]))

    best_idx = np.argmax(silhouettes)
    best_k = list(k_range)[best_idx]

    if len(inertias) >= 3:
        diffs = np.diff(inertias)
        second_diffs = np.diff(diffs)
        elbow_idx = np.argmax(second_diffs) + 1
        elbow_k = list(k_range)[elbow_idx]
        print('  Best silhouette k={}, Elbow k={}'.format(best_k, elbow_k))
    else:
        elbow_k = best_k

    return best_k, elbow_k, {
        'k_range': list(k_range),
        'inertias': [float(x) for x in inertias],
        'silhouettes': [float(x) for x in silhouettes],
        'ch_scores': [float(x) for x in ch_scores],
        'db_scores': [float(x) for x in db_scores],
    }


def train_and_validate(X_train, X_val, best_k):
    print('[CLUSTER] Training KMeans (k={}) + IsolationForest...'.format(best_k))

    km = KMeans(n_clusters=best_k, random_state=42, n_init=10, max_iter=300)
    km_labels_train = km.fit_predict(X_train)
    km_labels_val = km.predict(X_val)

    iso = IsolationForest(contamination=0.05, n_estimators=200, random_state=42)
    iso_labels_train = iso.fit_predict(X_train)
    iso_scores_train = iso.score_samples(X_train)
    iso_labels_val = iso.predict(X_val)
    iso_scores_val = iso.score_samples(X_val)

    if len(set(km_labels_val)) > 1:
        sil_val = silhouette_score(X_val, km_labels_val, sample_size=min(10000, len(X_val)))
        ch_val = calinski_harabasz_score(X_val, km_labels_val)
        db_val = davies_bouldin_score(X_val, km_labels_val)
    else:
        sil_val = ch_val = 0
        db_val = 10

    n_anomalies_train = (iso_labels_train == -1).sum()
    n_anomalies_val = (iso_labels_val == -1).sum()

    print('  Train: {} clusters, {} anomalies ({:.1f}%)'.format(
        best_k, n_anomalies_train, 100 * n_anomalies_train / len(X_train)))
    print('  Val:   silhouette={:.4f} CH={:.1f} DB={:.4f} anomalies={}'.format(
        sil_val, ch_val, db_val, n_anomalies_val))

    metrics = {
        'k': best_k,
        'train_n': len(X_train), 'val_n': len(X_val),
        'train_silhouette': float(silhouette_score(X_train, km_labels_train,
                                                    sample_size=min(10000, len(X_train)))) if len(set(km_labels_train)) > 1 else 0,
        'val_silhouette': float(sil_val),
        'val_ch': float(ch_val), 'val_db': float(db_val),
        'train_anomalies': int(n_anomalies_train),
        'val_anomalies': int(n_anomalies_val),
    }

    return km, iso, km_labels_train, iso_scores_train, iso_labels_train, metrics


def run_hdbscan(X_scaled):
    print('[HDBSCAN] Running HDBSCAN clustering...')
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=50,
        min_samples=10,
        metric='euclidean',
        cluster_selection_method='eom')
    labels = clusterer.fit_predict(X_scaled)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    print('  Clusters: {}, Noise: {} ({:.1f}%)'.format(
        n_clusters, n_noise, 100 * n_noise / len(labels)))

    if n_clusters > 1:
        non_noise = labels != -1
        if non_noise.sum() > 100:
            sil = silhouette_score(X_scaled[non_noise], labels[non_noise],
                                   sample_size=min(10000, non_noise.sum()))
            print('  Silhouette (excl. noise): {:.4f}'.format(sil))
        else:
            sil = 0
    else:
        sil = 0

    hdb_metrics = {
        'n_clusters': int(n_clusters),
        'n_noise': int(n_noise),
        'noise_pct': float(100 * n_noise / len(labels)),
        'silhouette': float(sil),
        'min_cluster_size': 50,
        'min_samples': 10,
    }
    return labels, clusterer, hdb_metrics


def calculate_risk(df, km_labels, iso_scores, iso_labels, hdb_labels):
    print('[RISK] Calculating flood risk scores...')
    risk_df = df.copy()
    risk_df['km_cluster'] = km_labels
    risk_df['anomaly_score'] = iso_scores
    risk_df['is_anomaly'] = (iso_labels == -1).astype(int)
    risk_df['hdb_cluster'] = hdb_labels

    def norm(x):
        mn, mx = x.min(), x.max()
        if mx - mn < 1e-8:
            return pd.Series(0.5, index=x.index)
        return (x - mn) / (mx - mn)

    if 'nivel_zscore' in risk_df.columns:
        nivel_risk = norm(risk_df['nivel_zscore'].clip(0, 5))
    elif 'NIVEL_INST' in risk_df.columns:
        nivel_risk = risk_df.groupby('estacao_sk')['NIVEL_INST'].transform(
            lambda x: x.rank(pct=True))
    else:
        nivel_risk = pd.Series(0.5, index=risk_df.index)

    taxa_col = 'taxa_subida_6h'
    if taxa_col in risk_df.columns:
        taxa_risk = norm(risk_df[taxa_col].clip(lower=0))
    else:
        taxa_risk = pd.Series(0, index=risk_df.index)

    precip_col = 'precip_accum_24h'
    if precip_col in risk_df.columns:
        precip_risk = norm(risk_df[precip_col].clip(lower=0))
    else:
        precip_risk = pd.Series(0, index=risk_df.index)

    soil_col = 'soil_saturacao_ratio'
    if soil_col in risk_df.columns:
        soil_risk = norm(risk_df[soil_col].fillna(0).clip(0, 1))
    else:
        soil_risk = pd.Series(0, index=risk_df.index)

    anomaly_risk = norm(-iso_scores)

    cluster_risk = pd.Series(0.5, index=risk_df.index)
    for c in risk_df['km_cluster'].unique():
        mask = risk_df['km_cluster'] == c
        c_mean = nivel_risk[mask].mean()
        cluster_risk[mask] = c_mean

    risk_df['risco_precipitacao'] = precip_risk
    risk_df['risco_hidrologico'] = nivel_risk
    risk_df['risco_solo'] = soil_risk
    risk_df['risco_anomalia'] = anomaly_risk

    risk_df['risco_flash_flood'] = (
        0.35 * precip_risk +
        0.25 * taxa_risk +
        0.20 * soil_risk +
        0.20 * anomaly_risk)

    risk_df['risco_river_flood'] = (
        0.35 * nivel_risk +
        0.20 * taxa_risk +
        0.15 * precip_risk +
        0.15 * soil_risk +
        0.15 * anomaly_risk)

    risk_df['risco_combinado'] = (
        0.5 * risk_df['risco_flash_flood'] +
        0.5 * risk_df['risco_river_flood'])

    risk_df['nivel_risco'] = pd.cut(
        risk_df['risco_combinado'],
        bins=[-0.01, 0.2, 0.4, 0.6, 0.8, 1.01],
        labels=[1, 2, 3, 4, 5]).astype(int)

    risk_map = {1: 'Muito Baixo', 2: 'Baixo', 3: 'Moderado', 4: 'Alto', 5: 'Muito Alto'}
    risk_df['categoria_risco'] = risk_df['nivel_risco'].map(risk_map)

    return risk_df


def save_results(conn, risk_df, all_metrics):
    print('[SAVE] Writing results to DB...')
    cur = conn.cursor()

    cur.execute("IF OBJECT_ID('ml.results') IS NOT NULL DROP TABLE ml.results")
    cur.execute("""
        CREATE TABLE ml.results (
            result_id BIGINT IDENTITY(1,1) PRIMARY KEY NONCLUSTERED,
            estacao_sk INT,
            tempo_sk INT,
            km_cluster INT,
            hdb_cluster INT,
            anomaly_score FLOAT,
            is_anomaly INT,
            risco_precipitacao FLOAT,
            risco_hidrologico FLOAT,
            risco_solo FLOAT,
            risco_anomalia FLOAT,
            risco_flash_flood FLOAT,
            risco_river_flood FLOAT,
            risco_combinado FLOAT,
            nivel_risco INT,
            categoria_risco NVARCHAR(20),
            datahora_registro DATETIME DEFAULT GETDATE()
        )
    """)
    cur.execute("CREATE CLUSTERED INDEX IX_ml_results ON ml.results (estacao_sk)")

    tempo_map = {}
    cur.execute("SELECT data_hora, tempo_sk FROM gold.dim_tempo")
    for r in cur.fetchall():
        tempo_map[r[0]] = r[1]

    batch = []
    for _, row in risk_df.iterrows():
        dt = row.get('data_hora')
        tsk = tempo_map.get(dt) if dt else None
        batch.append((
            int(row.get('estacao_sk', 0)),
            tsk,
            int(row.get('km_cluster', -1)),
            int(row.get('hdb_cluster', -1)),
            float(row.get('anomaly_score', 0)),
            int(row.get('is_anomaly', 0)),
            float(row.get('risco_precipitacao', 0)),
            float(row.get('risco_hidrologico', 0)),
            float(row.get('risco_solo', 0)),
            float(row.get('risco_anomalia', 0)),
            float(row.get('risco_flash_flood', 0)),
            float(row.get('risco_river_flood', 0)),
            float(row.get('risco_combinado', 0)),
            int(row.get('nivel_risco', 1)),
            str(row.get('categoria_risco', '')),
        ))

    insert_sql = """
        INSERT INTO ml.results
        (estacao_sk, tempo_sk, km_cluster, hdb_cluster, anomaly_score, is_anomaly,
         risco_precipitacao, risco_hidrologico, risco_solo, risco_anomalia,
         risco_flash_flood, risco_river_flood, risco_combinado,
         nivel_risco, categoria_risco)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    BATCH_SIZE = 5000
    for i in range(0, len(batch), BATCH_SIZE):
        chunk = batch[i:i + BATCH_SIZE]
        for row in chunk:
            cur.execute(insert_sql, *row)

    print('  ml.results: {} rows'.format(len(batch)))

    cur.execute("IF OBJECT_ID('ml.model_metrics') IS NOT NULL DROP TABLE ml.model_metrics")
    cur.execute("""
        CREATE TABLE ml.model_metrics (
            metric_id INT IDENTITY(1,1) PRIMARY KEY,
            algoritmo NVARCHAR(50),
            metricas NVARCHAR(MAX),
            data_registro DATETIME DEFAULT GETDATE()
        )
    """)
    for name, m in all_metrics.items():
        cur.execute("INSERT INTO ml.model_metrics (algoritmo, metricas) VALUES (?,?)",
                    name, json.dumps(m, default=str))

    print('  ml.model_metrics: {} algorithms'.format(len(all_metrics)))


def print_summary(risk_df):
    print()
    print('=' * 80)
    print('  FLOOD ML {} — SUMMARY'.format(MODEL_VERSION))
    print('=' * 80)
    print('  Stations: {} (natural river only)'.format(NATURAL_STATIONS))
    print('  Total rows: {:,}'.format(len(risk_df)))
    print()

    print('  Risk Distribution:')
    for cat in ['Muito Baixo', 'Baixo', 'Moderado', 'Alto', 'Muito Alto']:
        n = (risk_df['categoria_risco'] == cat).sum()
        pct = 100 * n / len(risk_df) if len(risk_df) > 0 else 0
        print('    {:15s}: {:>8,} ({:.1f}%)'.format(cat, n, pct))

    print()
    print('  Anomalies: {} ({:.1f}%)'.format(
        risk_df['is_anomaly'].sum(),
        100 * risk_df['is_anomaly'].mean()))

    if 'km_cluster' in risk_df.columns:
        print()
        print('  KMeans Cluster Distribution:')
        for c in sorted(risk_df['km_cluster'].unique()):
            n = (risk_df['km_cluster'] == c).sum()
            avg_risk = risk_df.loc[risk_df['km_cluster'] == c, 'risco_combinado'].mean()
            print('    Cluster {}: {:>8,} rows, avg_risk={:.3f}'.format(c, n, avg_risk))

    if 'hdb_cluster' in risk_df.columns:
        print()
        print('  HDBSCAN Cluster Distribution:')
        for c in sorted(risk_df['hdb_cluster'].unique()):
            label = 'Noise' if c == -1 else 'Cluster {}'.format(c)
            n = (risk_df['hdb_cluster'] == c).sum()
            print('    {}: {:>8,} rows'.format(label, n))

    print()
    print('  Per-Station Risk:')
    for sk in NATURAL_STATIONS:
        mask = risk_df['estacao_sk'] == sk
        if mask.sum() > 0:
            avg = risk_df.loc[mask, 'risco_combinado'].mean()
            high = (risk_df.loc[mask, 'nivel_risco'] >= 4).sum()
            print('    SK={}: avg_risk={:.3f}, high_risk_count={}'.format(sk, avg, high))


def main():
    start = datetime.now()
    print('=' * 80)
    print('  FLOOD ML {} — STARTING'.format(MODEL_VERSION))
    print('  Time: {}'.format(start))
    print('=' * 80)

    sample_size = DEFAULT_SAMPLE
    full_data = False
    no_save = False
    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--full':
            full_data = True
            sample_size = None
        elif arg == '--no-save':
            no_save = True
        elif arg == '--sample' and i + 1 < len(sys.argv[1:]):
            sample_size = int(sys.argv[i + 2])

    conn = get_conn()
    try:
        df = extract_features(conn, sample_size=None if full_data else sample_size)
        df = compute_lagged_features(df)
        features = select_features(df)
        features = drop_correlated(df, features, threshold=0.90)

        valid = df[features].replace([np.inf, -np.inf], np.nan).dropna()
        valid_idx = valid.index
        X = valid.values

        scaler = RobustScaler()
        X_scaled = scaler.fit_transform(X)

        print()
        print('[DATA] {} rows x {} features (after cleaning)'.format(X_scaled.shape[0], X_scaled.shape[1]))

        split_idx = int(0.8 * len(X_scaled))
        X_train, X_val = X_scaled[:split_idx], X_scaled[split_idx:]

        print()
        best_k, elbow_k, elbow_metrics = elbow_and_silhouette(X_train, MAX_K)
        km, iso, km_labels_train, iso_scores_train, iso_labels_train, km_metrics = \
            train_and_validate(X_train, X_val, best_k)

        km_labels_all = km.predict(X_scaled)
        iso_scores_all = iso.score_samples(X_scaled)
        iso_labels_all = iso.predict(X_scaled)

        print()
        hdb_labels, hdb_clusterer, hdb_metrics = run_hdbscan(X_scaled)

        risk_df = df.loc[valid_idx].copy()
        risk_df = calculate_risk(risk_df, km_labels_all, iso_scores_all, iso_labels_all, hdb_labels)

        all_metrics = {
            'KMeans': {**km_metrics, **elbow_metrics},
            'IsolationForest': {
                'contamination': 0.05,
                'n_estimators': 200,
                'train_anomalies': int((iso_labels_all == -1).sum()),
                'anomaly_pct': float(100 * (iso_labels_all == -1).mean()),
            },
            'HDBSCAN': hdb_metrics,
        }

        if not no_save:
            save_results(conn, risk_df, all_metrics)

        print_summary(risk_df)

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
