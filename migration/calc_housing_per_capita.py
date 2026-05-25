"""
calc_housing_per_capita.py
Рассчитывает показатели ввода жилья на душу населения:

  2.6 = 2.1 [тыс. кв. м] / 1.1 [тыс. чел.]    →  кв. м / чел.  (всего)
  2.7 = 2.2 [тыс. кв. м] / 1.1 [тыс. чел.]    →  кв. м / чел.  (ИЖС)
  2.8 = (2.1 − 2.2) [тыс. кв. м] / 1.1         →  кв. м / чел.  (МЖС)

Логика:
  - 1.1 — годовой (на 1 января года Y); используется для всех месяцев года Y
  - Для месяцев года Y, где 1.1[Y] отсутствует — пропускаем
  - Пересчёт полного ряда через DO UPDATE

Запуск:
  python migration/calc_housing_per_capita.py [--dry-run]

Запускается автоматически после rosstat.py через scheduler.py (10-е число).
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv

MONTHS_RU = [
    "январь","февраль","март","апрель","май","июнь",
    "июль","август","сентябрь","октябрь","ноябрь","декабрь",
]


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "realestate"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def get_indicator_id(cur, code: str) -> int:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Indicator '{code}' not found in DB")
    return row[0]


def fetch_monthly_series(cur, indicator_id: int) -> dict:
    """Возвращает {period_date: value} для месячного ряда."""
    cur.execute(
        """
        SELECT period_date, value
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def fetch_annual_series(cur, indicator_id: int) -> dict:
    """Возвращает {year: value} для годового ряда."""
    cur.execute(
        """
        SELECT period_date, value
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    return {row[0].year: float(row[1]) for row in cur.fetchall()}


def month_label(d: date) -> str:
    return f"{MONTHS_RU[d.month - 1]} {d.year}"


def main():
    log.info("=== Расчёт 2.6, 2.7, 2.8 — Ввод жилья на душу населения ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            id_21 = get_indicator_id(cur, "2.1")
            id_22 = get_indicator_id(cur, "2.2")
            id_11 = get_indicator_id(cur, "1.1")
            id_26 = get_indicator_id(cur, "2.6")
            id_27 = get_indicator_id(cur, "2.7")
            id_28 = get_indicator_id(cur, "2.8")

        with conn.cursor() as cur:
            s21 = fetch_monthly_series(cur, id_21)   # тыс. кв. м (ввод всего)
            s22 = fetch_monthly_series(cur, id_22)   # тыс. кв. м (ввод ИЖС)
            pop = fetch_annual_series(cur, id_11)    # тыс. чел. (1 января года Y)

        log.info(
            f"Загружено: 2.1={len(s21)} пт. | 2.2={len(s22)} пт. | 1.1={len(pop)} лет"
        )

        rows_26, rows_27, rows_28 = [], [], []
        skipped = 0

        all_dates = sorted(set(s21.keys()) | set(s22.keys()))
        for d in all_dates:
            population = pop.get(d.year)
            if population is None or population == 0:
                skipped += 1
                continue

            v21 = s21.get(d)
            v22 = s22.get(d)
            label = month_label(d)

            # 2.6: ввод всего на душу
            if v21 is not None:
                rows_26.append((id_26, d, label, round(v21 / population, 6)))

            # 2.7: ввод ИЖС на душу
            if v22 is not None:
                rows_27.append((id_27, d, label, round(v22 / population, 6)))

            # 2.8: ввод МЖС (всего − ИЖС) на душу
            if v21 is not None and v22 is not None:
                rows_28.append((id_28, d, label, round((v21 - v22) / population, 6)))

        log.info(
            f"Рассчитано: 2.6={len(rows_26)} | 2.7={len(rows_27)} | 2.8={len(rows_28)} точек"
        )
        if skipped:
            log.warning(
                f"Пропущено {skipped} месяц(ев) — нет данных 1.1 за соответствующий год"
            )

        if DRY_RUN:
            return len(rows_26) + len(rows_27) + len(rows_28)

        upsert_sql = """
            INSERT INTO data_points
                (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES (%s, %s, %s, %s, false)
            ON CONFLICT (indicator_id, period_date) DO UPDATE
                SET value        = EXCLUDED.value,
                    period_label = EXCLUDED.period_label
        """
        total = 0
        with conn.cursor() as cur:
            for rows, name in [
                (rows_26, "2.6"),
                (rows_27, "2.7"),
                (rows_28, "2.8"),
            ]:
                if rows:
                    cur.executemany(upsert_sql, rows)
                    log.info(f"  [{name}] Upserted: {len(rows)} точек")
                    total += len(rows)

            log.info("Обновляю materialized view ...")
            cur.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
            )

        conn.commit()
        log.info(f"✅ Готово. Итого upserted: {total} строк")
        return total

    finally:
        conn.close()


if __name__ == "__main__":
    main()
