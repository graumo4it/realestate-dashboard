#!/usr/bin/env python3
"""
Обновление раздела «Уровень концентрации»:
1. Скрыть индикатор 3.19 (ИХХ медианное) — is_public = false
2. Загрузить/обновить данные 3.18 (ИХХ средневзвешенное) и 3.19
   из листа 01_01_00 файла Excel, янв 2020 – апр 2026

Запуск:
  python migrate_ihh_update.py путь/к/01_01_stockvariablesexsales.xlsx
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

# Строки в листе (0-индексация):
#   строка 19 = ИХХ средневзвешенное → код 3.18
#   строка 20 = ИХХ медианное        → код 3.19
ROW_TO_CODE = {
    19: "3.18",
    20: "3.19",
}

# Заголовок блока «Концентрация» с датами — строка 17
DATE_HEADER_ROW = 17

MONTHS_RU = ["Январь","Февраль","Март","Апрель","Май","Июнь",
              "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]


def period_label(dt):
    return f"{MONTHS_RU[dt.month - 1]} {dt.year}"


def main():
    print(f"Читаем {EXCEL_PATH}, лист {SHEET}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET, header=None)

    # Находим столбцы с датами в строке 17, столбцы 2..77
    date_cols = {}
    for col in range(2, 78):
        val = df.iloc[DATE_HEADER_ROW, col]
        if pd.notna(val) and isinstance(val, datetime.datetime):
            date_cols[col] = val

    print(f"Дат: {len(date_cols)} | {min(date_cols.values()):%Y-%m} – {max(date_cols.values()):%Y-%m}")

    # Читаем данные
    data_by_code = {}
    for row_idx, code in ROW_TO_CODE.items():
        name = str(df.iloc[row_idx, 1]).strip()
        points = []
        for col, dt in date_cols.items():
            raw = df.iloc[row_idx, col]
            val = float(raw) if pd.notna(raw) else None
            points.append((dt, val))
        data_by_code[code] = points
        non_null = sum(1 for _, v in points if v is not None)
        print(f"  {code} ({name[:50]}): {non_null}/{len(points)} значений")

    print("\nПодключаемся к БД...")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # 1. Скрыть 3.19 (медианное) — убрать со страницы раздела
    cur.execute("UPDATE indicators SET is_public = false WHERE code = '3.19'")
    print(f"Индикатор 3.19 скрыт: {cur.rowcount} строк")

    # 2. Загрузить данные для обоих индикаторов (3.18 и 3.19)
    #    3.19 скрыт публично, но данные сохраняем — они нужны для ihh-chart.html
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
        print(f"  Upsert {code} ({ind_name[:40]}): {len(rows)} строк")

    # 3. Refresh materialized view
    print("Обновляем materialized view...")
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")

    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ Готово!")
    print("\nПримечание: ihh-chart.html напрямую запрашивает коды 3.18 и 3.19 через")
    print("/api/multi/data — is_public не влияет на этот эндпоинт, данные доступны.")


if __name__ == "__main__":
    main()
