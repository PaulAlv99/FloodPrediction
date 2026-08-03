import cdsapi
import os
import sys
import uuid
import zipfile
from datetime import datetime, timedelta
import pyodbc

CONN_STR = "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=PreFlood_DW;Trusted_Connection=yes;"
LANDING_DIR = r"C:\ProjetoDW\V4\Landing"
DELAY_DAYS = 7
SNIRH_START = "2010-06-06"
LAT_MIN, LAT_MAX = 40.04, 40.63
LON_MIN, LON_MAX = -8.89, -6.82

run_id = str(uuid.uuid4())
end_date = datetime.now() - timedelta(days=DELAY_DAYS)
start_date = datetime.strptime(SNIRH_START, "%Y-%m-%d")


def log_inicio(run_id, fase, passo):
    try:
        conn = pyodbc.connect(CONN_STR, autocommit=True)
        cursor = conn.cursor()
        cursor.execute("{CALL dbo.sp_ETL_LogInicio (?, ?, ?)}", run_id, fase, passo)
        conn.close()
    except Exception as e:
        print(f"WARNING log_inicio: {e}")


def log_fim(run_id, fase, passo, status, lidos, escritos, rejeitados, mensagem):
    try:
        conn = pyodbc.connect(CONN_STR, autocommit=True)
        cursor = conn.cursor()
        cursor.execute("{CALL dbo.sp_ETL_LogFim (?, ?, ?, ?, ?, ?, ?, ?)}",
                       run_id, fase, passo, status, lidos, escritos, rejeitados, mensagem)
        conn.close()
    except Exception as e:
        print(f"WARNING log_fim: {e}")


def log_erro(run_id, fase, passo, erro_numero, erro_mensagem, erro_severidade):
    try:
        conn = pyodbc.connect(CONN_STR, autocommit=True)
        cursor = conn.cursor()
        cursor.execute("{CALL dbo.sp_ETL_RegistarErro (?, ?, ?, ?, ?, ?)}",
                       run_id, fase, passo, erro_numero, erro_mensagem, erro_severidade)
        conn.close()
    except Exception as e:
        print(f"WARNING log_erro: {e}")


def get_pontos():
    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    query = """
        SELECT DISTINCT latitude, longitude FROM brz.ipma_est
        WHERE TRY_CAST(latitude AS FLOAT) IS NOT NULL
          AND TRY_CAST(latitude AS FLOAT) BETWEEN ? AND ?
          AND TRY_CAST(longitude AS FLOAT) BETWEEN ? AND ?
        UNION
        SELECT DISTINCT latitude, longitude FROM brz.snirh_est
        WHERE TRY_CAST(latitude AS FLOAT) IS NOT NULL
          AND TRY_CAST(latitude AS FLOAT) BETWEEN ? AND ?
          AND TRY_CAST(longitude AS FLOAT) BETWEEN ? AND ?
    """
    cursor.execute(query, LAT_MIN, LAT_MAX, LON_MIN, LON_MAX,
                   LAT_MIN, LAT_MAX, LON_MIN, LON_MAX)
    pontos = []
    seen = set()
    for row in cursor:
        lat = round(round(float(row[0]), 1), 1)
        lon = round(round(float(row[1]), 1), 1)
        key = (lat, lon)
        if key not in seen:
            seen.add(key)
            pontos.append((lat, lon))
    conn.close()
    return pontos


def download_point(client, lat, lon, date_start, date_end, output_file):
    request = {
        "variable": [
            "2m_temperature",
            "total_precipitation",
            "surface_pressure",
            "volumetric_soil_water_level_1",
            "volumetric_soil_water_level_2",
            "volumetric_soil_water_level_3",
            "volumetric_soil_water_level_4",
        ],
        "location": {"latitude": lat, "longitude": lon},
        "date": [f"{date_start}/{date_end}"],
        "data_format": "csv",
    }
    client.retrieve("reanalysis-era5-land-timeseries", request, output_file)


