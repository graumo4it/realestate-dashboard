"""
migration/calc_housing_provision.py

Рассчитывает показатель 2.10 — Обеспеченность жильём на конец года (кв. м / чел.)

Методология:
    Жилфонд (2.9) — данные на конец года N.
    Население (1.1) — данные на начало года N+1 (= конец года N).

    Т.е. для расчёта за год N используем:
        жилфонд[N]      (конец года N)
        население[N+1]  (начало следующего года = конец года N)

    Формула:
        2.10[N] = жилфонд[N] (млн кв. м) × 1_000_000
                  ─────────────────────────────────────
                  население[N+1] (тыс. чел.) × 1_000

    Последний доступный год: max(housing) при условии что население[max+1] есть.
    Пример: жилфонд есть за 2024, население на 01.01.2025 есть → 2.10 за 2024 ✓
            жилфонд есть за 2025, население на 01.01.2026 нет  → 2025 пропускаем

Зависимости:
    - 2.9  Общая площадь жилых помещений на конец года (Жилфонд), млн кв. м
    - 1.1  Численность постоянного населения на 1 января, тыс. чел.

Использование:
    python3 migration/calc_housing_provision.py
    python3 migration/calc_housing_provision.py --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# .env
for _env_path in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path.cwd() / ".env",
]:
    if _env_path.exists():
        load_dotenv(_env_path)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def fetch_annual_series(cur, code: str) -> dict:
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM dp.period_date)::int, dp.value
        FROM data_points dp
        JOIN indicators i ON i.id = dp.indicator_id
        WHERE i.code = %s AND dp.value IS NOT NULL
        ORDER BY dp.period_date
        """,
        (code,),
    )
    return {year: float(value) for year, value in cur.fetchall()}


def get_indicator_id(cur, code: str) -> Optional[int]:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    return row[0] if row else None


def ensure_indicator_210(cur) -> int:
    ind_id = get_indicator_id(cur, "2.10")
    if ind_id:
        return ind_id

    log.info("Индикатор 2.10 не найден — создаём...")

    cur.execute("SELECT id FROM categories WHERE code = 'housing_stock'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Категория 'housing_stock' не найдена в БД.")
    category_id = row[0]

    cur.execute("SELECT id FROM sources WHERE code = 'rosstat'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Источник 'rosstat' не найден в БД.")
    source_id = row[0]

    cur.execute(
        """
        INSERT INTO indicators
            (code, category_id, source_id, name, unit,
             periodicity, period_type, geo_level,
             description, source_url, is_public, chart_type, sort_order)
        VALUES
            ('2.10', %s, %s,
             'Обеспеченность жильём на конец года',
             'кв. м / чел.',
             'annual', 'point_in_time', 'russia',
             'Общая площадь жилых помещений в расчёте на одного жителя на конец года. '
             'Рассчитывается как отношение жилищного фонда на конец года N (показатель 2.9) '
             'к численности постоянного населения на начало года N+1 (показатель 1.1).',
             'https://rosstat.gov.ru/folder/12781',
             TRUE, 'line', 10)
        RETURNING id
        """,
        (category_id, source_id),
    )
    ind_id = cur.fetchone()[0]
    log.info(f"Создан индикатор 2.10, id={ind_id}")
    return ind_id


def upsert_data_points(cur, indicator_id: int, rows: list) -> int:
    if not rows:
        return 0
    data = [(indicator_id, r[0], r[1], r[2], False) for r in rows]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO data_points
            (indicator_id, period_date, period_label, value, is_preliminary)
        VALUES %s
        ON CONFLICT (indicator_id, period_date) DO UPDATE
            SET value          = EXCLUDED.value,
                period_label   = EXCLUDED.period_label,
                is_preliminary = EXCLUDED.is_preliminary
        """,
        data,
        template="(%s, %s, %s, %s, %s)",
    )
    return len(data)


def calc_provision(housing: dict, population: dict) -> list:
    """
    Для года N: жилфонд[N] (конец года) / население[N+1] (начало след. года).
    Год пропускается если нет population[N+1].
    period_date = 31 декабря года N.
    """
    results = []
    skipped = []

    for year in sorted(housing.keys()):
        pop_year = year + 1
        if pop_year not in population:
            skipped.append(year)
            continue

        h = housing[year]
        p = population[pop_year]

        if p <= 0:
            skipped.append(year)
            continue

        # млн кв. м * 1_000_000 / (тыс. чел. * 1_000) = кв. м / чел.
        value = round(h * 1_000_000 / (p * 1_000), 2)
        results.append((date(year, 12, 31), str(year), value))

    if skipped:
        log.info(f"Пропущено (нет населения на год N+1): {skipped}")

    return results


def apply_renames(cur):
    renames = [
        ("2.9",  "Общая площадь жилых помещений на конец года (Жилфонд)"),
        ("2.10", "Обеспеченность жильём на конец года"),
    ]
    for code, new_name in renames:
        cur.execute("UPDATE indicators SET name = %s WHERE code = %s", (new_name, code))
        if cur.rowcount:
            log.info(f"Переименован {code}: «{new_name}»")


def main():
    parser = argparse.ArgumentParser(
        description="Расчёт обеспеченности жильём на конец года (2.10)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Показать результат без записи в БД")
    args = parser.parse_args()

    log.info("Подключаемся к PostgreSQL...")
    try:
        conn = get_conn()
    except Exception as e:
        log.error(f"Ошибка подключения: {e}")
        sys.exit(1)

    try:
        with conn:
            with conn.cursor() as cur:

                housing = fetch_annual_series(cur, "2.9")
                population = fetch_annual_series(cur, "1.1")

                log.info(f"2.9  жилфонд:   {len(housing)} точек ({min(housing)}–{max(housing)})")
                log.info(f"1.1  население: {len(population)} точек ({min(population)}–{max(population)})")

                if not housing:
                    log.error("Нет данных для 2.9.")
                    sys.exit(1)
                if not population:
                    log.error("Нет данных для 1.1. Запустите migrate_population_1990_2010.py.")
                    sys.exit(1)

                results = calc_provision(housing, population)
                log.info(f"Рассчитано точек: {len(results)}")

                if not results:
                    log.error("Нет пересечения данных. Проверьте ряды 2.9 и 1.1.")
                    sys.exit(1)

                if args.dry_run:
                    log.info("─" * 60)
                    log.info("DRY-RUN: результаты расчёта")
                    log.info(f"  {'Год':<6} {'Жилфонд':>16} {'Нас-е N+1':>16} {'Обесп-ть':>12}")
                    log.info("─" * 60)
                    for period_date, label, value in results:
                        year = period_date.year
                        h = housing.get(year, "—")
                        p = population.get(year + 1, "—")
                        log.info(f"  {label:<6} {str(h):>16} {str(p):>16} {value:>10} кв.м/чел.")
                    log.info("─" * 60)
                    log.info(f"Последнее: {results[-1][2]} кв.м/чел. ({results[-1][1]})")
                    return

                apply_renames(cur)
                ind_id = ensure_indicator_210(cur)
                count = upsert_data_points(cur, ind_id, results)
                log.info(f"Записано/обновлено: {count} точек")

                log.info("Обновляем materialized view...")
                try:
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён ✓")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e}")

        log.info("=" * 55)
        log.info("Готово!")
        years = [r[0].year for r in results]
        log.info(f"  Диапазон:          {min(years)}–{max(years)}")
        log.info(f"  Последнее значение: {results[-1][2]} кв.м/чел. ({results[-1][1]})")
        log.info("=" * 55)

    except Exception as e:
        log.error(f"Ошибка: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
