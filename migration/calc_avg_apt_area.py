"""
migration/calc_avg_apt_area.py
Расчёт показателя 3.5 — Средняя площадь квартир в возводимых МЖД

Формула:
    3.5 = 3.3 / 3.4

где:
    3.3 — жилая площадь возводимых МЖД, млн кв. м
    3.4 — количество квартир в возводимых МЖД, млн ед.

Результат: кв. м (млн сокращаются)
Периодичность: monthly

Запуск:
    python migration/calc_avg_apt_area.py [--dry-run]

Зависимости: psycopg2, python-dotenv
"""

import os
import sys
import logging
from datetime import datetime

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


def main(dry_run: bool = False) -> int:
    """
    Рассчитывает и записывает 3.5 = 3.3 / 3.4.

    Параметры:
        dry_run: если True — только расчёт, без записи в БД.

    Возвращает количество записанных/обновлённых строк (0 при dry_run).
    """
    dry_run = dry_run or ("--dry-run" in sys.argv)
    log.info("=== Расчёт 3.5 — Средняя площадь квартир в возводимых МЖД ===")
    if dry_run:
        log.info("Режим DRY RUN — данные в БД не записываются")

    conn = get_connection()
    _n_rows = 0
    try:
        with conn:
            with conn.cursor() as cur:
                id_area  = get_indicator_id(cur, "3.3")
                id_count = get_indicator_id(cur, "3.4")
                id_out   = get_indicator_id(cur, "3.5")

                area  = fetch_series(cur, id_area)
                count = fetch_series(cur, id_count)

                log.info(f"3.3 — жилая площадь: {len(area)} точек")
                log.info(f"3.4 — количество квартир: {len(count)} точек")

                common_dates = sorted(set(area) & set(count))
                log.info(f"Совпадающих периодов: {len(common_dates)}")

                rows = []
                for d in common_dates:
                    a = area[d]
                    c = count[d]
                    if c <= 0:
                        log.warning(f"{d}: количество квартир = {c}, пропускаем")
                        continue
                    value = round(a / c, 4)
                    label = f"{MONTHS_RU[d.month - 1]} {d.year}"
                    rows.append((id_out, d, label, value, False, datetime.now()))
                    log.info(f"{label}: {a:.4f} / {c:.4f} = {value:.2f} кв. м")

                if not rows:
                    log.error("Нет данных для записи")
                    return

                log.info(f"Итого рассчитано: {len(rows)} точек")

                if dry_run:
                    log.info("DRY RUN — пропускаем запись в БД")
                    return 0

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
                log.info(f"Записано/обновлено: {_n_rows} строк")

                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e}")

        log.info("=== Готово. Проверьте: http://localhost:3000/chart.html?code=3.5 ===")
        print(f"Upserted: {_n_rows} rows")
        return _n_rows

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(0 if main() is not None else 1)
