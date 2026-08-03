import os
import sys
import time
import uuid
import zipfile
import argparse
from datetime import datetime, timedelta

ERA5_VARIABLES = [
    "2m_temperature",
    "total_precipitation",
    "volumetric_soil_water_level_1",
    "volumetric_soil_water_level_2",
    "volumetric_soil_water_level_3",
    "volumetric_soil_water_level_4",
    "surface_pressure",
]

DATASET_NAME = "reanalysis-era5-land-timeseries"

ERA5_COL_MAP = {
    't2m': 'temperatura_2m',
    'tp': 'precipitacao',
    'swvl1': 'solo_l1',
    'swvl2': 'solo_l2',
    'swvl3': 'solo_l3',
    'swvl4': 'solo_l4',
    'sp': 'pressao_superf',
}


def parse_args():
    p = argparse.ArgumentParser(description='Bronze ERA5 download + DB insert')
    p.add_argument('--conn-str', required=False,
                   default='DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=PreFlood_DW;Trusted_Connection=yes;')
    p.add_argument('--landing-dir', required=False,
                   default=r'C:\ProjetoDW\V4\Landing')
    p.add_argument('--start-date', required=False, default=None)
    p.add_argument('--end-date', required=False, default=None)
    p.add_argument('--delay-dias', type=int, default=7)
    p.add_argument('--lat-min', type=float, default=39.90)
    p.add_argument('--lat-max', type=float, default=40.45)
    p.add_argument('--lon-min', type=float, default=-8.55)
    p.add_argument('--lon-max', type=float, default=-7.85)
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--no-download', action='store_true')
    return p.parse_args()


