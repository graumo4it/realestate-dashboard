"""
migrate_prices_subtypes.py

Миграция данных по типам квартир из листа «4.4-4.5 Цены (Росстат)» в PostgreSQL.

Добавляет в БД 7 новых индикаторов (квартальные данные, 2017–2025):

Первичный рынок (4.4.*):
  4.4.1 — Квартиры среднего качества (типовые)
  4.4.2 — Квартиры улучшенного качества
  4.4.3 — Элитные квартиры

Вторичный рынок (4.5.*):
  4.5.1 — Квартиры низкого качества
  4.5.2 — Квартиры среднего качества (типовые)
  4.5.3 — Квартиры улучшенного качества
  4.5.4 — Элитные квартиры

Данные квартальные (period_type='period', periodicity='quarterly').
Дата квартала: первый день первого месяца квартала (Q1 → 01.01, Q2 → 01.04 и т.д.)

Использование:
  python migrate_prices_subtypes.py path/to/excel.xlsx

Требует .env в родительской папке: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import sys
import math
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ── Конфиг ───────────────────────────────────────────────────────────────────

SHEET_NAME = "4.4-4.5 Цены (Росстат)"
CATEGORY_CODE = "prices"
SOURCE_CODE = "rosstat"

# Карта: (строка заголовка, код индикатора, полное название)
# строка заголовка — текст в col 0, предшествующий строке «Квартал»
SUBTYPES = [
    # Первичный рынок
    {
        "header_row": 12,   # строка «Квартиры среднего качества (типовые)» для первичного
        "data_rows": [14, 15, 16, 17],
        "code": "4.4.1",
        "name": "Средняя стоимость 1 кв. м на первичном рынке — квартиры среднего качества (типовые)",
        "unit": "руб.",
    },
    {
        "header_row": 19,
        "data_rows": [21, 22, 23, 24],
        "code": "4.4.2",
        "name": "Средняя стоимость 1 кв. м на первичном рынке — квартиры улучшенного качества",
        "unit": "руб.",
    },
    {
        "header_row": 26,
        "data_rows": [28, 29, 30, 31],
        "code": "4.4.3",
        "name": "Средняя стоимость 1 кв. м на первичном рынке — элитные квартиры",
        "unit": "руб.",
    },
    # Вторичный рынок
    {
        "header_row": 42,
        "data_rows": [44, 45, 46, 47],
        "code": "4.5.1",
        "name": "Средняя стоимость 1 кв. м на вторичном рынке — квартиры низкого качества",
        "unit": "руб.",
    },
    {
        "header_row": 49,
        "data_rows": [51, 52, 53, 54],
        "code": "4.5.2",
        "name": "Средняя стоимость 1 кв. м на вторичном рынке — квартиры среднего качества (типовые)",
        "unit": "руб.",
    },
    {
        "header_row": 56,
        "data_rows": [58, 59, 60, 61],
        "code": "4.5.3",
        "name": "Средняя стоимость 1 кв. м на вторичном рынке — квартиры улучшенного качества",
        "unit": "руб.",
    },
    {
        "header_row": 63,
        "data_rows": [65, 66, 67, 68],
        "code": "4.5.4",
        "name": "Средняя стоимость 1 кв. м на вторичном рынке — элитные квартиры",
        "unit": "руб.",
    },
]

# Q → первый месяц квартала
QUARTER_TO_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}
QUARTER_LABELS = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}


# ── Подключение к БД ─────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ── Вспомогательные ─────────────────────────────────────────────────────────

def to_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def get_category_id(conn, code):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM categories WHERE code = %s", (code,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Категория '{code}' не найдена в БД")
        return row[0]


def get_source_id(conn, code):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sources WHERE code = %s", (code,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Источник '{code}' не найден в БД")
        return row[0]


def upsert_indicator(conn, code, name, unit, category_id, source_id, sort_order):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO indicators
                (code, name, unit, periodicity, period_type, geo_level,
                 category_id, source_id, sort_order, is_public, chart_type)
            VALUES
                (%s, %s, %s, 'quarterly', 'period', 'russia',
                 %s, %s, %s, TRUE, 'line')
            ON CONFLICT (code) DO UPDATE SET
                name        = EXCLUDED.name,
                unit        = EXCLUDED.unit,
                periodicity = EXCLUDED.periodicity,
                period_type = EXCLUDED.period_type,
                category_id = EXCLUDED.category_id,
                source_id   = EXCLUDED.source_id,
                sort_order  = EXCLUDED.sort_order,
                last_updated = NOW()
            RETURNING id
        """, (code, name, unit, category_id, source_id, sort_order))
        return cur.fetchone()[0]


