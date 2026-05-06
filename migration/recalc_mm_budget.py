"""
migration/recalc_mm_budget.py

Пересчитывает mm_budget (средний бюджет машиноместа, млн руб.)
за весь доступный период из полного файла Матрицы продаж.

Использование:
    python migration/recalc_mm_budget.py
"""

import os, re, sys
from pathlib import Path
from datetime import date
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

DATA_DIR = Path(__file__).parent / 'domrf_data' / 'sales_matrix'

MONTHS = {'Январь':1,'Февраль':2,'Март':3,'Апрель':4,'Май':5,'Июнь':6,
          'Июль':7,'Август':8,'Сентябрь':9,'Октябрь':10,'Ноябрь':11,'Декабрь':12}
MONTHS_R = {v: k for k, v in MONTHS.items()}


def parse_period(s):
    if not isinstance(s, str): return None
    m = re.match(r'(\w+)\s+(\d{4})', s.strip())
    if not m: return None
    mn = MONTHS.get(m.group(1))
    return date(int(m.group(2)), mn, 1) if mn else None


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def main():
    files = [f for f in DATA_DIR.glob('*.xlsx') if not f.name.startswith('~$')]
    if not files:
        print(f"Файл не найден в {DATA_DIR}")
        sys.exit(1)
    filepath = files[0]
    print(f"Файл: {filepath.name}")

    print("Читаю файл...")
    df = pd.read_excel(filepath)
    df['_date'] = df['Месяц'].map(parse_period)
    df = df.dropna(subset=['_date'])

    for col in ['Продано машиномест, руб.', 'Продано машиномест, шт.']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    grouped = df.groupby('_date').agg({
        'Продано машиномест, руб.': 'sum',
        'Продано машиномест, шт.':  'sum',
    }).reset_index()

    grouped['mm_budget'] = grouped.apply(
        lambda r: round(r['Продано машиномест, руб.'] / r['Продано машиномест, шт.'] / 1_000_000, 1)
        if r['Продано машиномест, шт.'] > 0 else None, axis=1
    )

    print(f"Периодов: {len(grouped)}, диапазон: {grouped['_date'].min()} – {grouped['_date'].max()}")

    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM indicators WHERE code = 'mm_budget'")
    row = cur.fetchone()
    if not row:
        print("ОШИБКА: индикатор mm_budget не найден в БД")
        sys.exit(1)
    ind_id = row[0]

    cur.execute("DELETE FROM data_points WHERE indicator_id = %s", (ind_id,))
    print(f"Удалено существующих точек: {cur.rowcount}")

    inserted = 0
    for _, row in grouped.iterrows():
        if row['mm_budget'] is None:
            continue
        pd_ = row['_date']
        label = f"{MONTHS_R[pd_.month]} {pd_.year}"
        cur.execute("""
            INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES (%s, %s, %s, %s, false)
            ON CONFLICT (indicator_id, period_date) DO UPDATE
                SET value = EXCLUDED.value, period_label = EXCLUDED.period_label
        """, (ind_id, pd_, label, row['mm_budget']))
        inserted += 1

    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    conn.commit()
    cur.close()
    conn.close()
    print(f"Записано точек: {inserted}")


if __name__ == '__main__':
    main()
