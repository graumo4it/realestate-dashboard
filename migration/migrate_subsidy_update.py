#!/usr/bin/env python3
"""
Обновление данных раздела «Ипотека (льготные программы)»:
1. Переименовать категорию mortgage_subsidy → «Ипотека (льготные программы)»
2. Обновить данные Jan 2018 – Mar 2026 из листа 01_02_01
3. Создать индикаторы 6.44/6.45 для «Ипотеки в отдельных регионах»

Маппинг кодов БД:
  6.36 = Семейная (кол-во)      6.37 = Семейная (объём)
  6.38 = Льготная (кол-во)      6.39 = Льготная (объём)
  6.40 = Дальневосточная (кол-во) 6.41 = Дальневосточная (объём)
  6.42 = IT (кол-во)            6.43 = IT (объём)
  6.44 = Регионы (кол-во) NEW   6.45 = Регионы (объём) NEW

Маппинг строк Excel (лист 01_02_01):
  строка 4  = Все программы (кол-во)      → не загружаем, нет такого кода в БД
  строка 5  = Все программы (объём)       → не загружаем
  строка 6  = Льготная (кол-во)           → 6.38
  строка 7  = Льготная (объём)            → 6.39
  строка 8  = Семейная (кол-во)           → 6.36
  строка 9  = Семейная (объём)            → 6.37
  строка 10 = Дальневосточная (кол-во)    → 6.40
  строка 11 = Дальневосточная (объём)     → 6.41
  строка 12 = IT (кол-во)                 → 6.42
  строка 13 = IT (объём)                  → 6.43
  строка 14 = Регионы (кол-во)            → 6.44 (новый)
  строка 15 = Регионы (объём)             → 6.45 (новый)

Запуск:
  python migrate_subsidy_update.py путь/к/Статистические_ряды.xlsx
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

EXCEL_PATH = sys.argv[1] if len(sys.argv) > 1 else "migration/data/file.xlsx"
SHEET = "01_02_01"

ROW_TO_CODE = {
    (6,  "шт."):      "6.38",   # Льготная — количество (завершена)
    (7,  "млн руб."): "6.39",   # Льготная — объём (завершена)
    (8,  "шт."):      "6.36",   # Семейная — количество
    (9,  "млн руб."): "6.37",   # Семейная — объём
    (10, "шт."):      "6.40",   # Дальневосточная — количество
    (11, "млн руб."): "6.41",   # Дальневосточная — объём
    (12, "шт."):      "6.42",   # IT — количество
    (13, "млн руб."): "6.43",   # IT — объём
    (14, "шт."):      "6.44",   # Ипотека в отдельных регионах — количество (новый)
    (15, "млн руб."): "6.45",   # Ипотека в отдельных регионах — объём (новый)
}

MONTHS_RU = ["Январь","Февраль","Март","Апрель","Май","Июнь",
              "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]


def period_label(dt):
    return f"{MONTHS_RU[dt.month - 1]} {dt.year}"


def main():
    print(f"Читаем {EXCEL_PATH}, лист {SHEET}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET, header=None)

    # Даты: строка 3, столбцы 12–110 (янв 2018 – мар 2026)
    date_cols = {}
    for col in range(12, 111):
        val = df.iloc[3, col]
        if pd.notna(val) and isinstance(val, datetime.datetime):
            date_cols[col] = val

    print(f"Дат: {len(date_cols)} | {min(date_cols.values()):%Y-%m} – {max(date_cols.values()):%Y-%m}")

    # Читаем данные
    data_by_code = {}
    for (row_idx, unit_part), code in ROW_TO_CODE.items():
        unit_cell = str(df.iloc[row_idx, 1])
        if unit_part not in unit_cell:
            print(f"  ОШИБКА {code}: строка {row_idx} содержит '{unit_cell}', ожидалось '{unit_part}'")
            continue
        prog_name = str(df.iloc[row_idx, 0]).strip()
        points = []
        for col, dt in date_cols.items():
            raw = df.iloc[row_idx, col]
            val = float(raw) if pd.notna(raw) else None
            # Льготная: нули с 2025 → NULL (программа завершена)
            if code in ("6.38", "6.39") and val == 0.0:
                val = None
            points.append((dt, val))
        data_by_code[code] = points
        non_null = sum(1 for _, v in points if v is not None)
        print(f"  {code} ({prog_name}): {non_null}/{len(points)} значений")

    print("\nПодключаемся к БД...")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # 1. Переименовать категорию
    cur.execute("UPDATE categories SET name = 'Ипотека (льготные программы)' WHERE code = 'mortgage_subsidy'")
    print(f"Категория mortgage_subsidy: обновлено {cur.rowcount} строк")

    # 2. Создать/обновить индикаторы 6.44 и 6.45
    cur.execute("SELECT id FROM categories WHERE code = 'mortgage_subsidy'")
    cat_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM sources WHERE code = 'domrf'")
    src_id = cur.fetchone()[0]

    for code, name, unit, sort_order in [
        ("6.44", "Ипотека в отдельных регионах: количество кредитов", "ед.", 44),
        ("6.45", "Ипотека в отдельных регионах: объём кредитов", "млн руб.", 45),
    ]:
        cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE indicators SET name=%s, unit=%s, category_id=%s, source_id=%s, sort_order=%s WHERE code=%s",
                (name, unit, cat_id, src_id, sort_order, code)
            )
            print(f"  {code} обновлён: {name}")
        else:
            cur.execute("""
                INSERT INTO indicators
                  (code, category_id, source_id, name, unit, periodicity,
                   period_type, geo_level, is_public, chart_type, sort_order)
                VALUES (%s,%s,%s,%s,%s,'monthly','period','russia',true,'bar',%s)
            """, (code, cat_id, src_id, name, unit, sort_order))
            print(f"  {code} создан: {name}")

    # 3. Загрузить данные
    for code, points in data_by_code.items():
        cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        if not row:
            print(f"  ПРОПУСК {code}: не найден в БД")
            continue
        ind_id = row[0]
        rows = [(ind_id, dt.date(), period_label(dt), val, False) for dt, val in points]
        execute_values(cur, """
            INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO UPDATE
              SET value = EXCLUDED.value,
                  period_label = EXCLUDED.period_label,
                  is_preliminary = EXCLUDED.is_preliminary
        """, rows)
        print(f"  Upsert {code}: {len(rows)} строк")

    # 4. Refresh materialized view
    print("Обновляем materialized view...")
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")

    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ Готово!")


if __name__ == "__main__":
    main()
