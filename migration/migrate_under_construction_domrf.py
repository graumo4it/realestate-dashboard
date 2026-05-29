"""
migration/migrate_under_construction_domrf.py

Создаёт раздел «Строящееся жильё (база данных ДОМ.РФ)» и рассчитывает
9 показателей из файлов Матрицы проектов.

Использование:
    python migration/migrate_under_construction_domrf.py

Показатели:
  uc_area_total      — Жилая площадь всего строящегося, млн кв. м (point_in_time, monthly)
  uc_area_active     — Жилая площадь активного строительства, млн кв. м (point_in_time, monthly)
  uc_dev_activity    — Девелоперская активность, кв. м на 1 чел. (period_start, annual)
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
CODE_INPUT_MZS  = '2.3'          # Объём ввода МЖС
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
    """Возвращает файлы матрицы, отсортированные по дате (хронологически).
    Сортировка по дате файла, а не алфавитная — иначе "15.09" идёт раньше "18.08"."""
    files = [f for f in MATRIX_DIR.glob('*.xlsb') if not f.name.startswith('~$')]
    files += [f for f in MATRIX_DIR.glob('*.xlsx') if not f.name.startswith('~$')]
    dated = [(parse_date_from_filename(f.name), f) for f in files]
    return [f for d, f in sorted((d, f) for d, f in dated if d is not None)]


def _norm_key(v) -> str:
    if v is None:
        return ''
    try:
        return str(int(float(str(v).strip())))
    except (TypeError, ValueError):
        return str(v).strip()


# ── Чтение Матрицы проектов ───────────────────────────────────────────────────

def _read_matrix_raw(filepath: Path) -> pd.DataFrame:
    """Читает файл Матрицы проектов без какого-либо фильтра. Внутренняя функция."""
    if filepath.suffix == '.xlsx':
        df = pd.read_excel(filepath)
        df.columns = [str(c).strip() for c in df.columns]
        return df
    else:
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
        if not rows_data:
            return pd.DataFrame()
        df = pd.DataFrame(rows_data, columns=headers)
        if status_col := next((c for c in df.columns if c.lower() in ('статус корпуса', 'статус')), None):
            df[status_col] = df[status_col].astype(str)
        return df


def read_matrix(filepath: Path) -> pd.DataFrame:
    """Читает файл Матрицы проектов и возвращает только строящиеся корпуса.
    Используется для показателей площади (uc_area_*, uc_sold_vs_ready и т.д.)."""
    df = _read_matrix_raw(filepath)
    if df.empty:
        return df
    status_col = next((c for c in df.columns if c.lower() in ('статус корпуса', 'статус')), None)
    if status_col is None:
        return pd.DataFrame()
    return df[df[status_col].str.lower().str.strip() == 'строится'].copy().reset_index(drop=True)


def calc_new_projects(df_full: pd.DataFrame, target_month: date):
    """
    Считает новые проекты за target_month из снепшота СЛЕДУЮЩЕГО месяца.
    Возвращает (new_total_mln, new_active_mln) или (None, None) если нет колонки Первая ПД.

    Логика: берём ВСЕ корпуса (все статусы) с «Первая ПД» в target_month.
    Снепшот следующего месяца уже содержит корпуса, зарегистрированные во второй
    половине target_month (которых нет в снепшоте самого target_month).
    """
    if df_full.empty:
        return None, None

    first_pd_col = next((c for c in df_full.columns if 'первая пд' in c.lower()), None)
    area_col     = next((c for c in df_full.columns if 'жилая площадь' in c.lower()), None)
    if first_pd_col is None or area_col is None:
        return None, None

    period_start = target_month
    period_end   = date(target_month.year, target_month.month,
                        monthrange(target_month.year, target_month.month)[1])

    dates = df_full[first_pd_col].apply(safe_date)
    new_mask = dates.apply(
        lambda d: d is not None and period_start <= (d.date() if hasattr(d, 'date') else d) <= period_end
    )
    area = df_full[area_col].apply(safe_float)

    # Фильтр массовой перерегистрации: если ≥60% корпусов целевого месяца имеют
    # одну и ту же дату — это системное событие в базе ДОМ.РФ (не реальные запуски).
    # Исключаем строки с той датой-выбросом.
    if new_mask.any():
        month_dates = dates[new_mask].apply(lambda d: d.date() if hasattr(d, 'date') else d)
        vc = month_dates.value_counts()
        top_cnt = vc.iloc[0]
        if top_cnt / new_mask.sum() >= 0.60:
            top_date = vc.index[0]
            print(f"  [!] Аномалия {target_month}: {top_cnt}/{new_mask.sum()} корпусов"
                  f" на {top_date} — дата-выброс исключена", flush=True)
            # Убираем только строки с аномальной датой, остальные оставляем
            excl = month_dates == top_date
            new_mask = new_mask.copy()
            new_mask[new_mask] = ~excl.values

    new_total = round(area[new_mask].sum() / 1_000_000, 4)

    # Активные: строится + (готовность > 0 ИЛИ продано > 0)
    status_col   = next((c for c in df_full.columns if c.lower() in ('статус корпуса', 'статус')), None)
    ready_col    = next((c for c in df_full.columns if 'процент готовности по объекту' in c.lower()), None)
    sold_cnt_col = next((c for c in df_full.columns
                         if 'продано квартир' in c.lower() and ('шт' in c.lower() or 'количество' in c.lower())), None)

    if status_col and (ready_col or sold_cnt_col):
        строится_mask = df_full[status_col].astype(str).str.lower().str.strip() == 'строится'
        ready = df_full[ready_col].apply(safe_float_pct) if ready_col else pd.Series([0.0] * len(df_full))
        sold  = df_full[sold_cnt_col].apply(safe_float)  if sold_cnt_col else pd.Series([0.0] * len(df_full))
        active_mask = строится_mask & ((ready > 0) | (sold > 0))
        new_active = round(area[new_mask & active_mask].sum() / 1_000_000, 4)
    else:
        new_active = new_total  # fallback

    return (new_total if new_total > 0 else None,
            new_active if new_active > 0 else None)


def safe_float(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def safe_float_pct(v) -> float:
    """Парсит процент готовности/распроданности.
    Поддерживает: '80%', '7,30%' (русская запятая), 0.8, 80.0."""
    if v is None:
        return 0.0
    if isinstance(v, str):
        v = v.strip()
        if v == '':
            return 0.0
        # Нормализуем русскую запятую → точка
        v = v.replace(',', '.')
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
        if 0 < f <= 1:
            return f * 100
        return f
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
        'жилая площадь':                             'area',
        'процент готовности по объекту':             'ready_pct',
        'распроданность':                            'sold_pct',
        'продано квартир, шт':                       'sold_apt_cnt',
        'количество проданных квартир по проекту':   'sold_apt_cnt',  # старый формат
        'продано квартир, м2':                       'sold_apt_sqm',
        'первая пд':                                 'first_pd',
    }
    for col in df.columns:
        key = col.lower().strip()
        for needle, alias in needed.items():
            if needle in key:
                if alias not in col_map:  # не перезаписываем если уже нашли
                    col_map[alias] = col
                break

    def col(alias) -> pd.Series:
        c = col_map.get(alias)
        if c is None:
            return pd.Series([0.0] * len(df))
        return df[c].apply(safe_float)
    
    def col_pct(alias) -> pd.Series:
        c = col_map.get(alias)
        if c is None:
            return pd.Series([0.0] * len(df))
        return df[c].apply(safe_float_pct)

    area       = col('area')
    ready_pct  = col_pct('ready_pct')
    sold_pct   = col_pct('sold_pct')   # col_pct: нормализует 0-1 → 0-100 как ready_pct
    sold_cnt   = col('sold_apt_cnt')
    sold_sqm   = col('sold_apt_sqm')

    total_area = area.sum()

    # Показатель 1: uc_area_total
    result['uc_area_total'] = round(total_area / 1_000_000, 1)

    # Показатель 2: uc_area_active — готовность > 0 ИЛИ продано > 0
    active_mask = (ready_pct > 0) | (sold_cnt > 0)
    result['uc_area_active'] = round(area[active_mask].sum() / 1_000_000, 1)

    # Показатель 4: uc_new_total и uc_new_active
    # НЕ считаются здесь — используется снепшот СЛЕДУЮЩЕГО месяца.
    # Значения проставляются из main() через calc_new_projects().
    result['uc_new_total']  = None
    result['uc_new_active'] = None

    # Показатель 9: uc_sold_vs_ready
    # sum(area × sold_pct) / sum(area × ready_pct)
    # Оба в одном масштабе (0–100) благодаря col_pct.
    # Если колонка «Распроданность» отсутствует — вернуть None, а не 0.
    if col_map.get('sold_pct') is None:
        result['uc_sold_vs_ready'] = None
    else:
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
    Суммирует значения за 12 месяцев, включая cutoff_date (cutoff … cutoff-11).
    Для ноября 2024 → декабрь 2023 – ноябрь 2024.
    Для апреля 2026 → май 2025 – апрель 2026.
    Если хотя бы один месяц отсутствует → возвращает None.
    """
    vals = []
    d = date(cutoff_date.year, cutoff_date.month, 1)
    for _ in range(12):
        if d not in series:
            return None
        vals.append(series[d])
        d = (date(d.year, d.month, 1) - timedelta(days=1))
        d = date(d.year, d.month, 1)
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

        # Строится — для площадных метрик
        df = read_matrix(filepath)
        if df.empty:
            print("пропущено (пустой датафрейм)")
            continue

        calc = calc_from_matrix(df, period_date)
        pt_data[period_date] = calc

        # Новые проекты за ПРЕДЫДУЩИЙ месяц: берём все статусы из текущего снепшота.
        # Снепшот M+1 содержит корпуса, зарегистрированные во второй половине M,
        # которых ещё нет в снепшоте M (снятом ≈15-го числа).
        prev_month = date((period_date - timedelta(days=1)).year,
                          (period_date - timedelta(days=1)).month, 1)
        if prev_month in pt_data:
            df_full = _read_matrix_raw(filepath)
            new_total, new_active = calc_new_projects(df_full, prev_month)
            pt_data[prev_month]['uc_new_total']  = new_total
            pt_data[prev_month]['uc_new_active'] = new_active
            print(f"area_total={calc['uc_area_total']}, new({prev_month})={new_total}")
        else:
            print(f"area_total={calc['uc_area_total']}")

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
        # Окно: текущий месяц + 11 предыдущих (M … M-11).
        # new_months_found считает сколько месяцев реально найдено в pt_data;
        # показатель рассчитывается только если найдены все 12.
        new_total_12 = new_active_12 = 0.0
        new_months_found = 0
        d = date(period_date.year, period_date.month, 1)
        for _ in range(12):
            # Считаем только месяцы где first_pd колонка есть (uc_new_total не None).
            # Старые файлы без first_pd дают None и не должны входить в счётчик.
            if d in pt_data and pt_data[d].get('uc_new_total') is not None:
                new_total_12  += pt_data[d]['uc_new_total']  or 0
                new_active_12 += pt_data[d].get('uc_new_active') or 0
                new_months_found += 1
            prev = (date(d.year, d.month, 1) - timedelta(days=1))
            d = date(prev.year, prev.month, 1)

        # Показатель 5: новые проекты / ввод МЖС, %
        # Требуем ровно 12 месяцев по новым проектам, иначе первые точки будут
        # занижены из-за неполного скользящего окна (данные с дек 2023).
        # ввод МЖС в тыс. кв. м → переводим в млн кв. м
        if input_12 and input_12 > 0 and new_months_found == 12:
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
        # Аналогично показателю 5: требуем 12 полных месяцев по новым проектам.
        if sales_sqm_12 and sales_sqm_12 > 0 and new_months_found == 12:
            if new_total_12 > 0:
                add('uc_new_vs_sales_total',  round(new_total_12  * 1_000_000 / sales_sqm_12 * 100, 1))
            if new_active_12 > 0:
                add('uc_new_vs_sales_active', round(new_active_12 * 1_000_000 / sales_sqm_12 * 100, 1))

        # Показатель 8: коэффициент поглощения, лет
        # (area - sold_sqm) / sales_sqm_12_месяцев / 12
        if sales_sqm_12 and sales_sqm_12 > 0:
            unsold_total  = calc['uc_area_total']  * 1_000_000 - calc.get('_sold_apt_sqm_total',  0)
            unsold_active = calc['uc_area_active'] * 1_000_000 - calc.get('_sold_apt_sqm_active', 0)
            if unsold_total > 0:
                add('uc_absorption_total',  round(unsold_total  / sales_sqm_12, 1))
            if unsold_active > 0:
                add('uc_absorption_active', round(unsold_active / sales_sqm_12, 1))

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
    print(f"Upserted: {inserted_total} rows")


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
      ('uc_dev_activity',        cat_id, src_id, 'Девелоперская активность по текущему строительству',                                    'кв. м / чел.', 'annual', 'period_start', true, 'line', 3),
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
