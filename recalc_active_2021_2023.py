"""
recalc_active_2021_2023.py

Досчитывает показатели «активного строительства» за декабрь 2021 – ноябрь 2023
из обновлённых файлов Матрицы проектов (теперь содержат «Процент готовности по объекту»).

Что пересчитывается:
  uc_area_active         — Жилая площадь активного строительства, млн кв. м
  uc_stock_years_active  — Запасы строящегося жилья (активные), лет
  uc_absorption_active   — Коэффициент поглощения (активные), лет
  uc_new_vs_input_active — Новые проекты / ввод МЖС (активные), %
  uc_new_vs_sales_active — Обеспеченность продаж новыми запусками (активные), %

Особенности старых файлов (до дек 2023):
  - «Процент готовности по объекту» хранится как строка '80%' (не число)
  - Столбец называется 'Процент готовности по объекту' (без изменений)
  - Столбца «Первая ПД» нет → uc_new_active не пересчитывается

Использование:
    python recalc_active_2021_2023.py

Запускать из корня репозитория, .env должен быть там же.
"""

import os
import re
import sys
from pathlib import Path
from datetime import date, timedelta
from calendar import monthrange

import psycopg2
from dotenv import load_dotenv
from pyxlsb import open_workbook

# Ищем .env в родительских директориях
for env_path in [Path('.env'), Path('../.env'), Path(__file__).parent / '.env']:
    if env_path.exists():
        load_dotenv(env_path)
        break

MATRIX_DIR = Path(__file__).parent / 'migration' / 'domrf_data' / 'matrix_projects'

MONTHS_RU = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}

# Период досчёта
RECALC_FROM = date(2021, 12, 1)
RECALC_TO   = date(2023, 11, 1)

CODES_ACTIVE = [
    'uc_area_active',
    'uc_stock_years_active',
    'uc_absorption_active',
    'uc_new_vs_input_active',
    'uc_new_vs_sales_active',
]


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def parse_date_from_filename(filename: str):
    m = re.search(r'(\d{2})[._](\d{2})[._](\d{4})', filename)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(year, month, 1)


def find_matrix_files() -> list:
    files = []
    for pattern in ('*.xlsb', '*.xlsx'):
        files.extend(MATRIX_DIR.glob(pattern))
    return sorted([f for f in files if not f.name.startswith('~$')])


def safe_float_pct(v) -> float:
    """
    Парсит процент готовности. Поддерживает:
    - float/int  → возвращает как есть (если > 1, считает что уже в %)
    - '80%'      → 80.0
    - '0.8'      → 80.0 (если ≤ 1 трактуем как долю)
    - None/''/0  → 0.0
    """
    if v is None:
        return 0.0
    if isinstance(v, str):
        v = v.strip()
        if v == '':
            return 0.0
        if v.endswith('%'):
            try:
                return float(v[:-1])
            except ValueError:
                return 0.0
        try:
            f = float(v)
            return f * 100 if 0 < f <= 1 else f
        except ValueError:
            return 0.0
    try:
        f = float(v)
        # Если значение от 0 до 1 — это доля, переводим в %
        if 0 < f <= 1:
            return f * 100
        return f
    except (TypeError, ValueError):
        return 0.0


def safe_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def read_matrix_active_area(filepath: Path) -> float | None:
    """
    Читает файл и возвращает суммарную жилую площадь корпусов
    в «активном» строительстве (готовность > 0 ИЛИ продано > 0).
    Единица — кв. м (не млн).
    """
    if filepath.suffix == '.xlsx':
        import pandas as pd
        df = pd.read_excel(filepath)
        df.columns = [str(c).strip() for c in df.columns]

        # Находим нужные столбцы
        status_col = area_col = pct_col = sold_col = None
        for c in df.columns:
            cl = c.lower().strip()
            if cl in ('статус корпуса', 'статус'):
                status_col = c
            elif c == 'Жилая площадь':
                area_col = c
            elif 'процент готовности' in cl:
                pct_col = c
            elif 'количество проданных квартир' in cl:
                sold_col = c

        if status_col is None or area_col is None:
            print(f"  Ошибка: не найдены обязательные столбцы в {filepath.name}")
            return None

        df = df[df[status_col].str.lower().str.strip() == 'строится'].copy()

        pct_series = df[pct_col].apply(safe_float_pct) if pct_col else pd.Series([0.0]*len(df))
        sold_series = df[sold_col].apply(safe_float) if sold_col else pd.Series([0.0]*len(df))

        active_mask = (pct_series > 0) | (sold_series > 0)
        return df.loc[active_mask, area_col].apply(safe_float).sum()

    else:
        # xlsb
        total_active = 0.0

        with open_workbook(str(filepath)) as wb:
            with wb.get_sheet(1) as sheet:
                headers = None
                idx_status = idx_area = idx_pct = idx_sold = None

                for row in sheet.rows():
                    vals = [c.v for c in row]
                    if headers is None:
                        headers = vals
                        hl = [h.lower().strip() if h else '' for h in headers]

                        for i, h in enumerate(hl):
                            if h in ('статус корпуса', 'статус'):
                                idx_status = i
                        for i, h in enumerate(headers):
                            if h == 'Жилая площадь':
                                idx_area = i
                            elif h and 'процент готовности' in str(h).lower():
                                idx_pct = i
                            elif h and 'количество проданных квартир' in str(h).lower():
                                idx_sold = i

                        if idx_status is None or idx_area is None:
                            print(f"  Ошибка: не найдены обязательные столбцы")
                            return None
                        continue

                    status = vals[idx_status] if idx_status < len(vals) else None
                    if not status or str(status).strip().lower() != 'строится':
                        continue

                    area = safe_float(vals[idx_area] if idx_area < len(vals) else None)
                    pct  = safe_float_pct(vals[idx_pct]  if idx_pct  is not None and idx_pct  < len(vals) else None)
                    sold = safe_float(vals[idx_sold] if idx_sold is not None and idx_sold < len(vals) else None)

                    if pct > 0 or sold > 0:
                        total_active += area

        return total_active