def upsert_data_points(conn, indicator_id, points):
    if not points:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO data_points (indicator_id, period_date, period_label, value)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO UPDATE SET
                value = EXCLUDED.value
        """, [(indicator_id, p["date"], p["label"], p["value"]) for p in points])
    return len(points)


# ── Основная логика ──────────────────────────────────────────────────────────

def parse_subtype(df, subtype):
    """Извлекает точки данных для одного подтипа."""
    # Строка заголовков годов — на строку ниже header_row
    year_row_idx = subtype["header_row"] + 1
    year_headers = df.iloc[year_row_idx].tolist()

    # Строим маппинг: col_index → год (только чистые годы, без динамики)
    year_cols = {}
    for ci, val in enumerate(year_headers):
        try:
            y = int(float(str(val)))
            if 2000 <= y <= 2030:
                year_cols[ci] = y
        except (ValueError, TypeError):
            pass

    points = []
    for row_idx in subtype["data_rows"]:
        row = df.iloc[row_idx].tolist()
        quarter_val = row[0]
        try:
            q = int(float(str(quarter_val)))
        except (ValueError, TypeError):
            continue
        if q not in QUARTER_TO_MONTH:
            continue

        month = QUARTER_TO_MONTH[q]
        for ci, year in year_cols.items():
            if ci >= len(row):
                continue
            v = to_float(row[ci])
            if v is None:
                continue
            d = date(year, month, 1)
            label = f"{QUARTER_LABELS[q]} {year}"
            points.append({"date": d, "label": label, "value": v})

    return points


def main():
    if len(sys.argv) < 2:
        print("Использование: python migrate_prices_subtypes.py path/to/excel.xlsx")
        sys.exit(1)

    filepath = sys.argv[1]
    log.info(f"Файл: {filepath}")
    log.info(f"Лист: {SHEET_NAME}\n")

    df = pd.read_excel(filepath, sheet_name=SHEET_NAME, header=None)
    log.info(f"Размер листа: {df.shape}")

    conn = get_conn()
    category_id = get_category_id(conn, CATEGORY_CODE)
    source_id = get_source_id(conn, SOURCE_CODE)

    total_points = 0

    for sort_idx, subtype in enumerate(SUBTYPES):
        code = subtype["code"]
        name = subtype["name"]
        unit = subtype["unit"]

        try:
            points = parse_subtype(df, subtype)
            ind_id = upsert_indicator(conn, code, name, unit, category_id, source_id, sort_idx + 100)
            n = upsert_data_points(conn, ind_id, points)
            conn.commit()
            total_points += n
            log.info(f"[OK] {code} — {len(points)} точек данных  |  {name[:60]}")
        except Exception as e:
            conn.rollback()
            log.error(f"[ERROR] {code}: {e}")
            import traceback; traceback.print_exc()

    # Обновляем materialized view
    try:
        log.info("\nОбновление materialized view...")
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
        conn.commit()
        log.info("Готово.")
    except Exception as e:
        log.error(f"Ошибка при обновлении view: {e}")

    conn.close()
    log.info(f"\nИтого загружено точек: {total_points}")


if __name__ == "__main__":
    main()