def parse_and_insert(run_dir, run_id):
    conn = pyodbc.connect(CONN_STR, autocommit=False)
    conn.add_output_converter(-155, lambda v: v.decode("utf-8"))
    cursor = conn.cursor()
    cursor.fast_executemany = True
    insert_sql = """
        INSERT INTO brz.era5_obs
        (data_hora, latitude, longitude, temperatura_2m, precipitacao,
         solo_l1, solo_l2, solo_l3, solo_l4, pressao_superf, _arquivo, _run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    run_uuid = uuid.UUID(run_id)
    BATCH_SIZE = 5000
    total_rows = 0
    batch = []

    point_data = {}

    for fname in os.listdir(run_dir):
        if not fname.startswith("era5_") or not fname.endswith(".csv"):
            continue
        fpath = os.path.join(run_dir, fname)

        try:
            zf = zipfile.ZipFile(fpath, "r")
        except zipfile.BadZipFile:
            print(f"WARNING: Not a valid ZIP: {fname}")
            continue

        with zf:
            for entry in zf.namelist():
                if not entry.endswith(".csv"):
                    continue
                with zf.open(entry) as csvf:
                    lines = [l.decode("utf-8") for l in csvf.readlines()]

                if len(lines) < 2:
                    continue

                header = lines[0].strip().lower()
                headers = [h.strip() for h in header.split(",")]

                time_idx = _col_idx(headers, ["valid_time", "time"])
                lat_idx = _col_idx(headers, ["latitude"])
                lon_idx = _col_idx(headers, ["longitude"])
                t2m_idx = _col_idx(headers, ["t2m"])
                sp_idx = _col_idx(headers, ["sp"])
                tp_idx = _col_idx(headers, ["tp"])
                l1_idx = _col_idx(headers, ["swvl1", "soil_water_level_1", "volumetric_soil_water_level_1"])
                l2_idx = _col_idx(headers, ["swvl2", "soil_water_level_2", "volumetric_soil_water_level_2"])
                l3_idx = _col_idx(headers, ["swvl3", "soil_water_level_3", "volumetric_soil_water_level_3"])
                l4_idx = _col_idx(headers, ["swvl4", "soil_water_level_4", "volumetric_soil_water_level_4"])

                if time_idx is None:
                    print(f"WARNING: No time column in {entry}")
                    continue

                for ln in lines[1:]:
                    ln = ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    cols = [c.strip() for c in ln.split(",")]

                    dt_val = _safe(cols, time_idx)
                    if not dt_val:
                        continue

                    lat_val = _safe(cols, lat_idx) or ""
                    lon_val = _safe(cols, lon_idx) or ""
                    key = (dt_val, lat_val, lon_val)

                    if key not in point_data:
                        point_data[key] = {
                            "dt": dt_val, "lat": lat_val, "lon": lon_val,
                            "t2m": None, "tp": None, "sp": None,
                            "l1": None, "l2": None, "l3": None, "l4": None,
                            "arquivo": fpath,
                        }

                    rec = point_data[key]
                    if t2m_idx is not None:
                        rec["t2m"] = _safe(cols, t2m_idx) or rec["t2m"]
                    if sp_idx is not None:
                        rec["sp"] = _safe(cols, sp_idx) or rec["sp"]
                    if tp_idx is not None:
                        rec["tp"] = _safe(cols, tp_idx) or rec["tp"]
                    if l1_idx is not None:
                        rec["l1"] = _safe(cols, l1_idx) or rec["l1"]
                    if l2_idx is not None:
                        rec["l2"] = _safe(cols, l2_idx) or rec["l2"]
                    if l3_idx is not None:
                        rec["l3"] = _safe(cols, l3_idx) or rec["l3"]
                    if l4_idx is not None:
                        rec["l4"] = _safe(cols, l4_idx) or rec["l4"]

    for rec in point_data.values():
        batch.append((
            rec["dt"], rec["lat"], rec["lon"],
            rec["t2m"], rec["tp"],
            rec["l1"], rec["l2"], rec["l3"], rec["l4"],
            rec["sp"], rec["arquivo"], run_uuid,
        ))
        if len(batch) >= BATCH_SIZE:
            cursor.executemany(insert_sql, batch)
            conn.commit()
            total_rows += len(batch)
            print(f"    {total_rows:,} rows...", flush=True)
            batch = []

    if batch:
        cursor.executemany(insert_sql, batch)
        conn.commit()
        total_rows += len(batch)

    conn.close()
    return total_rows


def _col_idx(headers, names):
    for n in names:
        for i, h in enumerate(headers):
            if n in h:
                return i
    return None


def _safe(cols, idx):
    if idx is None or idx < 0 or idx >= len(cols):
        return None
    v = cols[idx].strip()
    return v if v else None


if __name__ == "__main__":
    try:
        print("=" * 70)
        print(f"ERA5 Bronze — Historical Download")
        print(f"  RunId:  {run_id}")
        print(f"  Range:  {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print(f"  Span:   {(end_date - start_date).days} days ({(end_date - start_date).days // 365} years)")
        print("=" * 70)
        log_inicio(run_id, "EXTRACAO", "API->Bronze ERA5")

        era5_dir = os.path.join(LANDING_DIR, "ERA5")
        os.makedirs(era5_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(era5_dir, timestamp)
        os.makedirs(run_dir, exist_ok=True)

        pontos = get_pontos()
        print(f"Found {len(pontos)} coordinate points")

        if len(pontos) == 0:
            raise Exception("No station coordinates found in Bronze tables")

        d_start = start_date.strftime("%Y-%m-%d")
        d_end = end_date.strftime("%Y-%m-%d")
        print(f"Downloading full range: {d_start} to {d_end}")
        print()

        client = cdsapi.Client()
        total_downloaded = 0
        failed = 0

        for pt_idx, (lat, lon) in enumerate(pontos):
            fname = f"era5_pt{pt_idx}_{lat}_{lon}_{d_start}_{d_end}.csv"
            out_file = os.path.join(run_dir, fname)
            label = f"[{pt_idx+1}/{len(pontos)}] ({lat},{lon}) {d_start} to {d_end}"
            print(f"  {label} ... ", end="", flush=True)
            try:
                download_point(client, lat, lon, d_start, d_end, out_file)
                total_downloaded += 1
                print("OK")
            except Exception as e:
                failed += 1
                print(f"ERROR: {e}")

        print(f"\nDownloaded: {total_downloaded}/{total_downloaded+failed} files ({failed} failed)")

        print("\nParsing and inserting into Bronze...")
        total_rows = parse_and_insert(run_dir, run_id)
        print(f"Inserted {total_rows:,} rows into brz.era5_obs")

        log_fim(run_id, "EXTRACAO", "API->Bronze ERA5", "OK", total_rows, total_rows, 0, None)
        print("Done.")

    except Exception as e:
        print(f"FATAL: {e}")
        try:
            log_erro(run_id, "EXTRACAO", "API->Bronze ERA5", 0, str(e), 0)
        except:
            pass
        sys.exit(1)
