"""
migration/migrate_sales_matrix.py

Рассчитывает показатели из файла «Матрица продаж» (накопительный xlsx).

Показатели:
  Квартиры:
    5.8_recalc  — количество сделок с квартирами (шт./мес)     [пересчёт с 2021]
    4.1_recalc  — средняя цена 1 кв. м квартир (руб.)          [пересчёт с 2021]
    apt_budget  — средний бюджет сделки по квартирам (руб.)     [новый]
    apt_area    — средняя площадь сделки по квартирам (кв. м)   [новый]

  Машиноместа:
    mm_count    — количество сделок с машиноместами (шт./мес)
    mm_price    — средняя цена 1 кв. м машиноместа (руб.)
    mm_budget   — средний бюджет машиноместа (руб.)
    mm_area     — средняя площадь машиноместа (кв. м)

Использование:
    python migration/migrate_sales_matrix.py [путь_к_файлу.xlsx]

    Если путь не указан — ищет единственный *.xlsx в
    migration/domrf_data/sales_matrix/

Логика пересчёта:
    - Пересчитываются только предыдущий полный год и текущий неполный год
    - Более ранние периоды не трогаются
    - Для 5.8 и 4.1 дополнительно сохраняются данные за 2020 год
    - Расторжения НЕ вычитаются (используются только столбцы «Продано»)
    - Агрегация: группировка по столбцу «Месяц» (строка «Январь 2025»)
    - period_date: первый день месяца
"""

import os
import re
import sys
from pathlib import Path
from datetime import date

import psycopg2
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent / 'domrf_data' / 'sales_matrix'

# Маппинг indicator.code → что считаем
# (числитель_столбец, знаменатель_столбец_или_None)
# Если знаменатель None → просто sum(числитель)
INDICATORS = {
    '5.8':          ('Продано квартир, шт.',  None),
    '4.1':          ('Продано квартир, руб.', 'Продано квартир, м2'),
    'apt_budget':   ('Продано квартир, руб.', 'Продано квартир, шт.'),
    'apt_area':     ('Продано квартир, м2',  'Продано квартир, шт.'),
    'sales_apt_sqm':('Продано квартир, м2',  None),   # суммарная площадь продаж, кв. м
    'mm_count':     ('Продано машиномест, шт.',  None),
    'mm_price':     ('Продано машиномест, руб.', 'Продано машиномест, м2'),
    'mm_budget':    ('Продано машиномест, руб.', 'Продано машиномест, шт.'),
    'mm_area':      ('Продано машиномест, м2',   'Продано машиномест, шт.'),
    # Публичные коды 4.8/4.9 — те же формулы, что mm_price/mm_budget
    '4.8':          ('Продано машиномест, руб.', 'Продано машиномест, м2'),
    '4.9':          ('Продано машиномест, руб.', 'Продано машиномест, шт.'),
}

MONTHS_RU_TO_NUM = {
    'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4,
    'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
    'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12,
}
MONTHS_RU_FROM_NUM = {v: k for k, v in MONTHS_RU_TO_NUM.items()}


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def parse_period(month_str: str) -> object:
    """'Январь 2025' → date(2025, 1, 1)"""
    if not isinstance(month_str, str):
        return None
    m = re.match(r'(\w+)\s+(\d{4})', month_str.strip())
    if not m:
        return None
    mon_name, year = m.group(1), int(m.group(2))
    mon_num = MONTHS_RU_TO_NUM.get(mon_name)
    if not mon_num:
        return None
    return date(year, mon_num, 1)