def get_locations_from_bronze(conn_str, lat_min, lat_max, lon_min, lon_max):
    import pyodbc

    conn = pyodbc.connect(conn_str, autocommit=True)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT lat, lon FROM (
            SELECT TRY_CAST(latitude AS FLOAT) AS lat,
                   TRY_CAST(longitude AS FLOAT) AS lon
            FROM brz.brz_ipma_est
            WHERE latitude IS NOT NULL AND latitude <> ''
            UNION ALL
            SELECT TRY_CAST(latitude AS FLOAT),
                   TRY_CAST(longitude AS FLOAT)
            FROM brz.brz_snirh_est
            WHERE latitude IS NOT NULL AND latitude <> ''
        ) x
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND lat BETWEEN ? AND ?
          AND lon BETWEEN ? AND ?
    """, lat_min, lat_max, lon_min, lon_max)

    seen = set()
    locations = []
    for row in cur.fetchall():
        lat = round(float(row[0]), 1)
        lon = round(float(row[1]), 1)
        key = (lat, lon)
        if key in seen:
            continue
        seen.add(key)
        locations.append({
            'label': 'PT_{}_{}'.format(lat, lon).replace('.', 'p').replace('-', 'm'),
            'lat': lat,
            'lon': lon,
        })

    conn.close()
    return locations


def download_era5(locations, start_date, end_date, out_dir):
    import cdsapi

    cds = cdsapi.Client(quiet=False)
    date_range_str = '{}/{}'.format(
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d'))
    range_tag = '{}_{}'.format(
        start_date.strftime('%Y%m%d'),
        end_date.strftime('%Y%m%d'))
    loc_results = []

    for li, loc in enumerate(locations, 1):
        lat = loc['lat']
        lon = loc['lon']
        label = loc['label']

        extract_dir = os.path.join(out_dir, 'era5_{}_{}'.format(label, range_tag))
        zip_path = os.path.join(out_dir, 'era5_{}_{}.zip'.format(label, range_tag))

        if os.path.isdir(extract_dir) and os.listdir(extract_dir):
            print('  [{}/{}] SKIP {} (ja extraido)'.format(li, len(locations), label))
            csv_files = [os.path.join(extract_dir, f)
                         for f in os.listdir(extract_dir) if f.endswith('.csv')]
            loc_results.append((label, csv_files))
            continue

        print('  [{}/{}] {} ({}, {}) [{}]...'.format(
            li, len(locations), label, lat, lon, date_range_str))

        request = {
            'variable': ERA5_VARIABLES,
            'location': {'latitude': lat, 'longitude': lon},
            'date': date_range_str,
            'data_format': 'csv',
        }

        try:
            cds.retrieve(DATASET_NAME, request, zip_path)
            size_kb = os.path.getsize(zip_path) / 1024
            print('    Downloaded: {:.1f} KB'.format(size_kb))

            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
                extracted = zf.namelist()
            print('    Extracted: {} files'.format(len(extracted)))

            os.remove(zip_path)
            print('    ZIP removed')

            csv_files = [os.path.join(extract_dir, f)
                         for f in os.listdir(extract_dir) if f.endswith('.csv')]
            loc_results.append((label, csv_files))

        except Exception as e:
            print('    ERRO: {}'.format(e))
            if os.path.exists(zip_path):
                os.remove(zip_path)

        time.sleep(0.5)

    return loc_results


def merge_location_csvs(label, csv_files):
    merged = {}

    for csv_path in csv_files:
        fname = os.path.basename(csv_path)
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        header = None
        col_idx = {}
        header_line_idx = -1
        for li2, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = [p.strip() for p in stripped.split(',')]
            lower_parts = [p.lower() for p in parts]

            has_time = 'valid_time' in lower_parts or 'time' in lower_parts
            if has_time or any(k in lp for k in ERA5_COL_MAP for lp in lower_parts):
                header = parts
                header_line_idx = li2
                for ci, col_name in enumerate(parts):
                    cl = col_name.lower()
                    if cl == 'valid_time' or cl == 'time':
                        col_idx['time'] = ci
                    elif cl == 'latitude' or cl == 'lat':
                        col_idx['lat'] = ci
                    elif cl == 'longitude' or cl == 'lon':
                        col_idx['lon'] = ci
                    elif cl in ERA5_COL_MAP:
                        col_idx[ERA5_COL_MAP[cl]] = ci
                break

        if header is None or 'time' not in col_idx:
            print('    AVISO: sem header em {}'.format(fname))
            continue

        row_count = 0
        for line in lines[header_line_idx + 1:]:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = [p.strip() for p in stripped.split(',')]
            if len(parts) < 2:
                continue

            dt_val = parts[col_idx['time']] if 'time' in col_idx else ''
            if not dt_val:
                continue

            lat_val = parts[col_idx['lat']] if 'lat' in col_idx else ''
            lon_val = parts[col_idx['lon']] if 'lon' in col_idx else ''

            key = dt_val

            if key not in merged:
                merged[key] = {
                    'data_hora': dt_val,
                    'latitude': lat_val,
                    'longitude': lon_val,
                    '_arquivo': fname,
                }

            for bronze_col in ['temperatura_2m', 'precipitacao',
                               'solo_l1', 'solo_l2', 'solo_l3', 'solo_l4',
                               'pressao_superf']:
                if bronze_col in col_idx and bronze_col not in merged[key]:
                    idx = col_idx[bronze_col]
                    if idx < len(parts) and parts[idx]:
                        merged[key][bronze_col] = parts[idx]

            row_count += 1

        print('    {}: {} rows'.format(fname, row_count))

    rows = list(merged.values())
    rows.sort(key=lambda r: r['data_hora'])
    return rows


def insert_bronze(conn_str, all_rows, run_id):
    import pyodbc

    if not all_rows:
        return 0

    conn = pyodbc.connect(conn_str, autocommit=False)
    total = 0
    try:
        cur = conn.cursor()
        sql = """INSERT INTO brz.era5_obs
                 (data_hora, latitude, longitude,
                  temperatura_2m, precipitacao,
                  solo_l1, solo_l2, solo_l3, solo_l4,
                  pressao_superf, _arquivo, _run_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

        batch = []
        for row in all_rows:
            batch.append((
                row.get('data_hora'),
                row.get('latitude'),
                row.get('longitude'),
                row.get('temperatura_2m'),
                row.get('precipitacao'),
                row.get('solo_l1'),
                row.get('solo_l2'),
                row.get('solo_l3'),
                row.get('solo_l4'),
                row.get('pressao_superf'),
                row.get('_arquivo', ''),
                run_id,
            ))
            if len(batch) >= 100:
                cur.executemany(sql, batch)
                total += len(batch)
                batch = []

        if batch:
            cur.executemany(sql, batch)
            total += len(batch)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return total


def log_execution(conn_str, package, task, run_id, status, rows, error, start_time):
    import pyodbc
    try:
        conn = pyodbc.connect(conn_str, autocommit=True)
        cur = conn.cursor()
        end_time = datetime.now()
        duration = int((end_time - start_time).total_seconds())
        cur.execute("""
            INSERT INTO ctl.execution_log
            (package_name, task_name, run_id, status, rows_processed,
             error_message, start_time, end_time, duration_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            package, task, run_id, status, rows,
            error, start_time, end_time, duration)
        conn.close()
    except Exception as e:
        print('  AVISO log_execution: {}'.format(e))


def main():
    args = parse_args()
    run_id = str(uuid.uuid4())
    start_time = datetime.now()
    conn_str = args.conn_str

    today = datetime.now()
    if args.start_date and args.start_date.strip():
        start_date = datetime.strptime(args.start_date.strip(), '%Y-%m-%d')
    else:
        start_date = today - timedelta(days=365)
    if args.end_date and args.end_date.strip():
        end_date = datetime.strptime(args.end_date.strip(), '%Y-%m-%d')
    else:
        end_date = today - timedelta(days=args.delay_dias)

    days_in_range = (end_date - start_date).days + 1

    print('=== Bronze ERA5 ===')
    print('RunId: {}'.format(run_id))
    print('Date range: {} to {} ({} days)'.format(
        start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'),
        days_in_range))
    print('Landing dir: {}'.format(args.landing_dir))
    print('Bounding box: lat [{}, {}] lon [{}, {}]'.format(
        args.lat_min, args.lat_max, args.lon_min, args.lon_max))

    try:
        locations = get_locations_from_bronze(
            conn_str, args.lat_min, args.lat_max, args.lon_min, args.lon_max)

        if not locations:
            print('ERRO: nenhuma coordenada encontrada nas tabelas brz '
                  '(brz_ipma_est + brz_snirh_est) para a bounding box.')
            log_execution(conn_str, 'Pkg_Bronze', 'EPT_BronzeERA5',
                          run_id, 'Failed', 0,
                          'No coordinates found in Bronze tables for bounding box',
                          start_time)
            sys.exit(1)

        if args.limit:
            locations = locations[:args.limit]
        print('Locations: {} (deduplicated, rounded to 0.1)'.format(len(locations)))
        for loc in locations:
            print('  {} ({}, {})'.format(loc['label'], loc['lat'], loc['lon']))

        era5_dir = os.path.join(args.landing_dir, 'ERA5')
        os.makedirs(era5_dir, exist_ok=True)

        loc_results = []
        if not args.no_download:
            print('\n--- Download ---')
            loc_results = download_era5(locations, start_date, end_date, era5_dir)
        else:
            print('\n--- Parse existing extracted dirs ---')
            range_tag = '{}_{}'.format(
                start_date.strftime('%Y%m%d'),
                end_date.strftime('%Y%m%d'))
            for loc in locations:
                extract_dir = os.path.join(era5_dir, 'era5_{}_{}'.format(
                    loc['label'], range_tag))
                if os.path.isdir(extract_dir):
                    csv_files = [os.path.join(extract_dir, f)
                                 for f in os.listdir(extract_dir) if f.endswith('.csv')]
                    if csv_files:
                        loc_results.append((loc['label'], csv_files))

        print('\n--- Merge + Insert Bronze ---')
        all_rows = []
        for label, csv_files in loc_results:
            print('  Location: {} ({} CSVs)'.format(label, len(csv_files)))
            rows = merge_location_csvs(label, csv_files)
            print('    Merged: {} rows'.format(len(rows)))
            all_rows.extend(rows)

        print('\nTotal rows to insert: {}'.format(len(all_rows)))

        inserted = 0
        if all_rows:
            inserted = insert_bronze(conn_str, all_rows, run_id)
            print('Inserted: {}'.format(inserted))

        log_execution(conn_str, 'Pkg_Bronze', 'EPT_BronzeERA5',
                      run_id, 'Success', inserted, None, start_time)

        print('\n=== Bronze ERA5 complete ===')
        print('Rows: {}'.format(inserted))
        print('Duration: {}s'.format(int((datetime.now() - start_time).total_seconds())))

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print('ERRO FATAL: {}'.format(tb))
        log_execution(conn_str, 'Pkg_Bronze', 'EPT_BronzeERA5',
                      run_id, 'Failed', 0, str(e)[:4000], start_time)
        sys.exit(1)


if __name__ == '__main__':
    main()
