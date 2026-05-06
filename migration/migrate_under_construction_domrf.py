"""
migration/migrate_under_construction_domrf.py

Создаёт раздел «Строящееся жильё (база данных ДОМ.РФ)» и рассчитывает
9 показателей из файлов Матрицы проектов.

Использование:
    python migration/migrate_under_construction_domrf.py

Показатели:
  uc_area_total      — Жилая площадь всего строящегося, млн кв. м (point_in_time, monthly)
  uc_area_active     — Жилая площадь активного строительства, млн кв. м (point_in_time, monthly)
  uc_dev_activity    — Девелоперская активность, кв. м на 1 чел. (point_in_time, annual)
  uc_new_total       — Новые проекты (все), млн кв. м (period, monthly)
  uc_new_active      — Новые проекты (активные), млн кв. м (period, monthly)
  uc_new_vs_input    — Новые проекты / ввод МЖС, % (calculated, monthly)  [2 варианта]
  uc_stock_years     — Запасы строящегося жилья, лет (calculated, monthly) [2 варианта]
  uc_new_vs_sales    — Обеспеченность продаж новыми запусками, % (calculated, monthly) [2 варианта]
  uc_absorption      — Коэффициент поглощения, лет (calculated, monthly)  [2 варианта]
  uc_sold_vs_ready   — Отношение распроданности и стройготовности (point_in_time, monthly)

SQL для создания категории и индикаторов — см. print_setup_sql() ниже.
Запустите его ОДИН РАЗ перед первым запуском скрипта:
    python migration/migrate_under_construction_domrf.py --setup
"""

import os
import re
import sys
from pathlib import Path
from datetime import date, timedelta
from calendar import monthrange

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from pyxlsb import open_workbook

load_dotenv(Path(__file__).parent.parent / '.env')

MATRIX_DIR = Path(__file__).parent / 'domrf_data' / 'matrix_projects'

MONTHS_RU = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}

# Коды индикаторов
CODES = {
    'uc_area_total':   'uc_area_total',
    'uc_area_active':  'uc_area_active',
    'uc_dev_activity': 'uc_dev_activity',
    'uc_new_total':    'uc_new_total',
    'uc_new_active':   'uc_new_active',
    'uc_new_vs_input_total':  'uc_new_vs_input_total',
    'uc_new_vs_input_active': 'uc_new_vs_input_active',
    'uc_stock_years_total':   'uc_stock_years_total',
    'uc_stock_years_active':  'uc_stock_years_active',
    'uc_new_vs_sales_total':  'uc_new_vs_sales_total',
    'uc_new_vs_sales_active': 'uc_new_vs_sales_active',
    'uc_absorption_total':    'uc_absorption_total',
    'uc_absorption_active':   'uc_absorption_active',
    'uc_sold_vs_ready':       'uc_sold_vs_ready',
}

# Коды существующих индикаторов в БД
CODE_INPUT_MZS  = '2.2'          # Объём ввода МЖС
CODE_SALES      = '5.8'          # Количество сделок на первичном рынке
CODE_POPULATION = '1.1'          # Население
CODE_SALES_SQM  = 'sales_apt_sqm'  # Суммарная площадь продаж квартир, кв. м


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


def _norm_key(v) -> str:
    if v is None:
        return ''
    try:
        return str(int(float(str(v).strip())))
    except (TypeError, ValueError):
        return str(v).strip()


# ── Чтение Матрицы проектов ───────────────────────────────────────────────────