def read_matrix_sold_sqm_active(filepath: Path) -> float | None:
    """
    Возвращает суммарную площадь проданных квартир по активным корпусам.
    """
    if filepath.suffix == '.xlsx':
        import pandas as pd
        df = pd.read_excel(filepath)
        df.columns = [str(c).strip() for c in df.columns]

        status_col = pct_col = sold_col = sold_sqm_col = None
        for c in df.columns:
            cl = c.lower().strip()
            if cl in ('статус корпуса', 'статус'):
                status_col = c
            elif 'процент готовности' in cl:
                pct_col = c
            elif 'количество проданных квартир' in cl:
                sold_col = c
            elif 'площадь проданных квартир' in cl:
                sold_sqm_col = c

        if status_col is None:
            return None

        df = df[df[status_col].str.lower().str.strip() == 'строится'].copy()
        pct_series  = df[pct_col].apply(safe_float_pct) if pct_col else pd.Series([0.0]*len(df))
        sold_series = df[sold_col].apply(safe_float) if sold_col else pd.Series([0.0]*len(df))
        active_mask = (pct_series > 0) | (sold_series > 0)

        if sold_sqm_col is None:
            return 0.0
        return df.loc[active_mask, sold_sqm_col].apply(safe_float).sum()

    else:
        total_sold_sqm = 0.0
        with open_workbook(str(filepath)) as wb:
            with wb.get_sheet(1) as sheet:
                headers = None
                idx_status = idx_pct = idx_sold = idx_sold_sqm = None

                for row in sheet.rows():
                    vals = [c.v for c in row]
                    if headers is None:
                        headers = vals
                        hl = [h.lower().strip() if h else '' for h in headers]

                        for i, h in enumerate(hl):
                            if h in ('статус корпуса', 'статус'):
                                idx_status = i
                        for i, h in enumerate(headers):
                            if h and 'процент готовности' in str(h).lower():
                                idx_pct = i
                            elif h and 'количество проданных квартир' in str(h).lower():
                                idx_sold = i
                            elif h and 'площадь проданных квартир' in str(h).lower():
                                idx_sold_sqm = i

                        if idx_status is None:
                            return None
                        continue

                    status = vals[idx_status] if idx_status < len(vals) else None
                    if not status or str(status).strip().lower() != 'строится':
                        continue

                    pct  = safe_float_pct(vals[idx_pct]  if idx_pct  is not None and idx_pct  < len(vals) else None)
                    sold = safe_float(vals[idx_sold] if idx_sold is not None and idx_sold < len(vals) else None)

                    if pct > 0 or sold > 0:
                        sqm = safe_float(vals[idx_sold_sqm] if idx_sold_sqm is not None and idx_sold_sqm < len(vals) else None)
                        total_sold_sqm += sqm

        return total_sold_sqm


def load_db_series(cur, code: str) -> dict:
    cur.execute("""
        SELECT dp.period_date, dp.value
        FROM data_points dp
        JOIN indicators i ON i.id = dp.indicator_id
        WHERE i.code = %s AND dp.value IS NOT NULL
        ORDER BY dp.period_date
    """, (code,))
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def sum_last_12_months(series: dict, cutoff_date: date) -> float | None:
    end   = date(cutoff_date.year, cutoff_date.month, 1) - timedelta(days=1)
    end   = date(end.year, end.month, 1)
    start = date(end.year - 1, end.month, 1)
    vals = []
    d = start
    for _ in range(12):
        if d in series:
            vals.append(series[d])
        d = (date(d.year, d.month, 28) + timedelta(days=4)).replace(day=1)
    if not vals:
        return None
    return sum(vals)


