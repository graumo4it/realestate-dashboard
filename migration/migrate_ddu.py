"""
migration/migrate_ddu.py

Пересобирает данные показателя 5.1 — количество ДДУ:
- Переименовывает показатель (добавляет источник Росреестр)
- Удаляет все существующие данные
- Загружает квартальные данные из Excel-файла
- Меняет periodicity с 'monthly' на 'quarterly'

Использование:
    python migration/migrate_ddu.py [путь_к_файлу.xlsx]

    Если путь не указан — ищет данные_по_дду.xlsx рядом со скриптом
    или в migration/data/
"""

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from datetime import date
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

INDICATOR_CODE = '5.1'
NEW_NAME = 'Общее количество зарегистрированных договоров участия в долевом строительстве за период (Росреестр)'


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def quarter_to_date(quarter: int, year: int) -> date:
    """Q1 2010 → 2010-01-01, Q2 → 2010-04-01, Q3 → 2010-07-01, Q4 → 2010-10-01"""
    month = (quarter - 1) * 3 + 1
    return date(year, month, 1)


def quarter_label(quarter: int, year: int) -> str:
    return f"Q{quarter} {year}"


def main():
    # Находим файл
    if len(sys.argv) > 1:
        filepath = Path(sys.argv[1])
    else:
        candidates = [
            Path(__file__).parent / 'данные_по_дду.xlsx',
            Path(__file__).parent / 'data' / 'данные_по_дду.xlsx',
        ]
        filepath = next((p for p in candidates if p.exists()), None)
        if not filepath:
            print("Файл не найден. Укажите путь: python migrate_ddu.py <путь>")
            sys.exit(1)

    print(f"Файл: {filepath}")

    # Читаем Excel
    df = pd.read_excel(filepath)
    print(f"Столбцы: {list(df.columns)}")
    print(df)

    # Строки: кварталы 1-4, последняя строка — «Итого»
    # Фильтруем только строки с числовыми кварталами
    df = df[pd.to_numeric(df['Квартал'], errors='coerce').notna()].copy()
    df['Квартал'] = df['Квартал'].astype(int)

    # Собираем временной ряд
    records = []
    year_cols = [c for c in df.columns if c != 'Квартал' and isinstance(c, (int, float))]

    for _, row in df.iterrows():
        quarter = int(row['Квартал'])
        for year_col in year_cols:
            val = row[year_col]
            if pd.isna(val):
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            year = int(year_col)
            period_date = quarter_to_date(quarter, year)
            label = quarter_label(quarter, year)
            records.append((period_date, label, round(val)))

    records.sort(key=lambda x: x[0])
    print(f"\nПериодов для загрузки: {len(records)}")
    print(f"Диапазон: {records[0][0]} – {records[-1][0]}")

    conn = get_db_conn()
    cur = conn.cursor()

    # Получаем indicator_id
    cur.execute("SELECT id FROM indicators WHERE code = %s", (INDICATOR_CODE,))
    row = cur.fetchone()
    if not row:
        print(f"ОШИБКА: индикатор {INDICATOR_CODE} не найден в БД")
        sys.exit(1)
    indicator_id = row[0]

    # Переименовываем и меняем periodicity
    cur.execute("""
        UPDATE indicators
        SET name = %s,
            periodicity = 'quarterly'
        WHERE code = %s
    """, (NEW_NAME, INDICATOR_CODE))
    print(f"\nПереименован индикатор: {NEW_NAME}")
    print(f"periodicity → quarterly")

    # Удаляем все существующие данные
    cur.execute("DELETE FROM data_points WHERE indicator_id = %s", (indicator_id,))
    print(f"Удалено существующих точек: {cur.rowcount}")

    # Вставляем новые данные
    inserted = 0
    for period_date, label, val in records:
        cur.execute("""
            INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES (%s, %s, %s, %s, false)
            ON CONFLICT (indicator_id, period_date) DO UPDATE
                SET value = EXCLUDED.value,
                    period_label = EXCLUDED.period_label
        """, (indicator_id, period_date, label, val))
        inserted += 1

    print(f"Записано точек: {inserted}")

    print("\nОбновляю materialized view ...", end=' ')
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    print("готово")

    conn.commit()
    cur.close()
    conn.close()
    print("\nГотово.")


if __name__ == '__main__':
    main()
