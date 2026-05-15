"""
migration/calc_housing_need.py
Расчёт показателей потребности в жилье (5.12–5.15) по двум сценариям

Два сценария:
    33 — целевая обеспеченность 33 кв. м / чел. к 2030 г.
    38 — целевая обеспеченность 38 кв. м / чел. к 2036 г.

Формулы:

5.12.T = (T - 2.10) × 1.1           тыс. кв. м
    T       — целевое значение (33 или 38)
    2.10    — обеспеченность жильём, кв. м / чел.
    1.1     — численность населения, тыс. чел.

5.13.T = 5.12.T / ввод_за_год       лет
    ввод_за_год — сумма 2.1 за все месяцы года, тыс. кв. м

5.14.T = (T - 2.10 × 2.13/100) × 1.1    тыс. кв. м
    2.13    — доля благоустроенного жилфонда, %

5.15.T = 5.14.T / ввод_за_год       лет

Все показатели годовые (annual).
period_date = YYYY-01-01, period_label = 'YYYY'

Перед запуском: удалить старые данные 5.12–5.15 и сами индикаторы,
создать новые коды 5.12.33, 5.12.38, 5.13.33, 5.13.38,
5.14.33, 5.14.38, 5.15.33, 5.15.38.

Запуск:
    python migration/calc_housing_need.py [--dry-run]

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

TARGETS = [33, 38]


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


def fetch_monthly_sum_by_year(cur, indicator_id: int) -> dict:
    """Суммирует месячные значения по годам. Возвращает {year: total}."""
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM period_date)::int, SUM(value)
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        GROUP BY EXTRACT(YEAR FROM period_date)
        ORDER BY 1
        """,
        (indicator_id,),
    )
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def upsert_rows(cur, indicator_id: int, rows: list):
    data = [
        (indicator_id, date(year, 1, 1), str(year), value, False, datetime.now())
        for year, value in rows
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


def delete_old_indicators(cur):
    """Удаляем старые данные и индикаторы 5.12–5.15."""
    old_codes = ['5.12', '5.13', '5.14', '5.15']
    for code in old_codes:
        cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM data_points WHERE indicator_id = %s", (row[0],))
            cur.execute("DELETE FROM indicators WHERE id = %s", (row[0],))
            log.info(f"Удалён индикатор {code} и его данные")
        else:
            log.info(f"Индикатор {code} не найден, пропускаем")


def create_new_indicators(cur):
    """Создаём новые коды если их ещё нет."""
    # Получаем category_id и source_id из одного из старых или соседних показателей
    cur.execute("""
        SELECT category_id, source_id
        FROM indicators
        WHERE code IN ('5.9', '5.10', '5.11', '5.3')
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        raise ValueError("Не удалось определить category_id и source_id для новых индикаторов")
    category_id, source_id = row

    new_indicators = [
        ('5.12.33', '5.12 Уровень потребности в жилье для достижения минимально приемлемых условий комфорта проживания (цель 33 кв. м)', 'тыс. кв. м', 10),
        ('5.12.38', '5.12 Уровень потребности в жилье для достижения минимально приемлемых условий комфорта проживания (цель 38 кв. м)', 'тыс. кв. м', 11),
        ('5.13.33', '5.13 Скорость удовлетворения потребности в жилье при текущем объеме ввода (цель 33 кв. м)', 'лет', 12),
        ('5.13.38', '5.13 Скорость удовлетворения потребности в жилье при текущем объеме ввода (цель 38 кв. м)', 'лет', 13),
        ('5.14.33', '5.14 Уровень потребности в жилье для достижения минимально приемлемых условий комфорта проживания (цель 33 кв. м)', 'тыс. кв. м', 14),
        ('5.14.38', '5.14 Уровень потребности в жилье для достижения минимально приемлемых условий комфорта проживания (цель 38 кв. м)', 'тыс. кв. м', 15),
        ('5.15.33', '5.15 Скорость удовлетворения реальной потребности в жилье при текущем объеме ввода (цель 33 кв. м)', 'лет', 16),
        ('5.15.38', '5.15 Скорость удовлетворения реальной потребности в жилье при текущем объеме ввода (цель 38 кв. м)', 'лет', 17),
    ]

    for code, name, unit, sort_order in new_indicators:
        cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
        if cur.fetchone():
            log.info(f"Индикатор {code} уже существует, пропускаем")
            continue
        cur.execute(
            """
            INSERT INTO indicators
                (code, category_id, source_id, name, unit, periodicity,
                 period_type, is_public, chart_type, sort_order)
            VALUES (%s, %s, %s, %s, %s, 'annual', 'period', false, 'line', %s)
            """,
            (code, category_id, source_id, name, unit, sort_order),
        )
        log.info(f"Создан индикатор {code}: {name}")


def main():
    log.info("=== Расчёт 5.12–5.15 — Потребность в жилье (два сценария) ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:

                if not DRY_RUN:
                    log.info("Удаляем старые индикаторы 5.12–5.15...")
                    delete_old_indicators(cur)
                    log.info("Создаём новые индикаторы...")
                    create_new_indicators(cur)

                # Загружаем исходные данные
                id_provision = get_indicator_id(cur, "2.10")   # кв. м / чел.
                id_population = get_indicator_id(cur, "1.1")   # тыс. чел.
                id_input = get_indicator_id(cur, "2.1")        # тыс. кв. м, monthly
                id_amenity = get_indicator_id(cur, "2.13")     # %, annual

                provision  = fetch_annual(cur, id_provision)
                population = fetch_annual(cur, id_population)
                input_vol  = fetch_monthly_sum_by_year(cur, id_input)
                amenity    = fetch_annual(cur, id_amenity)

                log.info(f"2.10 — обеспеченность: {sorted(provision.keys())}")
                log.info(f"1.1  — население: {sorted(population.keys())}")
                log.info(f"2.1  — ввод жилья (год): {sorted(input_vol.keys())}")
                log.info(f"2.13 — благоустройство: {sorted(amenity.keys())}")

                # Общие годы для 5.12 и 5.13
                years_512 = sorted(set(provision) & set(population))
                years_513 = sorted(set(years_512) & set(input_vol))
                # Общие годы для 5.14 и 5.15
                years_514 = sorted(set(provision) & set(population) & set(amenity))
                years_515 = sorted(set(years_514) & set(input_vol))

                results = {t: {'5.12': [], '5.13': [], '5.14': [], '5.15': []} for t in TARGETS}

                for t in TARGETS:
                    log.info(f"\n--- Сценарий {t} кв. м ---")

                    # 5.12.T = (T - 2.10) × 1.1
                    for year in years_512:
                        val = round((t - provision[year]) * population[year], 4)
                        results[t]['5.12'].append((year, val))
                        log.info(f"  5.12.{t} {year}: ({t} - {provision[year]:.2f}) × {population[year]:.1f} = {val:,.0f} тыс. кв. м")

                    # 5.13.T = 5.12.T / ввод
                    dict_512 = dict(results[t]['5.12'])
                    for year in years_513:
                        if dict_512.get(year) is None or input_vol[year] <= 0:
                            continue
                        val = round(dict_512[year] / input_vol[year], 4)
                        results[t]['5.13'].append((year, val))
                        log.info(f"  5.13.{t} {year}: {dict_512[year]:,.0f} / {input_vol[year]:,.0f} = {val:.2f} лет")

                    # 5.14.T = (T - 2.10 × 2.13/100) × 1.1
                    for year in years_514:
                        effective = provision[year] * amenity[year] / 100
                        val = round((t - effective) * population[year], 4)
                        results[t]['5.14'].append((year, val))
                        log.info(f"  5.14.{t} {year}: ({t} - {provision[year]:.2f}×{amenity[year]:.1f}%) × {population[year]:.1f} = {val:,.0f} тыс. кв. м")

                    # 5.15.T = 5.14.T / ввод
                    dict_514 = dict(results[t]['5.14'])
                    for year in years_515:
                        if dict_514.get(year) is None or input_vol[year] <= 0:
                            continue
                        val = round(dict_514[year] / input_vol[year], 4)
                        results[t]['5.15'].append((year, val))
                        log.info(f"  5.15.{t} {year}: {dict_514[year]:,.0f} / {input_vol[year]:,.0f} = {val:.2f} лет")

                if DRY_RUN:
                    log.info("\nDRY RUN — пропускаем запись в БД")
                    # Выводим итоговое количество точек
                    for t in TARGETS:
                        for base in ['5.12', '5.13', '5.14', '5.15']:
                            log.info(f"  {base}.{t}: {len(results[t][base])} точек")
                    return

                # Записываем данные
                for t in TARGETS:
                    for base in ['5.12', '5.13', '5.14', '5.15']:
                        code = f"{base}.{t}"
                        ind_id = get_indicator_id(cur, code)
                        n = upsert_rows(cur, ind_id, results[t][base])
                        log.info(f"{code}: записано {n} строк")

                # Refresh materialized view
                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e} (данные записаны)")

        log.info("=== Готово ===")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