def read_matrix(filepath: Path) -> pd.DataFrame:
    """Читает файл Матрицы проектов и возвращает DataFrame только строящихся корпусов."""

    if filepath.suffix == '.xlsx':
        df = pd.read_excel(filepath)
        # Нормализуем заголовки
        df.columns = [str(c).strip() for c in df.columns]
        # Фильтр статуса
        status_col = None
        for c in df.columns:
            if c.lower() in ('статус корпуса', 'статус'):
                status_col = c
                break
        if status_col is None:
            return pd.DataFrame()
        df = df[df[status_col].str.lower().str.strip() == 'строится'].copy()
        return df
    else:
        # xlsb
        rows_data = []
        with open_workbook(str(filepath)) as wb:
            with wb.get_sheet(1) as sheet:
                headers = None
                for row in sheet.rows():
                    vals = [c.v for c in row]
                    if headers is None:
                        headers = [str(v).strip() if v is not None else '' for v in vals]
                        continue
                    if len(vals) < len(headers):
                        vals += [None] * (len(headers) - len(vals))
                    rows_data.append(vals[:len(headers)])

        df = pd.DataFrame(rows_data, columns=headers)
        # Фильтр статуса
        status_col = None
        for c in df.columns:
            if c.lower() in ('статус корпуса', 'статус'):
                status_col = c
                break
        if status_col is None:
            return pd.DataFrame()
        df[status_col] = df[status_col].astype(str)
        df = df[df[status_col].str.lower().str.strip() == 'строится'].copy()
        return df


