"""
migration/calc_developer_activity.py
Расчёт показателей девелоперской активности по текущему строительству

Формула:
    3.7             = 3.3[январь года] * 1000 / 1.1[год]
    uc_dev_activity = uc_area_total[январь года] * 1000 / 1.1[год]

где:
    3.3 — жилая площадь возводимых МЖД на отчётную дату, млн кв. м
          берём значение за январь каждого года
    uc_area_total — жилая площадь возводимых МЖД из платной базы ДОМ.РФ,
                    млн кв. м; берём значение за январь каждого года
    1.1 — численность постоянного населения на 1 января, тыс. чел.

Результат: кв. м / чел.
    млн кв. м × 1000 / тыс. чел. = кв. м / чел.

Периодичность: annual, period_date = YYYY-01-01.
period_label: 'YYYY' для 3.7, 'Январь YYYY' для uc_dev_activity.

Запуск:
    python migration/calc_developer_activity.py [--dry-run]

Зависимости: psycopg2, python-dotenv
"""

import os
import sys
import logging
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

MONTHS_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

CALCULATIONS = [
    {
        "area_code": "3.3",
        "out_code": "3.7",
        "name": "3.7 — открытые данные ДОМ.РФ",
        "decimals": 4,
        "period_label": lambda year: str(year),
    },
    {
        "area_code": "uc_area_total",
        "out_code": "uc_dev_activity",
        "name": "uc_dev_activity — платная база ДОМ.РФ",
        "decimals": 2,
        "period_label": lambda year: f"{MONTHS_RU[1]} {year}",
    },
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


def get_optional_indicator_id(cur, code: str) -> int | None:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    return row[0] if row else None


def fetch_january_values(cur, indicator_id: int) -> dict:
    """Возвращает {year: value} — только январские значения."""
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM period_date)::int, value
        FROM data_points
        WHERE indicator_id = %s
          AND value IS NOT NULL
          AND EXTRACT(MONTH FROM period_date) = 1
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def calculate_rows(cur, population: dict) -> tuple[list[tuple], list[str]]:
    rows = []
    output_codes = []

    for cfg in CALCULATIONS:
        area_code = cfg["area_code"]
        out_code = cfg["out_code"]
        id_area = get_optional_indicator_id(cur, area_code)
        id_out = get_optional_indicator_id(cur, out_code)

        if id_area is None:
            log.warning(f"{cfg['name']}: входной индикатор {area_code} не найден, пропускаем")
            continue
        if id_out is None:
            log.warning(f"{cfg['name']}: выходной индикатор {out_code} не найден, пропускаем")
            continue

        area_jan = fetch_january_values(cur, id_area)
        common_years = sorted(set(area_jan) & set(population))

        log.info(f"{area_code} (январь) — данные за годы: {sorted(area_jan.keys())}")
        log.info(f"{cfg['name']}: совпадающих лет с 1.1: {len(common_years)}")

        if not common_years:
            log.warning(f"{cfg['name']}: нет общих лет с населением 1.1")
            continue

        output_codes.append(out_code)

        for year in common_years:
            area = area_jan[year]
            pop = population[year]
            value = round(area * 1000 / pop, cfg["decimals"])
            log.info(
                f"{year}: {area_code}[янв]={area:.4f} млн кв.м × 1000 / "
                f"{pop:.1f} тыс.чел. = {value:.4f} кв.м/чел. → {out_code}"
            )
            rows.append((
                id_out,
                date(year, 1, 1),
                cfg["period_label"](year),
                value,
                False,
                datetime.now(),
            ))

    return rows, output_codes


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
    log.info("=== Расчёт девелоперской активности по текущему строительству ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    conn = get_connection()
    _n_rows = 0
    try:
        with conn:
            with conn.cursor() as cur:
                id_pop = get_indicator_id(cur, "1.1")
                population = fetch_annual(cur, id_pop)

                log.info(f"1.1 — население: данные за годы: {sorted(population.keys())}")

                rows, output_codes = calculate_rows(cur, population)

                if not rows:
                    log.error("Нет данных для записи")
                    return

                log.info(f"Итого рассчитано: {len(rows)} точек")

                if DRY_RUN:
                    log.info("DRY RUN — пропускаем запись в БД")
                    return

                # Сначала удаляем старые данные
                cur.execute(
                    """
                    DELETE FROM data_points
                    WHERE indicator_id IN (
                        SELECT id FROM indicators WHERE code = ANY(%s)
                    )
                    """,
                    (output_codes,),
                )
                log.info(f"Удалено старых точек: {cur.rowcount}")

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
                log.info(f"Записано: {_n_rows} строк")

                # Обновляем periodicity на annual
                cur.execute(
                    "UPDATE indicators SET periodicity = 'annual' WHERE code = ANY(%s)",
                    (output_codes,),
                )
                log.info(f"periodicity обновлён на 'annual' для {', '.join(output_codes)}")

                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e}")

        log.info("=== Готово. Проверьте: http://localhost:3000/chart.html?code=3.7 и ?code=uc_dev_activity ===")
        print(f"Upserted: {_n_rows} rows")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
