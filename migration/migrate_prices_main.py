"""
migrate_prices_main.py

Добавляет/обновляет в БД индикаторы 4.4 и 4.5 как квартальные данные (Q1-Q4).

4.4 — был загружен как годовой (строка «Среднее за год») — заменяем на квартальные Q1-Q4
4.5 — не был загружен вообще (нет строки «Среднее за год») — добавляем квартальные Q1-Q4

Использование:
  python3 migration/migrate_prices_main.py "migration/data/file.xlsx"
"""

import os, sys, math, logging
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

SHEET_NAME = "4.4-4.5 Цены (Росстат)"
CATEGORY_CODE = "prices"
SOURCE_CODE = "rosstat"

# 4.4: строка заголовка «Квартал» = строка 5, данные = строки 6-9
# 4.5: строка заголовка «Квартал» = строка 36, данные = строки 37-40
MAIN_INDICATORS = [
    {
        "header_row": 5,
        "data_rows": [6, 7, 8, 9],
        "code": "4.4",
        "name": "Средняя стоимость 1 кв. м на первичном рынке (все типы квартир)",
        "unit": "руб. / кв. м",
        "sort_order": 10,
    },
    {
        "header_row": 36,
        "data_rows": [37, 38, 39, 40],
        "code": "4.5",
        "name": "Средняя стоимость 1 кв. м на вторичном рынке (все типы квартир)",
        "unit": "руб. / кв. м",
        "sort_order": 11,
    },
]

QUARTER_TO_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}
QUARTER_LABELS   = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def to_float(v):
    if v is None: return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except: return None


def get_id(conn, table, code):
    with conn.cursor() as cur:
        cur.execute(f"SELECT id FROM {table} WHERE code = %s", (code,))
        row = cur.fetchone()
        if not row: raise ValueError(f"Не найдено в {table}: {code}")
        return row[0]


def upsert_indicator(conn, code, name, unit, category_id, source_id, sort_order):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO indicators
                (code, name, unit, periodicity, period_type, geo_level,
                 category_id, source_id, sort_order, is_public, chart_type)
            VALUES (%s, %s, %s, 'quarterly', 'period', 'russia', %s, %s, %s, TRUE, 'line')
            ON CONFLICT (code) DO UPDATE SET
                name        = EXCLUDED.name,
                unit        = EXCLUDED.unit,
                periodicity = 'quarterly',
                period_type = 'period',
                last_updated = NOW()
            RETURNING id
        """, (code, name, unit, category_id, source_id, sort_order))
        return cur.fetchone()[0]


def upsert_points(conn, indicator_id, points):
    if not points: return 0
    # Сначала удаляем старые данные (они были годовые — неправильные)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM data_points WHERE indicator_id = %s", (indicator_id,))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO data_points (indicator_id, period_date, period_label, value)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO UPDATE SET value = EXCLUDED.value
        """, [(indicator_id, p["date"], p["label"], p["value"]) for p in points])
    return len(points)


def parse_quarters(df, ind):
    year_headers = df.iloc[ind["header_row"]].tolist()
    year_cols = {}
    for ci, val in enumerate(year_headers):
        try:
            y = int(float(str(val)))
            if 2000 <= y <= 2030:
                year_cols[ci] = y
        except: pass

    points = []
    for row_idx in ind["data_rows"]:
        row = df.iloc[row_idx].tolist()
        try: q = int(float(str(row[0])))
        except: continue
        if q not in QUARTER_TO_MONTH: continue
        month = QUARTER_TO_MONTH[q]
        for ci, year in year_cols.items():
            v = to_float(row[ci] if ci < len(row) else None)
            if v is None: continue
            d = date(year, month, 1)
            points.append({"date": d, "label": f"{QUARTER_LABELS[q]} {year}", "value": v})
    return points


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 migrate_prices_main.py path/to/excel.xlsx")
        sys.exit(1)

    filepath = sys.argv[1]
    log.info(f"Файл: {filepath}\nЛист: {SHEET_NAME}\n")

    df = pd.read_excel(filepath, sheet_name=SHEET_NAME, header=None)
    conn = get_conn()
    cat_id = get_id(conn, "categories", CATEGORY_CODE)
    src_id = get_id(conn, "sources",    SOURCE_CODE)
    total  = 0

    for ind in MAIN_INDICATORS:
        try:
            points = parse_quarters(df, ind)
            iid    = upsert_indicator(conn, ind["code"], ind["name"], ind["unit"],
                                      cat_id, src_id, ind["sort_order"])
            n      = upsert_points(conn, iid, points)
            conn.commit()
            total += n
            first = points[0]  if points else None
            last  = points[-1] if points else None
            log.info(f"[OK] {ind['code']} — {n} точек | "
                     f"{first['date'] if first else '—'} … {last['date'] if last else '—'} | "
                     f"последнее={last['value'] if last else '—':.0f} руб.")
        except Exception as e:
            conn.rollback()
            log.error(f"[ERROR] {ind['code']}: {e}")
            import traceback; traceback.print_exc()

    try:
        log.info("\nОбновление materialized view...")
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
        conn.commit()
        log.info("Готово.")
    except Exception as e:
        log.error(f"Ошибка view: {e}")

    conn.close()
    log.info(f"\nИтого загружено точек: {total}")


if __name__ == "__main__":
    main()
