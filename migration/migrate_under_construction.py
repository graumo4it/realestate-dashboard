#!/usr/bin/env python3
"""
Обновление данных раздела «Строящееся жильё»:
Загрузить/обновить данные янв 2020 – апр 2026 из листа 01_01_00

Маппинг кодов БД → строки Excel:
  3.1 = Количество возводимых МКД, шт.          → строка 4, делитель 1
  3.2 = Общая площадь возводимых МКД, млн кв.м  → строка 5, делитель 1_000_000
  3.3 = Жилая площадь возводимых МКД, млн кв.м  → строка 6, делитель 1_000_000
  3.4 = Количество квартир в МКД, млн шт.       → строка 7, делитель 1_000_000

Примечание: делители соответствуют первичной миграции из ТЗ
  (UPDATE data_points SET value = value / 1000000 WHERE code IN ('3.2','3.3','3.4'))

Запуск:
  python migrate_under_construction.py путь/к/01_01_stockvariablesexsales.xlsx
"""

import sys, os, datetime
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

DB = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME", "realestate"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

EXCEL_PATH = sys.argv[1] if len(sys.argv) > 1 else "migration/data/01_01_stockvariablesexsales.xlsx"
SHEET = "01_01_00"

# (строка Excel, делитель) → код индикатора
ROW_TO_CODE = {
    (4, 1):         "3.1",
    (5, 1_000_000): "3.2",
    (6, 1_000_000): "3.3",
    (7, 1_000_000): "3.4",
}

# Строка с датами для первого блока данных
DATE_HEADER_ROW = 3

MONTHS_RU = ["Январь","Февраль","Март","Апрель","Май","Июнь",
              "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]


def period_label(dt):
    return f"{MONTHS_RU[dt.month - 1]} {dt.year}"


def main():
    print(f"Читаем {EXCEL_PATH}, лист {SHEET}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET, header=None)

    # Даты: строка 3, столбцы 2..77
    date_cols = {}
    for col in range(2, 78):
        val = df.iloc[DATE_HEADER_ROW, col]
        if pd.notna(val) and isinstance(val, datetime.datetime):
            date_cols[col] = val

    print(f"Дат: {len(date_cols)} | {min(date_cols.values()):%Y-%m} – {max(date_cols.values()):%Y-%m}")

    # Читаем данные с масштабированием
    data_by_code = {}
    for (row_idx, divisor), code in ROW_TO_CODE.items():
        name = str(df.iloc[row_idx, 1]).strip()
        points = []
        for col, dt in date_cols.items():
            raw = df.iloc[row_idx, col]
            val = (float(raw) / divisor) if pd.notna(raw) else None
            points.append((dt, val))
        data_by_code[code] = points
        non_null = sum(1 for _, v in points if v is not None)
        print(f"  {code} ({name[:55]}): {non_null}/{len(points)} значений, делитель={divisor:,}")

    print("\nПодключаемся к БД...")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    for code, points in data_by_code.items():
        cur.execute("SELECT id, name FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        if not row:
            print(f"  ПРОПУСК {code}: не найден в БД")
            continue
        ind_id, ind_name = row

        rows = [(ind_id, dt.date(), period_label(dt), val, False) for dt, val in points]
        execute_values(cur, """
            INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO UPDATE
              SET value = EXCLUDED.value,
                  period_label = EXCLUDED.period_label,
                  is_preliminary = EXCLUDED.is_preliminary
        """, rows)
        print(f"  Upsert {code} ({ind_name[:45]}): {len(rows)} строк")

    print("Обновляем materialized view...")
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")

    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ Готово!")


if __name__ == "__main__":
    main()
