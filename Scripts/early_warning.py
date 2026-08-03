import argparse
import sys
from datetime import datetime, timedelta

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


class EarlyWarningEngine:

    def __init__(self, conn=None, dry_run: bool = False):
        self.dry_run = dry_run
        self._owns_conn = conn is None
        self.conn = conn or get_conn()
        self.detections: list[dict] = []

    def evaluate_station(self, estacao_sk: int) -> list[dict]:
        self.detections = []

        p_score = self.check_percentile_thresholds(estacao_sk)
        s_score = self.check_sequence_anomalies(estacao_sk)
        combined = self.compute_combined_score(p_score, s_score, estacao_sk)
        lead_time = self.estimate_lead_time(estacao_sk)

        if combined is not None and combined.get("combined_score", 0) > 0:
            detection = {
                "estacao_sk": estacao_sk,
                "detection_ts": datetime.now(),
                "layer1_percentile_score": _nullify(p_score.get("max_score", 0)) if p_score else None,
                "layer1_details": _nullify(p_score.get("details")) if p_score else None,
                "layer2_sequence_score": _nullify(s_score.get("score", 0)) if s_score else None,
                "layer2_details": _nullify(s_score.get("details")) if s_score else None,
                "layer3_combined_score": _nullify(combined.get("combined_score")),
                "lead_time_hours": _nullify(lead_time),
            }
            self.detections.append(detection)

        return self.detections

    def check_percentile_thresholds(self, estacao_sk: int) -> dict | None:
        sql = """
            SELECT t.metric_name, t.warning_level AS p90, t.alert_level AS p95, t.critical_level AS p99,
                   m.valor AS current_value,
                   m.data_hora
            FROM ctl.ew_thresholds t
            JOIN (
                SELECT TOP 1 dt.data_hora, fm.valor
                FROM gold.fact_medicao fm
                JOIN gold.dim_tempo dt ON fm.tempo_sk = dt.tempo_sk
                JOIN gold.dim_parametro dp ON fm.parametro_sk = dp.parametro_sk
                WHERE fm.estacao_sk = ?
                  AND dp.parametro_codigo = '1843'
                  AND fm.valor IS NOT NULL
                ORDER BY dt.data_hora DESC
            ) m ON 1=1
            WHERE t.estacao_sk = ?
              AND t.metric_name = 'NIVEL_INST'
        """
        try:
            df = pd.read_sql(sql, self.conn, params=[estacao_sk, estacao_sk])
        except Exception:
            return None

        if df.empty:
            return None

        row = df.iloc[0]
        current = float(row["current_value"])
        p90 = float(row["p90"])
        p95 = float(row["p95"])
        p99 = float(row["p99"])

        score = 0.0
        details_parts = []

        if current >= p99:
            score = 1.0
            details_parts.append(f"NIVEL_INST {current:.2f} >= P99 ({p99:.2f})")
        elif current >= p95:
            score = 0.75
            details_parts.append(f"NIVEL_INST {current:.2f} >= P95 ({p95:.2f})")
        elif current >= p90:
            score = 0.5
            details_parts.append(f"NIVEL_INST {current:.2f} >= P90 ({p90:.2f})")

        if not details_parts:
            return {"max_score": 0.0, "details": None}

        return {
            "max_score": score,
            "details": "; ".join(details_parts),
        }

    def check_sequence_anomalies(self, estacao_sk: int) -> dict | None:
        sql = """
            SELECT TOP 24 dt.data_hora, fm.valor
            FROM gold.fact_medicao fm
            JOIN gold.dim_tempo dt ON fm.tempo_sk = dt.tempo_sk
            JOIN gold.dim_parametro dp ON fm.parametro_sk = dp.parametro_sk
            WHERE fm.estacao_sk = ?
              AND dp.parametro_codigo = '1843'
              AND fm.valor IS NOT NULL
              AND dt.data_hora >= DATEADD(HOUR, -12, SYSDATETIME())
            ORDER BY dt.data_hora ASC
        """
        try:
            df = pd.read_sql(sql, self.conn, params=[estacao_sk])
        except Exception:
            return None

        if df.empty or len(df) < 3:
            return {"score": 0.0, "details": None}

        values = df["valor"].astype(float).values
        score = 0.0
        details_parts = []

        consecutive_rises = 0
        for i in range(1, len(values)):
            if values[i] > values[i - 1]:
                consecutive_rises += 1
            else:
                consecutive_rises = 0

        if consecutive_rises >= 6:
            score += 0.4
            details_parts.append(f"Rising {consecutive_rises}h consecutive")
        elif consecutive_rises >= 4:
            score += 0.2
            details_parts.append(f"Rising {consecutive_rises}h consecutive")
        elif consecutive_rises >= 2:
            score += 0.1
            details_parts.append(f"Rising {consecutive_rises}h consecutive")

        if len(values) >= 3:
            recent = values[-6:] if len(values) >= 6 else values
            diffs = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
            accel = [diffs[i] - diffs[i - 1] for i in range(1, len(diffs))]
            if accel and sum(a > 0 for a in accel) / len(accel) > 0.6:
                score += 0.3
                details_parts.append("Acceleration detected")

        sql_coincident = """
            SELECT COUNT(*) AS cnt
            FROM gold.fact_medicao fm
            JOIN gold.dim_tempo dt ON fm.tempo_sk = dt.tempo_sk
            JOIN gold.dim_parametro dp ON fm.parametro_sk = dp.parametro_sk
            JOIN ctl.ew_thresholds t
              ON fm.estacao_sk = t.estacao_sk
              AND t.metric_name = 'NIVEL_INST'
            WHERE fm.estacao_sk IN (?, ?, ?, ?)
              AND dp.parametro_codigo = '1843'
              AND fm.valor IS NOT NULL
              AND dt.data_hora >= DATEADD(HOUR, -1, SYSDATETIME())
              AND fm.valor >= t.warning_level
        """
        try:
            df_coinc = pd.read_sql(
                sql_coincident, self.conn,
                params=NATURAL_STATIONS,
            )
            coincident_count = int(df_coinc.iloc[0]["cnt"])
            if coincident_count >= 3:
                score += 0.3
                details_parts.append(f"Coincident triggers at {coincident_count} stations")
            elif coincident_count >= 2:
                score += 0.15
                details_parts.append(f"Coincident triggers at {coincident_count} stations")
        except Exception:
            pass

        score = min(score, 1.0)
        if not details_parts:
            return {"score": 0.0, "details": None}

        return {
            "score": score,
            "details": "; ".join(details_parts),
        }

    def compute_combined_score(
        self,
        p_score: dict | None,
        s_score: dict | None,
        estacao_sk: int,
    ) -> dict | None:
        pct = p_score.get("max_score", 0) if p_score else 0.0
        seq = s_score.get("score", 0) if s_score else 0.0

        ml_score = 0.0
        sql_ml = """
            SELECT TOP 1 CAST(nivel_risco AS FLOAT) / 5.0 AS risk_score
            FROM ml.flood_risk_current
            WHERE estacao_sk = ?
            ORDER BY data_atualizacao DESC
        """
        try:
            df_ml = pd.read_sql(sql_ml, self.conn, params=[estacao_sk])
            if not df_ml.empty:
                ml_score = float(df_ml.iloc[0]["risk_score"])
        except Exception:
            pass

        combined = 0.40 * pct + 0.40 * seq + 0.20 * ml_score

        return {
            "combined_score": round(combined, 4),
            "pct_component": round(pct, 4),
            "seq_component": round(seq, 4),
            "ml_component": round(ml_score, 4),
        }

    def estimate_lead_time(self, estacao_sk: int) -> float | None:
        sql_current = """
            SELECT TOP 6 dt.data_hora, fm.valor
            FROM gold.fact_medicao fm
            JOIN gold.dim_tempo dt ON fm.tempo_sk = dt.tempo_sk
            JOIN gold.dim_parametro dp ON fm.parametro_sk = dp.parametro_sk
            WHERE fm.estacao_sk = ?
              AND dp.parametro_codigo = '1843'
              AND fm.valor IS NOT NULL
              AND dt.data_hora >= DATEADD(HOUR, -6, SYSDATETIME())
            ORDER BY dt.data_hora ASC
        """
        try:
            df_cur = pd.read_sql(sql_current, self.conn, params=[estacao_sk])
        except Exception:
            return None

        if len(df_cur) < 2:
            return None

        df_cur = df_cur.sort_values("data_hora")
        values = df_cur["valor"].astype(float).values
        hours = (len(values) - 1)
        if hours <= 0:
            return None

        current_rate = (values[-1] - values[0]) / hours
        if current_rate <= 0:
            return None

        sql_hist = """
            SELECT TOP 1 peak_value
            FROM ml.ew_flood_events
            WHERE estacao_sk = ?
            ORDER BY peak_value DESC
        """
        try:
            df_hist = pd.read_sql(sql_hist, self.conn, params=[estacao_sk])
        except Exception:
            return None

        if df_hist.empty:
            return None

        peak = float(df_hist.iloc[0]["peak_value"])
        current_level = float(values[-1])

        if current_level >= peak:
            return 0.0

        remaining = peak - current_level
        lead_time = remaining / current_rate
        return round(lead_time, 1)

    def save_detections(self) -> int:
        if not self.detections:
            return 0

        if self.dry_run:
            print(f"[DRY-RUN] Would insert {len(self.detections)} detection(s)")
            for d in self.detections:
                print(f"  Station SK={d['estacao_sk']}  "
                      f"combined={d['layer3_combined_score']}  "
                      f"lead_time={d['lead_time_hours']}h")
            return len(self.detections)

        sql = """
            INSERT INTO ml.ew_detections
                (estacao_sk, detection_ts,
                 layer1_percentile_score, layer1_details,
                 layer2_sequence_score, layer2_details,
                 layer3_combined_score,
                 lead_time_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = self.conn.cursor()
        count = 0
        for d in self.detections:
            cursor.execute(
                sql,
                d["estacao_sk"],
                d["detection_ts"],
                _nullify(d.get("layer1_percentile_score")),
                _nullify(d.get("layer1_details")),
                _nullify(d.get("layer2_sequence_score")),
                _nullify(d.get("layer2_details")),
                _nullify(d.get("layer3_combined_score")),
                _nullify(d.get("lead_time_hours")),
            )
            count += 1
        self.conn.commit()
        print(f"Inserted {count} detection(s) into ml.ew_detections")
        return count

    def close(self):
        if self._owns_conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="PreFlood_DW — 3-Layer Early Warning Engine",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
    )
    parser.add_argument(
        "--station", type=int, default=None,
    )
    args = parser.parse_args()

    stations = [args.station] if args.station else NATURAL_STATIONS

    engine = EarlyWarningEngine(dry_run=args.dry_run)
    try:
        total = 0
        for sk in stations:
            print(f"\n--- Evaluating station SK={sk} ---")
            detections = engine.evaluate_station(sk)
            for d in detections:
                print(
                    f"  Detection: combined_score={d['layer3_combined_score']}  "
                    f"pct={d['layer1_percentile_score']}  "
                    f"seq={d['layer2_sequence_score']}  "
                    f"lead_time={d['lead_time_hours']}h"
                )
            total += len(detections)

        print(f"\nTotal detections: {total}")
        if total > 0:
            engine.save_detections()
    finally:
        engine.close()


if __name__ == "__main__":
    main()