def main():
    # Находим файл
    if len(sys.argv) > 1:
        filepath = Path(sys.argv[1])
    else:
        files = list(DATA_DIR.glob('*.xlsx'))
        if not files:
            print(f"Нет xlsx-файлов в {DATA_DIR}")
            sys.exit(1)
        if len(files) > 1:
            print(f"Найдено несколько файлов: {[f.name for f in files]}")
            print("Укажите путь явно: python migrate_sales_matrix.py <путь>")
            sys.exit(1)
        filepath = files[0]

    if not filepath.exists():
        print(f"Файл не найден: {filepath}")
        sys.exit(1)

    print(f"Читаю {filepath.name} ...")
    df = pd.read_excel(filepath, dtype={'Год': 'Int64'})

    # Нужные столбцы
    required_cols = ['Месяц'] + list({
        col
        for num_col, den_col in INDICATORS.values()
        for col in ([num_col] + ([den_col] if den_col else []))
    })
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"ОШИБКА: Не найдены столбцы: {missing}")
        sys.exit(1)

    # Преобразуем числовые столбцы
    num_cols = [c for c in required_cols if c != 'Месяц']
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Парсим даты
    df['_period_date'] = df['Месяц'].map(parse_period)
    df = df.dropna(subset=['_period_date'])

    # Определяем окно пересчёта: предыдущий год + текущий год
    current_year = date.today().year
    recalc_from = date(current_year - 1, 1, 1)
    print(f"Окно пересчёта: с {recalc_from} (предыдущий + текущий год)")

    # Агрегируем по периоду
    agg_dict = {col: 'sum' for col in num_cols}
    grouped = df.groupby('_period_date').agg(agg_dict).reset_index()

    # Оставляем только строки в окне пересчёта
    grouped = grouped[grouped['_period_date'] >= recalc_from]
    print(f"Периодов в окне пересчёта: {len(grouped)}")

    if grouped.empty:
        print("Нет данных в окне пересчёта — выход.")
        return

    conn = get_db_conn()
    cur = conn.cursor()

    # Получаем indicator_id
    all_codes = list(INDICATORS.keys())
    cur.execute("SELECT code, id FROM indicators WHERE code = ANY(%s)", (all_codes,))
    code_to_id = dict(cur.fetchall())

    missing_indicators = [c for c in all_codes if c not in code_to_id]
    if missing_indicators:
        print(f"ОШИБКА: Индикаторы не найдены в БД: {missing_indicators}")
        print("Добавьте их командой (см. SQL ниже) и повторите.")
        print_setup_sql()
        sys.exit(1)

    # Удаляем только данные в окне пересчёта
    for code, indicator_id in code_to_id.items():
        cur.execute(
            "DELETE FROM data_points WHERE indicator_id = %s AND period_date >= %s",
            (indicator_id, recalc_from)
        )
        print(f"  [{code}] Удалено точек: {cur.rowcount}")


    # Вставляем новые данные
    inserted_counts = {code: 0 for code in all_codes}

    for _, row in grouped.iterrows():
        period_date: date = row['_period_date']
        label = f"{MONTHS_RU_FROM_NUM[period_date.month]} {period_date.year}"

        for code, (num_col, den_col) in INDICATORS.items():

            numerator = float(row[num_col])

            if den_col is None:
                value = round(numerator, 4) if numerator > 0 else None
            else:
                denominator = float(row[den_col])
                if denominator == 0:
                    value = None
                else:
                    value = round(numerator / denominator, 4)

            if value is None:
                continue

            cur.execute("""
                INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
                VALUES (%s, %s, %s, %s, false)
                ON CONFLICT (indicator_id, period_date) DO UPDATE
                    SET value = EXCLUDED.value,
                        period_label = EXCLUDED.period_label
            """, (code_to_id[code], period_date, label, value))
            inserted_counts[code] += 1

    print("\nОбновляю materialized view ...", end=' ')
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    print("готово")

    conn.commit()
    cur.close()
    conn.close()

    print("\nРезультат:")
    for code, cnt in inserted_counts.items():
        print(f"  [{code}] Записано точек: {cnt}")
    print(f"Upserted: {sum(inserted_counts.values())} rows")


def print_setup_sql():
    print("""
-- SQL для создания недостающих индикаторов:

DO $$
DECLARE
    cat_demand  INT := (SELECT id FROM categories WHERE code = 'demand');
    cat_prices  INT := (SELECT id FROM categories WHERE code = 'prices');
    src_domrf   INT := (SELECT id FROM sources WHERE code = 'domrf');
BEGIN
    INSERT INTO indicators (code, category_id, source_id, name, unit, periodicity, period_type, chart_type, sort_order)
    VALUES
      -- Квартиры (машиноместа и новые показатели)
      ('apt_budget', cat_demand, src_domrf, 'Средний бюджет сделки по квартирам', 'руб.', 'monthly', 'period', 'line', 25),
      ('apt_area',   cat_demand, src_domrf, 'Средняя площадь квартиры в сделке', 'кв. м', 'monthly', 'period', 'line', 26),
      ('mm_count',   cat_demand, src_domrf, 'Количество сделок с машиноместами', 'шт.', 'monthly', 'period', 'bar', 30),
      ('mm_price',   cat_prices, src_domrf, 'Средняя цена 1 кв. м машиноместа', 'руб./кв. м', 'monthly', 'period', 'line', 31),
      ('mm_budget',  cat_prices, src_domrf, 'Средний бюджет машиноместа', 'руб.', 'monthly', 'period', 'line', 32),
      ('mm_area',    cat_demand, src_domrf, 'Средняя площадь машиноместа в сделке', 'кв. м', 'monthly', 'period', 'line', 33)
    ON CONFLICT (code) DO NOTHING;
END $$;
""")


if __name__ == '__main__':
    main()
