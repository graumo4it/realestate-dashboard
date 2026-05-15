"""
migration/calc_sales_pace_mm.py
Расчёт показателей темпа продаж машиномест на первичном рынке

5.22 — нарастающее среднее с начала года (YTD average) по 5.20:
    5.22[янв] = 5.20[янв]
    5.22[фев] = (5.20[янв] + 5.20[фев]) / 2
    ...
    5.22[дек] = (5.20[янв] + ... + 5.20[дек]) / 12

5.22.ma12 — скользящее среднее за 12 месяцев (rolling 12m):
    5.22.ma12[месяц] = среднее 5.20 за последние 12 месяцев включительно
    Расчёт начинается с декабря первого полного года данных

ВНИМАНИЕ: данные 5.22 от ДОМ.РФ будут перезаписаны.

Запуск:
    python migration/calc_sales_pace_mm.py [--dry-run]

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

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


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


def fetch_series(cur, indicator_id: int) -> dict:
    """Возвращает {period_date: value} для всех ненулевых точек."""
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


def calc_ytd(source: dict) -> list:
    """Нарастающее среднее с начала года."""
    by_year = defaultdict(dict)
    for d, v in source.items():
        by_year[d.year][d.month] = (d, v)

    rows = []
    for year in sorted(by_year):
        months = sorted(by_year[year])
        running_sum = 0.0
        for i, month in enumerate(months, start=1):
            period_date, val = by_year[year][month]
            running_sum += val
            ytd_avg = round(running_sum / i, 4)
            label = f"{MONTHS_RU[month - 1]} {year}"
            rows.append((period_date, label, ytd_avg))
    return rows


def calc_ma12(source: dict) -> list:
    """Скользящее среднее за 12 месяцев, начиная с первого декабря где есть 12 точек."""
    sorted_dates = sorted(source.keys())
    rows = []

    for i, d in enumerate(sorted_dates):
        if i < 11:
            continue  # нужно минимум 12 точек
        window = [source[sd] for sd in sorted_dates[i - 11: i + 1]]
        if len(window) < 12:
            continue
        ma12 = round(sum(window) / 12, 4)
        label = f"{MONTHS_RU[d.month - 1]} {d.year}"
        rows.append((d, label, ma12))
    return rows


def upsert_rows(cur, indicator_id: int, rows: list):
    data = [
        (indicator_id, d, label, value, False, datetime.now())
        for d, label, value in rows
    ]
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
        data,
    )
    return cur.rowcount


def main():
    log.info("=== Расчёт 5.22 и 5.22.ma12 — Темп продаж машиномест ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                id_src  = get_indicator_id(cur, "5.20")
                id_ytd  = get_indicator_id(cur, "5.22")
                id_ma12 = get_indicator_id(cur, "5.22.ma12")

                source = fetch_series(cur, id_src)
                log.info(f"5.20 — загружено точек: {len(source)}")
                log.info(f"Диапазон: {min(source.keys())} — {max(source.keys())}")

                # --- 5.22: YTD-среднее ---
                ytd_rows = calc_ytd(source)
                log.info(f"\n--- 5.22 (YTD-среднее): {len(ytd_rows)} точек ---")
                for d, label, val in ytd_rows[-6:]:
                    log.info(f"  {label}: {val:,.2f}")

                # --- 5.22.ma12: скользящее среднее 12м ---
                ma12_rows = calc_ma12(source)
                log.info(f"\n--- 5.22.ma12 (MA12): {len(ma12_rows)} точек ---")
                log.info(f"  Начало: {ma12_rows[0][1] if ma12_rows else '—'}")
                for d, label, val in ma12_rows[-6:]:
                    log.info(f"  {label}: {val:,.2f}")

                if DRY_RUN:
                    log.info("\nDRY RUN — пропускаем запись в БД")
                    return

                # Записываем 5.22
                n = upsert_rows(cur, id_ytd, ytd_rows)
                log.info(f"5.22 записано/обновлено: {n} строк")

                # Записываем 5.22.ma12
                n = upsert_rows(cur, id_ma12, ma12_rows)
                log.info(f"5.22.ma12 записано/обновлено: {n} строк")

                # Refresh materialized view
                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e} (данные записаны)")

        log.info("=== Готово. Проверьте: http://localhost:3000/sales-pace-mm-chart.html ===")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
