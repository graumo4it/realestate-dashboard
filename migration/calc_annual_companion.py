"""
migration/calc_annual_companion.py

Авто-рассчитывает компаньон-индикатор 1.3.y
«Среднемесячная заработная плата (годовая)».

Методология Росстата: «Год» = среднее арифметическое четырёх кварталов.
1.3.y[Y] = (1.3[Q1 Y] + 1.3[Q2 Y] + 1.3[Q3 Y] + 1.3[Q4 Y]) / 4

Условия расчёта года:
  - Все 4 квартала присутствуют в data_points (value IS NOT NULL)
  - Год считается «полным» — неполные последние годы пропускаются

period_date для 1.3.y: YYYY-01-01 (первый день года)
period_label:           «YYYY»
periodicity:            annual (уже задано в indicators)
is_public:              false  (не показывается в навигации)

Запуск:
  source venv/bin/activate
  python migration/calc_annual_companion.py [--dry-run]

Используется в scheduler.py (day10, после rosstat.py).
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

for _env in [Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Источник и цель
SRC_CODE = "1.3"    # квартальная зарплата (от rosstat.py / EMISS)
DST_CODE = "1.3.y"  # годовой компаньон


def get_conn():
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
        raise ValueError(f"Индикатор '{code}' не найден в БД.")
    return row[0]


def fetch_quarterly(cur, indicator_id: int) -> dict[int, list[float]]:
    """
    Возвращает {year: [значения по кварталам]}.
    Ожидаем period_date = YYYY-{01,04,07,10}-01.
    """
    cur.execute(
        """
        SELECT EXTRACT(YEAR FROM period_date)::int  AS y,
               EXTRACT(MONTH FROM period_date)::int AS m,
               value
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    QUARTER_MONTHS = {1, 4, 7, 10}
    by_year: dict[int, list[float]] = defaultdict(list)
    skipped = 0
    for y, m, v in cur.fetchall():
        if m in QUARTER_MONTHS:
            by_year[y].append(float(v))
        else:
            skipped += 1
    if skipped:
        log.warning(f"Пропущено {skipped} строк с неквартальными месяцами (м={m}).")
    return dict(by_year)


def calc_annual(quarterly: dict[int, list[float]]) -> list[tuple[int, float]]:
    """
    Для каждого года с 4 кварталами возвращает (year, avg).
    Неполные годы (< 4 кварталов) пропускаются.
    """
    results = []
    skipped = []
    for year in sorted(quarterly):
        vals = quarterly[year]
        if len(vals) < 4:
            skipped.append(f"{year} ({len(vals)}/4 кв.)")
            continue
        if len(vals) > 4:
            log.warning(f"{year}: найдено {len(vals)} кварталов, берём первые 4")
            vals = vals[:4]
        annual_value = round(sum(vals) / 4, 4)
        results.append((year, annual_value))
    if skipped:
        log.info(f"Пропущены неполные годы: {', '.join(skipped)}")
    return results


def upsert(conn, indicator_id: int, rows: list[tuple[int, float]]) -> int:
    data = [
        (indicator_id, date(year, 1, 1), str(year), value, False)
        for year, value in rows
    ]
    with conn.cursor() as cur:
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
        log.info("Обновляю materialized view ...")
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    conn.commit()
    return len(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Расчёт {DST_CODE} = среднее 4 кварталов {SRC_CODE}"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Не записывать в БД, только показать расчёт")
    args = parser.parse_args()

    log.info(f"=== {DST_CODE}: авто-расчёт из квартальных данных {SRC_CODE} ===")
    if args.dry_run:
        log.info("Режим DRY RUN")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            src_id = get_indicator_id(cur, SRC_CODE)
            dst_id = get_indicator_id(cur, DST_CODE)

        with conn.cursor() as cur:
            quarterly = fetch_quarterly(cur, src_id)

        log.info(f"Загружено лет с квартальными данными: {len(quarterly)}")
        if not quarterly:
            log.error(f"Нет квартальных данных для {SRC_CODE}.")
            sys.exit(1)

        rows = calc_annual(quarterly)
        log.info(f"Рассчитано полных лет: {len(rows)}")

        if args.dry_run:
            log.info("─" * 50)
            for year, val in rows:
                qs = quarterly.get(year, [])
                log.info(f"  {year}: avg({', '.join(f'{v:.0f}' for v in qs)}) = {val:.2f}")
            log.info("─" * 50)
            log.info("DRY RUN: БД не изменена.")
            return len(rows)

        n = upsert(conn, dst_id, rows)
        log.info(f"✅ Upserted {n} строк для {DST_CODE}")
        return n

    except Exception as e:
        log.error(f"Ошибка: {e}")
        if conn and not conn.closed:
            conn.rollback()
        sys.exit(1)
    finally:
        if conn and not conn.closed:
            conn.close()


if __name__ == "__main__":
    main()