def main():
    files = find_matrix_files()
    if not files:
        print(f"Нет файлов в {MATRIX_DIR}")
        sys.exit(1)

    # Фильтруем только нужный диапазон
    target_files = []
    for f in files:
        pd_ = parse_date_from_filename(f.name)
        if pd_ and RECALC_FROM <= pd_ <= RECALC_TO:
            target_files.append((pd_, f))

    if not target_files:
        print(f"Нет файлов за период {RECALC_FROM} – {RECALC_TO}")
        sys.exit(1)

    print(f"Найдено файлов для досчёта: {len(target_files)}")
    for pd_, f in target_files:
        print(f"  {pd_} ← {f.name}")

    conn = get_db_conn()
    cur = conn.cursor()

    # Получаем id индикаторов
    cur.execute("SELECT code, id FROM indicators WHERE code = ANY(%s)", (CODES_ACTIVE,))
    code_to_id = dict(cur.fetchall())
    missing = [c for c in CODES_ACTIVE if c not in code_to_id]
    if missing:
        print(f"ОШИБКА: индикаторы не найдены в БД: {missing}")
        sys.exit(1)

    # Загружаем данные из БД нужные для расчётных показателей
    print("\nЗагружаю данные из БД...")
    series_input     = load_db_series(cur, '2.2')         # ввод МЖС, тыс. кв. м
    series_sales_sqm = load_db_series(cur, 'sales_apt_sqm')  # продано кв. м

    # Загружаем uc_new_active по всем периодам (уже есть в БД для более новых файлов)
    series_uc_new_active = load_db_series(cur, 'uc_new_active')

    print(f"  Ввод МЖС (2.2):   {len(series_input)} точек")
    print(f"  Продано кв.м:      {len(series_sales_sqm)} точек")
    print(f"  uc_new_active:     {len(series_uc_new_active)} точек")

    inserted_total = 0

    for period_date, filepath in sorted(target_files):
        label = f"{MONTHS_RU[period_date.month]} {period_date.year}"
        print(f"\nОбрабатываю {filepath.name} → {period_date} ...")

        # 1. Читаем активную жилую площадь
        active_area_sqm = read_matrix_active_area(filepath)
        if active_area_sqm is None:
            print(f"  Пропускаю — ошибка чтения файла")
            continue

        active_area_mln = round(active_area_sqm / 1_000_000, 1)
        print(f"  uc_area_active = {active_area_mln} млн кв. м")

        # 2. Площадь проданных квартир по активным корпусам
        sold_sqm_active = read_matrix_sold_sqm_active(filepath)
        print(f"  sold_sqm_active = {sold_sqm_active:.0f} кв. м")

        rows = []

        def add(code, val):
            if val is not None and code in code_to_id:
                rows.append((code_to_id[code], period_date, label, float(val)))

        # uc_area_active
        add('uc_area_active', active_area_mln)

        # Расчётные показатели
        input_12     = sum_last_12_months(series_input, period_date)
        sales_sqm_12 = sum_last_12_months(series_sales_sqm, period_date)

        # uc_new_active за последние 12 месяцев (из уже имеющихся данных БД)
        new_active_12 = 0.0
        d = date(period_date.year, period_date.month, 1)
        for _ in range(12):
            prev = (date(d.year, d.month, 1) - timedelta(days=1))
            d = date(prev.year, prev.month, 1)
            new_active_12 += series_uc_new_active.get(d, 0.0)

        # uc_stock_years_active = uc_area_active / ввод МЖС за 12 мес. (в млн кв. м)
        if input_12 and input_12 > 0:
            input_mln = input_12 / 1000  # тыс. кв. м → млн кв. м
            add('uc_stock_years_active', round(active_area_mln / input_mln, 1))
            print(f"  uc_stock_years_active = {active_area_mln / input_mln:.1f} лет  (ввод={input_mln:.1f} млн кв.м)")

            # uc_new_vs_input_active
            if new_active_12 > 0:
                add('uc_new_vs_input_active', round(new_active_12 / input_mln * 100, 1))

        # uc_absorption_active = (active_area - sold_sqm_active) / (sales_sqm_12/12)
        if sales_sqm_12 and sales_sqm_12 > 0:
            unsold_active = active_area_sqm - (sold_sqm_active or 0)
            monthly_sales = sales_sqm_12 / 12
            if unsold_active > 0:
                add('uc_absorption_active', round(unsold_active / monthly_sales, 1))
                print(f"  uc_absorption_active = {unsold_active/monthly_sales:.1f} лет")

            # uc_new_vs_sales_active
            if new_active_12 > 0:
                add('uc_new_vs_sales_active', round(new_active_12 * 1_000_000 / sales_sqm_12 * 100, 1))

        # Записываем в БД (UPSERT — не трогаем другие периоды)
        for indicator_id, pd_, lbl, val in rows:
            cur.execute("""
                INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
                VALUES (%s, %s, %s, %s, false)
                ON CONFLICT (indicator_id, period_date) DO UPDATE
                    SET value = EXCLUDED.value,
                        period_label = EXCLUDED.period_label
            """, (indicator_id, pd_, lbl, val))
        inserted_total += len(rows)
        print(f"  Записано {len(rows)} показателей")

    print(f"\nОбновляю materialized view ...", end=' ')
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    print("готово")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✅ Готово. Всего записано/обновлено точек: {inserted_total}")


if __name__ == '__main__':
    main()
