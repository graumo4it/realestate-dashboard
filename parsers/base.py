"""
Базовый класс для всех парсеров данных
"""
import logging
import os
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "realestate"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

MAX_RETRIES = 3
RETRY_BACKOFF = 60  # секунд


class BaseParser(ABC):
    source_code: str = ""

    def __init__(self):
        self.conn = None
        self.source_id: int | None = None
        self.job_id: int | None = None

    # ─── Абстрактные методы ──────────────────────────────────────────────────

    @abstractmethod
    def fetch_raw(self) -> Any:
        """Скачать исходные данные (Excel, JSON, HTML)."""
        ...

    @abstractmethod
    def parse(self, raw: Any) -> list[dict]:
        """
        Распарсить исходные данные.
        Возвращает список:
          [{"indicator_code": str, "period_date": date, "value": float | None}, ...]
        """
        ...

    # ─── Шаблонный метод ─────────────────────────────────────────────────────

    def run(self) -> dict:
        self._connect()
        self._get_source_id()
        self._start_job()

        try:
            raw = self._fetch_with_retry()
            records = self.parse(raw)

            codes = list({r["indicator_code"] for r in records})
            last_dates = self.get_last_dates(codes)
            new_records = [
                r for r in records
                if r["period_date"] > last_dates.get(r["indicator_code"], date.min)
            ]
            log.info(
                f"[{self.source_code}] Распарсено: {len(records)}, новых: {len(new_records)}"
            )

            rows = self.upsert_to_db(new_records)
            self._finish_job("success", rows)
            self._refresh_view()
            log.info(f"[{self.source_code}] Done. Rows upserted: {rows}")
            return {"status": "success", "rows": rows, "error": None}
        except Exception as e:
            log.error(f"[{self.source_code}] Error: {e}", exc_info=True)
            self._finish_job("error", 0, str(e))
            return {"status": "error", "rows": 0, "error": str(e)}
        finally:
            if self.conn:
                self.conn.close()

    # ─── Утилиты ─────────────────────────────────────────────────────────────

    def _connect(self):
        self.conn = psycopg2.connect(**DB_CONFIG)

    def _get_source_id(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM sources WHERE code = %s", (self.source_code,))
            row = cur.fetchone()
            self.source_id = row[0] if row else None

    def _start_job(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO update_jobs (source_id, status, started_at)
                VALUES (%s, 'running', NOW())
                RETURNING id
            """, (self.source_id,))
            self.job_id = cur.fetchone()[0]
            self.conn.commit()

    def _finish_job(self, status: str, rows: int, error: str | None = None):
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE update_jobs
                SET status = %s, finished_at = NOW(), rows_upserted = %s, error_message = %s
                WHERE id = %s
            """, (status, rows, error, self.job_id))
            self.conn.commit()

    def _fetch_with_retry(self) -> Any:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.fetch_raw()
            except Exception as e:
                log.warning(f"[{self.source_code}] Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF * attempt)
                else:
                    raise

    def get_last_dates(self, codes: list[str]) -> dict[str, date]:
        """Возвращает {indicator_code: max_period_date} для переданных кодов."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT i.code, MAX(dp.period_date)
                FROM data_points dp
                JOIN indicators i ON i.id = dp.indicator_id
                WHERE i.code = ANY(%s)
                GROUP BY i.code
            """, (codes,))
            return {row[0]: row[1] for row in cur.fetchall()}

    def _get_indicator_id(self, cur, code: str) -> int | None:
        cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        return row[0] if row else None

    def upsert_to_db(self, records: list[dict]) -> int:
        if not records:
            return 0
        with self.conn.cursor() as cur:
            rows = []
            for r in records:
                ind_id = self._get_indicator_id(cur, r["indicator_code"])
                if ind_id is None:
                    log.warning(f"Unknown indicator code: {r['indicator_code']}")
                    continue
                rows.append((
                    ind_id,
                    r["period_date"],
                    r.get("period_label"),
                    r.get("value"),
                ))
            if rows:
                execute_values(cur, """
                    INSERT INTO data_points (indicator_id, period_date, period_label, value)
                    VALUES %s
                    ON CONFLICT (indicator_id, period_date) DO NOTHING
                """, rows)
            self.conn.commit()
        return len(rows)

    def upsert_update_to_db(self, records: list[dict]) -> int:
        """
        Upsert с перезаписью существующих значений (ON CONFLICT DO UPDATE).
        Используется для индикаторов, данные которых ретроспективно уточняются
        (например, субсидии ДОМ.РФ).
        """
        if not records:
            return 0
        with self.conn.cursor() as cur:
            rows = []
            for r in records:
                ind_id = self._get_indicator_id(cur, r["indicator_code"])
                if ind_id is None:
                    log.warning(f"Unknown indicator code: {r['indicator_code']}")
                    continue
                rows.append((
                    ind_id,
                    r["period_date"],
                    r.get("period_label"),
                    r.get("value"),
                ))
            if rows:
                execute_values(cur, """
                    INSERT INTO data_points (indicator_id, period_date, period_label, value)
                    VALUES %s
                    ON CONFLICT (indicator_id, period_date) DO UPDATE
                      SET value        = EXCLUDED.value,
                          period_label = EXCLUDED.period_label
                """, rows)
            self.conn.commit()
        return len(rows)

    def _refresh_view(self):
        with self.conn.cursor() as cur:
            try:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
                self.conn.commit()
            except Exception as e:
                log.warning(f"Could not refresh materialized view: {e}")
                self.conn.rollback()
