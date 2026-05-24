"""
migration/calc_demand_activity.py
Расчёт показателя 5.3 — Активность спроса на первичном рынке

Формула:
    5.3 = SUM(5.1 за 4 квартала года) / 1.1

где:
    5.1  — количество ДДУ (Росреестр), квартальные данные
    1.1  — численность постоянного населения на 1 января, тыс. чел.

Результат: сделок на 1 тыс. чел. (annual)
Берём только полные годы (все 4 квартала присутствуют).

Запуск:
    python migration/calc_demand_activity.py [--dry-run]

Зависимости: psycopg2, python-dotenv
"""

import os
import sys
import logging
from collections import defaultdict
from datetime import date, datetime

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_indicator_id(cur, code: str) -> int:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Indicator '{code}' not found in DB")
    return row[0]


def fetch_quarterly_sum_by_year(cur, indicator_id: int) -> dict:
    """
    Суммирует квартальные значения по годам.
    Берём только полные годы (4 квартала).
    Возвращает {year: total}.
    """
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM period_date)::int AS year,
               COUNT(*) AS quarters,
               SUM(value) AS total
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        GROUP BY year
        HAVING COUNT(*) = 4
        ORDER BY year
        """,
        (indicator_id,),
    )
    return {row[0]: float(row[2]) for row in cur.fetchall()}


def fetch_annual(cur, indicator_id: int) -> dict:
    """Возвращает {year: value} для годовых данных."""
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM period_date)::int, value
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def main():
    log.info("=== Расчёт 5.3 — Активность спроса на первичном рынке ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    conn = get_connection()
    _n_rows = 0
    try:
        with conn:
            with conn.cursor() as cur:
                id_ddu  = get_indicator_id(cur, "5.1")
                id_pop  = get_indicator_id(cur, "1.1")
                id_out  = get_indicator_id(cur, "5.3")

                ddu_by_year = fetch_quarterly_sum_by_year(cur, id_ddu)
                population  = fetch_annual(cur, id_pop)

                log.info(f"5.1 — ДДУ (полные годы): {sorted(ddu_by_year.keys())}")
                log.info(f"1.1 — население: {sorted(population.keys())}")

                common_years = sorted(set(ddu_by_year) & set(population))
                log.info(f"Совпадающих лет: {len(common_years)}")

                rows = []
                for year in common_years:
                    ddu = ddu_by_year[year]
                    pop = population[year]
                    value = round(ddu / pop, 4)
                    log.info(
                        f"{year}: ДДУ={ddu:,.0f} / население={pop:,.1f} тыс. чел. "
                        f"→ {value:.4f} сделок/тыс. чел."
                    )
                    rows.append((
                        id_out,
                        date(year, 1, 1),
                        str(year),
                        value,
                        False,
                        datetime.now(),
                    ))

                if not rows:
                    log.error("Нет данных для записи")
                    return

                log.info(f"Итого рассчитано: {len(rows)} точек")

                if DRY_RUN:
                    log.info("DRY RUN — пропускаем запись в БД")
                    return

                execute_values(
                    cur,
                    """
                    INSERT INTO data_points
                        (indicator_id, period_date, period_label, value, is_preliminary, created_at)
                    VALUES %s
                    ON CONFLICT (indicator_id, period_date)
                    DO UPDATE SET
                        value          = EXCLUDED.value,
                        period_label   = EXCLUDED.period_label,
                        is_preliminary = EXCLUDED.is_preliminary
                    """,
                    rows,
                )
                _n_rows = cur.rowcount
                log.info(f"Записано/обновлено в data_points: {_n_rows} строк")

                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e} (данные записаны)")

        log.info("=== Готово. Проверьте: http://localhost:3000/chart.html?code=5.3 ===")
        print(f"Upserted: {_n_rows} rows")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
