import math
import sys
import numpy as np
import pandas as pd
from scipy.spatial import KDTree
from preflood_config import DB_NAME, get_conn


def build_era5_mappings(conn):
    print("=== Mapeamento espacial: estacoes -> ERA5 ===")
    era5 = pd.read_sql(
        "SELECT estacao_sk, latitude, longitude FROM gold.dim_estacao "
        "WHERE sistema_origem = 'ERA5' AND latitude IS NOT NULL", conn)
    ipma = pd.read_sql(
        "SELECT estacao_sk, latitude, longitude FROM gold.dim_estacao "
        "WHERE sistema_origem = 'IPMA' AND latitude IS NOT NULL", conn)
    snirh = pd.read_sql(
        "SELECT estacao_sk, latitude, longitude FROM gold.dim_estacao "
        "WHERE sistema_origem = 'SNIRH' AND latitude IS NOT NULL", conn)

    if era5.empty:
        print("  ERRO: sem estacoes ERA5 com coordenadas.")
        return

    avg_lat = math.radians(era5['latitude'].mean())
    cos_lat = math.cos(avg_lat)
    era5_coords = np.column_stack([
        era5['latitude'].values * 111.0,
        era5['longitude'].values * 111.0 * cos_lat,
    ])
    tree = KDTree(era5_coords)

    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE ctl.map_spatial_proximity")

    total = 0
    for src_df, label in [(ipma, 'IPMA'), (snirh, 'SNIRH')]:
        if src_df.empty:
            print("  {}: sem estacoes".format(label))
            continue

        src_coords = np.column_stack([
            src_df['latitude'].values * 111.0,
            src_df['longitude'].values * 111.0 * cos_lat,
        ])
        k = min(3, len(era5))
        dists, idxs = tree.query(src_coords, k=k)

        rows = []
        for i in range(len(src_df)):
            for rank in range(k):
                eidx = idxs[i, rank]
                rows.append((
                    int(src_df.iloc[i]['estacao_sk']),
                    int(era5.iloc[eidx]['estacao_sk']),
                    float(dists[i, rank] * 1000),
                    1 if rank == 0 else 0,
                    rank + 1,
                ))

        cur.fast_executemany = True
        cur.executemany(
            "INSERT INTO ctl.map_spatial_proximity "
            "(source_station_sk, target_station_sk, distance_meters, is_nearest, rank_distance) "
            "VALUES (?,?,?,?,?)", rows)
        cur.fast_executemany = False
        total += len(rows)
        print("  {}: {} estacoes x {} vizinhos = {} mappings".format(label, len(src_df), k, len(rows)))

    cur.execute("SELECT COUNT(*) FROM ctl.map_spatial_proximity")
    print("  Total: {}".format(cur.fetchone()[0]))


def run():
    conn = get_conn()
    build_era5_mappings(conn)
    conn.close()


if __name__ == '__main__':
    run()
