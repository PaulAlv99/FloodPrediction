import argparse
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from preflood_config import DB_NAME, get_conn, NATURAL_STATIONS


def _nullify(val):
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, pd.Timestamp) and pd.isna(val):
        return None
    return val


def _fetch_nivel_inst(conn, estacao_sk: int) -> pd.DataFrame:
    sql = """
        SELECT t.data_hora, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE f.estacao_sk = ?
          AND p.parametro_codigo = '1843'
          AND f.valor IS NOT NULL
        ORDER BY t.data_hora ASC
    """
    return pd.read_sql(sql, conn, params=[estacao_sk])


def _fetch_p95(conn, estacao_sk: int) -> float | None:
    sql = """
        SELECT p95
        FROM ctl.ml_risk_thresholds
        WHERE estacao_sk = ?
          AND target_parametro = 'NIVEL_INST'
    """
    df = pd.read_sql(sql, conn, params=[estacao_sk])
    if df.empty:
        return None
    return float(df.iloc[0]["p95"])


def _fetch_precip_series(conn, estacao_sk: int) -> pd.DataFrame:
    sql = """
        SELECT t.data_hora, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE f.estacao_sk = ?
          AND p.parametro_codigo = 'prec'
          AND f.valor IS NOT NULL
        ORDER BY t.data_hora ASC
    """
    return pd.read_sql(sql, conn, params=[estacao_sk])


def _fetch_soil_series(conn, estacao_sk: int) -> pd.DataFrame:
    sql = """
        SELECT t.data_hora, f.valor
        FROM gold.fact_medicao f
        JOIN gold.dim_tempo t ON f.tempo_sk = t.tempo_sk
        JOIN gold.dim_parametro p ON f.parametro_sk = p.parametro_sk
        WHERE f.estacao_sk = ?
          AND p.parametro_codigo = 'swvl1'
          AND f.valor IS NOT NULL
        ORDER BY t.data_hora ASC
    """
    return pd.read_sql(sql, conn, params=[estacao_sk])


def _compute_antecedent_precip(precip_df: pd.DataFrame, ref_ts: datetime,
                                hours: int) -> float | None:
    if precip_df.empty:
        return None
    start = ref_ts - timedelta(hours=hours)
    mask = (precip_df["data_hora"] >= start) & (precip_df["data_hora"] < ref_ts)
    total = precip_df.loc[mask, "valor"].astype(float).sum()
    return round(float(total), 4) if not np.isnan(total) else None


def _compute_soil_moisture(soil_df: pd.DataFrame,
                            ref_ts: datetime) -> float | None:
    if soil_df.empty:
        return None
    mask = soil_df["data_hora"] <= ref_ts
    subset = soil_df.loc[mask]
    if subset.empty:
        return None
    return round(float(subset.iloc[-1]["valor"]), 4)


def detect_events(df: pd.DataFrame, p95: float,
                  min_duration: int) -> list[dict]:
    if df.empty:
        return []

    events: list[dict] = []
    event_start = None
    event_values: list[float] = []
    event_times: list[datetime] = []

    for _, row in df.iterrows():
        ts = row["data_hora"] if isinstance(row["data_hora"], datetime) \
            else pd.Timestamp(row["data_hora"]).to_pydatetime()
        val = float(row["valor"])

        if val > p95:
            if event_start is None:
                event_start = ts
                event_values = [val]
                event_times = [ts]
            else:
                event_values.append(val)
                event_times.append(ts)
        else:
            if event_start is not None:
                duration_h = _compute_duration(event_times)
                if duration_h >= min_duration:
                    events.append(_build_event(
                        event_times, event_values,
                    ))
                event_start = None
                event_values = []
                event_times = []

    if event_start is not None:
        duration_h = _compute_duration(event_times)
        if duration_h >= min_duration:
            events.append(_build_event(event_times, event_values))

    return events


def _compute_duration(times: list[datetime]) -> int:
    if len(times) < 2:
        return 0
    delta = times[-1] - times[0]
    return max(1, int(delta.total_seconds() / 3600))