def safe_float(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def safe_date(v):
    """Парсит дату из значения ячейки."""
    if v is None:
        return None
    if isinstance(v, (date,)):
        return v
    if isinstance(v, pd.Timestamp):
        return v.date()
    # xlsb хранит даты как числа (дни от 1900-01-01)
    if isinstance(v, (int, float)):
        try:
            n = int(v)
            if 30000 < n < 60000:  # разумный диапазон дат
                from datetime import timedelta
                base = date(1899, 12, 30)
                return base + timedelta(days=n)
        except (TypeError, ValueError):
            pass
    if isinstance(v, str):
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y'):
            try:
                return pd.to_datetime(v, format=fmt).date()
            except Exception:
                pass
    return None


# ── Расчёт показателей из одного файла ───────────────────────────────────────

def calc_from_matrix(df: pd.DataFrame, period_date: date) -> dict:
    """
    Рассчитывает все показатели point_in_time из DataFrame строящихся корпусов.
    Возвращает словарь {код: значение}.
    """
    result = {}

    # Находим нужные столбцы (case-insensitive)
    col_map = {}
    needed = {
        'жилая площадь':                    'area',
        'процент готовности по объекту':    'ready_pct',
        'распроданность':                   'sold_pct',
        'продано квартир, шт':              'sold_apt_cnt',
        'продано квартир, м2':              'sold_apt_sqm',
        'первая пд':                        'first_pd',
    }
    for col in df.columns:
        key = col.lower().strip()
        for needle, alias in needed.items():
            if needle in key:
                col_map[alias] = col
                break

    def col(alias) -> pd.Series:
        c = col_map.get(alias)
        if c is None:
            return pd.Series([0.0] * len(df))
        return df[c].apply(safe_float)

    area       = col('area')
    ready_pct  = col('ready_pct')
    sold_pct   = col('sold_pct')
    sold_cnt   = col('sold_apt_cnt')
    sold_sqm   = col('sold_apt_sqm')

    total_area = area.sum()

    # Показатель 1: uc_area_total
    result['uc_area_total'] = round(total_area / 1_000_000, 1)

    # Показатель 2: uc_area_active — готовность > 0 ИЛИ продано > 0
    active_mask = (ready_pct > 0) | (sold_cnt > 0)
    result['uc_area_active'] = round(area[active_mask].sum() / 1_000_000, 1)

    # Показатель 4: uc_new_total и uc_new_active
    # Корпуса где «Первая ПД» попадает в месяц среза
    first_pd_col = col_map.get('first_pd')
    if first_pd_col:
        period_start = period_date
        period_end   = date(period_date.year, period_date.month,
                            monthrange(period_date.year, period_date.month)[1])
        first_pd_dates = df[first_pd_col].apply(safe_date)
        new_mask = first_pd_dates.apply(
            lambda d: d is not None and period_start <= (d.date() if hasattr(d, 'date') else d) <= period_end
        )
        result['uc_new_total']  = round(area[new_mask].sum() / 1_000_000, 1)
        result['uc_new_active'] = round(area[new_mask & active_mask].sum() / 1_000_000, 1)
    else:
        result['uc_new_total']  = None
        result['uc_new_active'] = None

    # Показатель 9: uc_sold_vs_ready
    # sum(area × sold_pct) / sum(area × ready_pct)
    weighted_sold  = (area * sold_pct).sum()
    weighted_ready = (area * ready_pct).sum()
    if weighted_ready > 0:
        result['uc_sold_vs_ready'] = round(weighted_sold / weighted_ready, 4)
    else:
        result['uc_sold_vs_ready'] = None

    # Для показателя 8: сумма «Продано квартир, м2» (проданная жилая площадь)
    result['_sold_apt_sqm_total']  = sold_sqm.sum()
    result['_sold_apt_sqm_active'] = sold_sqm[active_mask].sum()

    return result


# ── Загрузка данных из БД ─────────────────────────────────────────────────────

def load_db_series(cur, code: str) -> dict:
    """Загружает временной ряд из БД. Возвращает {period_date: value}."""
    cur.execute("""
        SELECT dp.period_date, dp.value
        FROM data_points dp
        JOIN indicators i ON i.id = dp.indicator_id
        WHERE i.code = %s AND dp.value IS NOT NULL
        ORDER BY dp.period_date
    """, (code,))
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def sum_last_12_months(series: dict, cutoff_date: date) -> float | None:
    """
    Суммирует значения за 12 месяцев до cutoff_date (не включая cutoff_date).
    Для файла апрель 2026 → апрель 2025 – март 2026.
    """
    end   = date(cutoff_date.year, cutoff_date.month, 1) - timedelta(days=1)
    end   = date(end.year, end.month, 1)
    start = date(end.year - 1, end.month, 1)
    # Берём 12 месяцев: start .. start+11 месяцев
    vals = []
    d = start
    for _ in range(12):
        if d in series:
            vals.append(series[d])
        d = (date(d.year, d.month, 28) + timedelta(days=4)).replace(day=1)
    if not vals:
        return None
    return sum(vals)


def get_population_for_year(series: dict, year: int) -> float | None:
    """Берёт значение населения на 1 января (period_date = YYYY-01-01)."""
    return series.get(date(year, 1, 1))


# ── Основная функция ──────────────────────────────────────────────────────────

def main():
    if '--setup' in sys.argv:
        print_setup_sql()
        return

    files = find_matrix_files()
    if not files:
        print(f"Нет файлов в {MATRIX_DIR}")
        sys.exit(1)

    conn = get_db_conn()
    cur  = conn.cursor()

    # Проверяем что все индикаторы созданы
    all_codes = list(CODES.values())
    cur.execute("SELECT code, id FROM indicators WHERE code = ANY(%s)", (all_codes,))
    code_to_id = dict(cur.fetchall())
    missing = [c for c in all_codes if c not in code_to_id]
    if missing:
        print(f"ОШИБКА: индикаторы не найдены в БД: {missing}")
        print("Запустите: python migration/migrate_under_construction_domrf.py --setup")
        print("Затем выполните SQL из вывода и повторите запуск.")
        sys.exit(1)

    # Загружаем данные из БД для расчётных показателей
    print("Загружаю данные из БД...")
    series_input    = load_db_series(cur, CODE_INPUT_MZS)
    series_sales    = load_db_series(cur, CODE_SALES)
    series_pop      = load_db_series(cur, CODE_POPULATION)
    series_sales_sqm = load_db_series(cur, CODE_SALES_SQM)

    print(f"  Ввод МЖС (2.2):          {len(series_input)} точек")
    print(f"  Сделки шт. (5.8):        {len(series_sales)} точек")
    print(f"  Продано кв. м (sales_sqm): {len(series_sales_sqm)} точек")
    print(f"  Население (1.1):          {len(series_pop)} точек")

    # Удаляем все существующие данные
    ids = list(code_to_id.values())
    cur.execute("DELETE FROM data_points WHERE indicator_id = ANY(%s)", (ids,))
    print(f"\nУдалено существующих точек: {cur.rowcount}")

    # Обрабатываем каждый файл
    # Сначала собираем все point_in_time данные
    pt_data = {}  # {period_date: {code: value}}

    for filepath in files:
        period_date = parse_date_from_filename(filepath.name)
        if not period_date:
            continue

        print(f"Читаю {filepath.name} → {period_date} ...", end=' ')
        df = read_matrix(filepath)
        if df.empty:
            print("пропущено (пустой датафрейм)")
            continue

        calc = calc_from_matrix(df, period_date)
        pt_data[period_date] = calc
        print(f"area_total={calc['uc_area_total']}, new_total={calc.get('uc_new_total')}")

    print(f"\nОбработано файлов: {len(pt_data)}")

    # Вычисляем расчётные показатели и записываем всё в БД
    inserted_total = 0

    for period_date in sorted(pt_data.keys()):
        calc  = pt_data[period_date]
        label = f"{MONTHS_RU[period_date.month]} {period_date.year}"

        rows = []

        # point_in_time показатели
        def add(code, val):
            if val is not None and code in code_to_id:
                rows.append((code_to_id[code], period_date, label, val))

        add('uc_area_total',   calc['uc_area_total'])
        add('uc_area_active',  calc['uc_area_active'])
        add('uc_new_total',    calc.get('uc_new_total'))
        add('uc_new_active',   calc.get('uc_new_active'))
        add('uc_sold_vs_ready', calc.get('uc_sold_vs_ready'))

        # Показатель 3: девелоперская активность — только январские файлы
        if period_date.month == 1:
            pop = get_population_for_year(series_pop, period_date.year)
            if pop and pop > 0:
                # Население в тыс. чел. → умножаем на 1000
                dev_activity = round(calc['uc_area_total'] * 1_000_000 / (pop * 1000), 2)
                add('uc_dev_activity', dev_activity)

        # Расчётные показатели (нужны данные за последние 12 месяцев)
        input_12    = sum_last_12_months(series_input,    period_date)  # ввод МЖС
        sales_sqm_12 = sum_last_12_months(series_sales_sqm, period_date)  # продано кв. м

        # Для новых проектов за 12 месяцев — собираем из pt_data
        new_total_12 = new_active_12 = 0.0
        d = date(period_date.year, period_date.month, 1)
        for _ in range(12):
            prev = (date(d.year, d.month, 1) - timedelta(days=1))
            d = date(prev.year, prev.month, 1)
            if d in pt_data:
                new_total_12  += pt_data[d].get('uc_new_total')  or 0
                new_active_12 += pt_data[d].get('uc_new_active') or 0

        # Показатель 5: новые проекты / ввод МЖС, %
        # ввод МЖС в тыс. кв. м → переводим в млн кв. м
        if input_12 and input_12 > 0:
            input_mln = input_12 / 1000
            if new_total_12 > 0:
                add('uc_new_vs_input_total',  round(new_total_12  / input_mln * 100, 1))
            if new_active_12 > 0:
                add('uc_new_vs_input_active', round(new_active_12 / input_mln * 100, 1))

        # Показатель 6: запасы строящегося жилья, лет
        if input_12 and input_12 > 0:
            input_mln = input_12 / 1000
            add('uc_stock_years_total',  round(calc['uc_area_total']  / input_mln, 1))
            add('uc_stock_years_active', round(calc['uc_area_active'] / input_mln, 1))

        # Показатель 7: обеспеченность продаж новыми запусками, %
        # новые проекты (кв. м) / продано квартир (кв. м) × 100
        if sales_sqm_12 and sales_sqm_12 > 0:
            if new_total_12 > 0:
                add('uc_new_vs_sales_total',  round(new_total_12  * 1_000_000 / sales_sqm_12 * 100, 1))
            if new_active_12 > 0:
                add('uc_new_vs_sales_active', round(new_active_12 * 1_000_000 / sales_sqm_12 * 100, 1))

        # Показатель 8: коэффициент поглощения, лет
        # (area - sold_sqm) / sales_sqm_12_месяцев / 12
        if sales_sqm_12 and sales_sqm_12 > 0:
            unsold_total  = calc['uc_area_total']  * 1_000_000 - calc.get('_sold_apt_sqm_total',  0)
            unsold_active = calc['uc_area_active'] * 1_000_000 - calc.get('_sold_apt_sqm_active', 0)
            monthly_sales = sales_sqm_12 / 12
            if unsold_total > 0:
                add('uc_absorption_total',  round(unsold_total  / monthly_sales, 1))
            if unsold_active > 0:
                add('uc_absorption_active', round(unsold_active / monthly_sales, 1))

        # Записываем в БД
        for indicator_id, pd_, lbl, val in rows:
            if val is None:
                continue
            cur.execute("""
                INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
                VALUES (%s, %s, %s, %s, false)
                ON CONFLICT (indicator_id, period_date) DO UPDATE
                    SET value = EXCLUDED.value,
                        period_label = EXCLUDED.period_label
            """, (indicator_id, pd_, lbl, float(val)))
            inserted_total += 1

    print(f"\nОбновляю materialized view ...", end=' ')
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    print("готово")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Готово. Всего записано точек: {inserted_total}")


def print_setup_sql():
    print("""
-- Запустите этот SQL для создания категории и индикаторов:

-- 1. Создаём категорию
INSERT INTO categories (code, name, sort_order)
VALUES ('under_construction_domrf', 'Строящееся жильё (база данных ДОМ.РФ)', 6)
ON CONFLICT (code) DO NOTHING;

-- 2. Создаём индикаторы
DO $$
DECLARE
    cat_id INT := (SELECT id FROM categories WHERE code = 'under_construction_domrf');
    src_id INT := (SELECT id FROM sources WHERE code = 'domrf');
BEGIN
    INSERT INTO indicators
        (code, category_id, source_id, name, unit, periodicity, period_type, is_public, chart_type, sort_order)
    VALUES
      ('uc_area_total',          cat_id, src_id, 'Жилая площадь возводимых МЖД на отчётную дату',                                        'млн кв. м', 'monthly', 'point_in_time', true, 'bar',  1),
      ('uc_area_active',         cat_id, src_id, 'Жилая площадь МЖД в стадии активного строительства или продаж',                        'млн кв. м', 'monthly', 'point_in_time', true, 'bar',  2),
      ('uc_dev_activity',        cat_id, src_id, 'Девелоперская активность по текущему строительству',                                    'кв. м / чел.', 'annual', 'point_in_time', true, 'line', 3),
      ('uc_new_total',           cat_id, src_id, 'Новые проекты (все)',                                                                    'млн кв. м', 'monthly', 'period',         true, 'bar',  4),
      ('uc_new_active',          cat_id, src_id, 'Новые проекты (активные)',                                                              'млн кв. м', 'monthly', 'period',         true, 'bar',  5),
      ('uc_new_vs_input_total',  cat_id, src_id, 'Новые проекты / ввод МЖС (все проекты)',                                               '%',          'monthly', 'point_in_time', false, 'line', 6),
      ('uc_new_vs_input_active', cat_id, src_id, 'Новые проекты / ввод МЖС (активные проекты)',                                          '%',          'monthly', 'point_in_time', false, 'line', 7),
      ('uc_stock_years_total',   cat_id, src_id, 'Запасы строящегося жилья (все проекты)',                                               'лет',        'monthly', 'point_in_time', false, 'line', 8),
      ('uc_stock_years_active',  cat_id, src_id, 'Запасы строящегося жилья (активные проекты)',                                          'лет',        'monthly', 'point_in_time', false, 'line', 9),
      ('uc_new_vs_sales_total',  cat_id, src_id, 'Обеспеченность продаж новыми запусками (все проекты)',                                 '%',          'monthly', 'point_in_time', false, 'line', 10),
      ('uc_new_vs_sales_active', cat_id, src_id, 'Обеспеченность продаж новыми запусками (активные проекты)',                            '%',          'monthly', 'point_in_time', false, 'line', 11),
      ('uc_absorption_total',    cat_id, src_id, 'Коэффициент поглощения (все проекты)',                                                 'лет',        'monthly', 'point_in_time', false, 'line', 12),
      ('uc_absorption_active',   cat_id, src_id, 'Коэффициент поглощения (активные проекты)',                                            'лет',        'monthly', 'point_in_time', false, 'line', 13),
      ('uc_sold_vs_ready',       cat_id, src_id, 'Отношение распроданности и стройготовности',                                           '',           'monthly', 'point_in_time', true,  'line', 14)
    ON CONFLICT (code) DO NOTHING;
END $$;
""")


if __name__ == '__main__':
    main()