def _build_event(times: list[datetime], values: list[float]) -> dict:
    peak_idx = max(range(len(values)), key=lambda i: values[i])
    start_ts = times[0]
    peak_ts = times[peak_idx]
    end_ts = times[-1]
    duration_h = _compute_duration(times)

    rise_rate = None
    if peak_ts > start_ts and peak_idx > 0:
        hours_to_peak = (peak_ts - start_ts).total_seconds() / 3600
        if hours_to_peak > 0:
            rise_rate = round((values[peak_idx] - values[0]) / hours_to_peak, 4)

    return {
        "start_ts": start_ts,
        "peak_ts": peak_ts,
        "end_ts": end_ts,
        "duration_hours": duration_h,
        "peak_value": round(values[peak_idx], 4),
        "rise_rate": rise_rate,
        "start_value": round(values[0], 4),
        "end_value": round(values[-1], 4),
    }


def save_events_batch(conn, estacao_sk: int, events: list[dict],
                      precip_df: pd.DataFrame, soil_df: pd.DataFrame,
                      p95: float) -> int:
    sql = """
        INSERT INTO ml.ew_flood_events
            (estacao_sk, event_start, event_peak, event_end,
             duration_hours, peak_value, rise_rate,
             start_value, end_value,
             antecedent_precip_6h, antecedent_precip_24h,
             antecedent_soil_moisture,
             threshold_p95)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    cursor = conn.cursor()
    count = 0
    for ev in events:
        precip_6h = _compute_antecedent_precip(precip_df, ev["start_ts"], 6)
        precip_24h = _compute_antecedent_precip(precip_df, ev["start_ts"], 24)
        soil_m = _compute_soil_moisture(soil_df, ev["start_ts"])

        cursor.execute(
            sql,
            estacao_sk,
            ev["start_ts"],
            ev["peak_ts"],
            ev["end_ts"],
            ev["duration_hours"],
            ev["peak_value"],
            _nullify(ev["rise_rate"]),
            ev["start_value"],
            ev["end_value"],
            _nullify(precip_6h),
            _nullify(precip_24h),
            _nullify(soil_m),
            _nullify(p95),
        )
        count += 1
        print(
            f"    Event {ev['start_ts']} -> {ev['end_ts']}  "
            f"peak={ev['peak_value']:.3f}  dur={ev['duration_hours']}h  "
            f"rise={ev['rise_rate']}  "
            f"precip6h={precip_6h}  precip24h={precip_24h}  "
            f"soil={soil_m}"
        )
    conn.commit()
    return count


def main():
    parser = argparse.ArgumentParser(
        description="PreFlood_DW — Compute historical flood events",
    )
    parser.add_argument(
        "--full", action="store_true",
    )
    parser.add_argument(
        "--min-duration", type=int, default=2,
    )
    args = parser.parse_args()

    conn = get_conn()
    total_inserted = 0

    try:
        for sk in NATURAL_STATIONS:
            print(f"\n=== Station SK={sk} ===")

            p95 = _fetch_p95(conn, sk)
            if p95 is None:
                print(f"  No P95 threshold found — skipping.")
                continue
            print(f"  P95 threshold: {p95:.3f}")

            df = _fetch_nivel_inst(conn, sk)
            if df.empty:
                print("  No NIVEL_INST data — skipping.")
                continue
            print(f"  Loaded {len(df)} NIVEL_INST records")

            precip_df = _fetch_precip_series(conn, sk)
            soil_df = _fetch_soil_series(conn, sk)
            print(f"  Precip: {len(precip_df)} rows, Soil: {len(soil_df)} rows")

            events = detect_events(df, p95, args.min_duration)
            print(f"  Detected {len(events)} flood event(s)")

            if events:
                n = save_events_batch(conn, sk, events, precip_df, soil_df, p95)
                total_inserted += n
    finally:
        conn.close()

    print(f"\nTotal events inserted: {total_inserted}")


if __name__ == "__main__":
    main()
