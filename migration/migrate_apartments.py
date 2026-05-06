"""
migration/migrate_apartments.py

Рассчитывает три показателя квартирографии из файлов «Квартирография» (*.xlsb / *.xlsx):

  apartments_count  — количество квартир по комнатности (bar stacked)
  apartments_area   — средняя площадь квартир по комнатности (line)
  apartments_share  — структура квартир по комнатности, % (bar 100%)

Использование:
    python migration/migrate_apartments.py

Особенности:
    - Поддерживает оба формата: .xlsb и .xlsx
    - Для старых файлов (без столбца статуса): берёт статус из Матрицы проектов
      за тот же месяц (поиск по месяцу+году, день игнорируется)
    - Для xlsx-файлов Матрицы проектов тоже поддерживается
    - Некорректные периоды (дек.2023, янв.2024): заменяются интерполяцией
      между ноябрём 2023 и февралём 2024
"""

import os
import re
import sys
from pathlib import Path
from datetime import date

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from pyxlsb import open_workbook

load_dotenv()

MONTHS_RU = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}

DATA_DIR   = Path(__file__).parent / 'domrf_data' / 'apartments'
MATRIX_DIR = Path(__file__).parent / 'domrf_data' / 'matrix_projects'

# Периоды с некорректными данными — заменяются интерполяцией
# Значение: (дата левой границы, дата правой границы)
BAD_PERIODS = {
    date(2023, 12, 1): (date(2023, 11, 1), date(2024, 2, 1)),
    date(2024,  1, 1): (date(2023, 11, 1), date(2024, 2, 1)),
}

INDICATOR_CODES = {
    ('count', '1k'):    'apartments_count_1k',
    ('count', '2k'):    'apartments_count_2k',
    ('count', '3k'):    'apartments_count_3k',
    ('count', '4k'):    'apartments_count_4k',
    ('count', 'total'): 'apartments_count_total',
    ('area',  '1k'):    'apartments_area_1k',
    ('area',  '2k'):    'apartments_area_2k',
    ('area',  '3k'):    'apartments_area_3k',
    ('area',  '4k'):    'apartments_area_4k',
    ('area',  'total'): 'apartments_area_total',
    ('share', '1k'):    'apartments_share_1k',
    ('share', '2k'):    'apartments_share_2k',
    ('share', '3k'):    'apartments_share_3k',
    ('share', '4k'):    'apartments_share_4k',
}

ROOM_TYPES = ['1k', '2k', '3k', '4k']

ROOM_COLS_NEW = {
    '1k': ('1к. кв количество',  '1к. кв средняя площадь'),
    '2k': ('2к. кв количество',  '2к. кв средняя площадь'),
    '3k': ('3к. кв количество',  '3к. кв средняя площадь'),
    '4k': ('4к. кв количество',  '4к. кв средняя площадь'),
}
ROOM_COLS_OLD = {
    '1k': ('1к.кв_количество', '1к.кв_avg_sq'),
    '2k': ('2к.кв_количество', '2к.кв_avg_sq'),
    '3k': ('3к.кв_количество', '3к.кв_avg_sq'),
    '4k': ('4к.кв_количество', '4к.кв_avg_sq'),
}
# Самый старый формат (дек.2021, янв.2022): только количество, без площади
ROOM_COLS_OLDEST = {
    '1k': ('1-комнатные', None),
    '2k': ('2-комнатные', None),
    '3k': ('3-комнатные', None),
    '4k': ('4-комнатные', None),
}


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def parse_date_from_filename(filename: str) -> object:
    """Поддерживает DD.MM.YYYY и DD_MM_YYYY в имени файла."""
    m = re.search(r'(\d{2})[._](\d{2})[._](\d{4})', filename)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(year, month, 1)


def find_all_data_files() -> list:
    """Возвращает отсортированный список всех xlsx и xlsb файлов."""
    files = []
    for pattern in ('*.xlsb', '*.xlsx'):
        files.extend(DATA_DIR.glob(pattern))
    files = [f for f in files if not f.name.startswith('~$')]
    return sorted(files)


# ── Загрузка статусов из Матрицы проектов ────────────────────────────────────

def load_statuses_from_matrix(period_date: date) -> dict:
    """
    Загружает {корпус: статус} из Матрицы проектов за тот же месяц/год.
    Поддерживает .xlsb и .xlsx.
    """
    month_year = f".{period_date.month:02d}.{period_date.year}"
    for pattern in ('*.xlsb', '*.xlsx'):
        for f in MATRIX_DIR.glob(pattern):
            if f.name.startswith('~$'):
                continue
            if month_year in f.name:
                if f.suffix == '.xlsx':
                    return _read_statuses_xlsx(f)
                else:
                    return _read_statuses_xlsb(f)
    return {}


def _read_statuses_xlsb(filepath: Path) -> dict:
    result = {}
    with open_workbook(str(filepath)) as wb:
        with wb.get_sheet(1) as sheet:
            headers = None
            idx_korpus = idx_status = None
            for row in sheet.rows():
                vals = [c.v for c in row]
                if headers is None:
                    headers = vals
                    hl = [h.lower().strip() if h else '' for h in headers]
                    try:
                        idx_korpus = hl.index('корпус')
                        if 'статус корпуса' in hl:
                            idx_status = hl.index('статус корпуса')
                        elif 'статус' in hl:
                            idx_status = hl.index('статус')
                    except ValueError:
                        return {}
                    continue
                if idx_korpus is None or idx_status is None:
                    continue
                korpus = vals[idx_korpus] if idx_korpus < len(vals) else None
                status = vals[idx_status] if idx_status < len(vals) else None
                if korpus is not None:
                    result[_norm_key(korpus)] = status
    return result


def _norm_key(v) -> str:
    """Нормализует ключ корпуса к строке целого числа: 13330.0 → '13330', '47895' → '47895'."""
    if v is None:
        return ''
    try:
        return str(int(float(str(v).strip())))
    except (ValueError, TypeError):
        return str(v).strip()


def _read_statuses_xlsx(filepath: Path) -> dict:
    df = pd.read_excel(filepath, dtype=str)
    # Заголовки могут быть не строками (datetime и т.д.) — приводим безопасно
    cl = {str(c).lower().strip(): c for c in df.columns}
    if 'корпус' not in cl:
        return {}
    col_korpus = cl['корпус']
    col_status = None
    if 'статус корпуса' in cl:
        col_status = cl['статус корпуса']
    elif 'статус' in cl:
        col_status = cl['статус']
    if col_status is None:
        return {}
    result = {}
    for _, row in df.iterrows():
        k = row[col_korpus]
        s = row[col_status]
        if pd.notna(k):
            result[_norm_key(k)] = s if pd.notna(s) else None
    return result


# ── Чтение квартирографии ─────────────────────────────────────────────────────

def _build_result(count_sum: dict, area_weighted: dict) -> dict | None:
    total_count = sum(count_sum.values())
    if total_count == 0:
        print("  Предупреждение: суммарное количество квартир = 0")
        return None

    area_avg = {}
    total_area = sum(area_weighted.values())
    for rt in ROOM_TYPES:
        if count_sum[rt] > 0 and total_area > 0:
            area_avg[rt] = round(area_weighted[rt] / count_sum[rt], 2)
        else:
            area_avg[rt] = None
    area_avg['total'] = round(total_area / total_count, 2) if total_area > 0 else None

    share     = {rt: round(count_sum[rt] / total_count * 100, 2) for rt in ROOM_TYPES}
    count_int = {rt: round(count_sum[rt]) for rt in ROOM_TYPES}
    count_int['total'] = round(total_count)

    return {'count': count_int, 'area': area_avg, 'share': share}


def calc_apartments_xlsb(filepath: Path, status_map: dict) -> dict | None:
    count_sum     = {rt: 0.0 for rt in ROOM_TYPES}
    area_weighted = {rt: 0.0 for rt in ROOM_TYPES}

    with open_workbook(str(filepath)) as wb:
        with wb.get_sheet(1) as sheet:
            headers = None
            col_idx = {}
            room_cols = None
            use_external = bool(status_map)

            for row in sheet.rows():
                vals = [c.v for c in row]
                if headers is None:
                    headers = vals
                    hl = [h.lower().strip() if h else '' for h in headers]

                    if '1к. кв количество' in headers:
                        room_cols = ROOM_COLS_NEW
                    elif '1к.кв_количество' in headers:
                        room_cols = ROOM_COLS_OLD
                    else:
                        print("  Ошибка: не найдены столбцы комнатности")
                        return None

                    try:
                        col_idx['korpus'] = hl.index('корпус')
                        for rt, (cnt_col, area_col) in room_cols.items():
                            col_idx[f'{rt}_cnt']  = headers.index(cnt_col)
                            col_idx[f'{rt}_area'] = headers.index(area_col)
                    except ValueError as e:
                        print(f"  Ошибка: столбец не найден — {e}")
                        return None

                    if not use_external:
                        if 'статус корпуса' in hl:
                            col_idx['status'] = hl.index('статус корпуса')
                        elif 'статус' in hl:
                            col_idx['status'] = hl.index('статус')
                        else:
                            print("  Ошибка: нет столбца статуса и нет внешнего маппинга")
                            return None
                    continue

                if use_external:
                    korpus = vals[col_idx['korpus']] if col_idx['korpus'] < len(vals) else None
                    status = status_map.get(_norm_key(korpus))
                else:
                    status = vals[col_idx['status']] if col_idx['status'] < len(vals) else None

                if not status or str(status).strip().lower() != 'строится':
                    continue

                for rt in ROOM_TYPES:
                    cnt_raw  = vals[col_idx[f'{rt}_cnt']]  if col_idx[f'{rt}_cnt']  < len(vals) else None
                    area_raw = vals[col_idx[f'{rt}_area']] if col_idx[f'{rt}_area'] < len(vals) else None
                    try:
                        cnt = float(cnt_raw) if cnt_raw not in (None, '') else 0.0
                    except (TypeError, ValueError):
                        cnt = 0.0
                    try:
                        avg_area = float(area_raw) if area_raw not in (None, '') else 0.0
                    except (TypeError, ValueError):
                        avg_area = 0.0
                    count_sum[rt]    += cnt
                    area_weighted[rt] += cnt * avg_area

    return _build_result(count_sum, area_weighted)


def calc_apartments_xlsx(filepath: Path, status_map: dict) -> dict | None:
    df = pd.read_excel(filepath)
    cl = {c.lower().strip(): c for c in df.columns}

    if '1к. кв количество' in df.columns:
        room_cols = ROOM_COLS_NEW
    elif '1к.кв_количество' in df.columns:
        room_cols = ROOM_COLS_OLD
    elif '1-комнатные' in df.columns:
        room_cols = ROOM_COLS_OLDEST
    else:
        print("  Ошибка: не найдены столбцы комнатности")
        return None

    if 'корпус' not in cl:
        print("  Ошибка: нет столбца 'Корпус'")
        return None
    col_korpus = cl['корпус']

    use_external = bool(status_map)
    col_status = None
    if not use_external:
        if 'статус корпуса' in cl:
            col_status = cl['статус корпуса']
        elif 'статус' in cl:
            col_status = cl['статус']
        else:
            print("  Ошибка: нет столбца статуса и нет внешнего маппинга")
            return None

    count_sum     = {rt: 0.0 for rt in ROOM_TYPES}
    area_weighted = {rt: 0.0 for rt in ROOM_TYPES}

    for _, row in df.iterrows():
        if use_external:
            korpus = row[col_korpus]
            status = status_map.get(_norm_key(korpus))
        else:
            status = row[col_status] if col_status else None

        if not status or str(status).strip().lower() != 'строится':
            continue

        for rt in ROOM_TYPES:
            cnt_col, area_col = room_cols[rt]
            try:
                cnt = float(row[cnt_col]) if pd.notna(row[cnt_col]) else 0.0
            except (TypeError, ValueError):
                cnt = 0.0
            try:
                avg_area = float(row[area_col]) if area_col and pd.notna(row[area_col]) else 0.0
            except (TypeError, ValueError):
                avg_area = 0.0
            count_sum[rt]    += cnt
            area_weighted[rt] += cnt * avg_area

    return _build_result(count_sum, area_weighted)


def calc_apartments(filepath: Path, status_map: dict) -> dict | None:
    if filepath.suffix == '.xlsx':
        return calc_apartments_xlsx(filepath, status_map)
    return calc_apartments_xlsb(filepath, status_map)


# ── Интерполяция для некорректных периодов ────────────────────────────────────

def interpolate_bad_periods(results: dict) -> dict:
    """
    Для периодов из BAD_PERIODS заменяет значения средним между
    левой и правой граничными точками.
    """
    for bad_date, (left_date, right_date) in BAD_PERIODS.items():
        if left_date not in results or right_date not in results:
            print(f"  Предупреждение: не найдены граничные точки для {bad_date} "
                  f"(нужны {left_date} и {right_date}) — пропускаем")
            continue

        left  = results[left_date]
        right = results[right_date]
        interp = {'count': {}, 'area': {}, 'share': {}}

        for rt in ROOM_TYPES + ['total']:
            lv = left['count'].get(rt)
            rv = right['count'].get(rt)
            interp['count'][rt] = round((lv + rv) / 2) if lv is not None and rv is not None else None

        for rt in ROOM_TYPES + ['total']:
            lv = left['area'].get(rt)
            rv = right['area'].get(rt)
            interp['area'][rt] = round((lv + rv) / 2, 2) if lv is not None and rv is not None else None

        for rt in ROOM_TYPES:
            lv = left['share'].get(rt)
            rv = right['share'].get(rt)
            interp['share'][rt] = round((lv + rv) / 2, 2) if lv is not None and rv is not None else None

        results[bad_date] = interp
        print(f"  Интерполяция {bad_date}: total_count={interp['count'].get('total')}, "
              f"area_total={interp['area'].get('total')}")

    return results


# ── Основная функция ──────────────────────────────────────────────────────────

def main():
    if not DATA_DIR.exists():
        print(f"Папка не найдена: {DATA_DIR}")
        sys.exit(1)

    files = find_all_data_files()
    if not files:
        print(f"Нет файлов в {DATA_DIR}")
        sys.exit(1)

    conn = get_db_conn()
    cur  = conn.cursor()

    all_codes = list(INDICATOR_CODES.values())
    cur.execute("SELECT code, id FROM indicators WHERE code = ANY(%s)", (all_codes,))
    code_to_id = dict(cur.fetchall())

    missing = [c for c in all_codes if c not in code_to_id]
    if missing:
        print(f"ОШИБКА: индикаторы не найдены в БД: {missing}")
        sys.exit(1)

    ids = list(code_to_id.values())
    cur.execute("DELETE FROM data_points WHERE indicator_id = ANY(%s)", (ids,))
    print(f"Удалено существующих точек: {cur.rowcount}")

    # ── Шаг 1: читаем все файлы ──
    results = {}  # {period_date: result_dict}

    for filepath in files:
        period_date = parse_date_from_filename(filepath.name)
        if not period_date:
            print(f"  Пропуск (дата не распознана): {filepath.name}")
            continue

        # Некорректные периоды пропускаем — заполним интерполяцией
        if period_date in BAD_PERIODS:
            print(f"  Пропуск некорректного периода {period_date} ({filepath.name}) → интерполяция")
            continue

        print(f"Обрабатываю {filepath.name} → {period_date} ...", end=' ')
        status_map = load_statuses_from_matrix(period_date)
        if not status_map:
            print(f"\n  Внешний маппинг не найден, используем статус из файла", end=' ')

        result = calc_apartments(filepath, status_map)
        if result is None:
            print("пропущено")
            continue

        print(f"total={result['count']['total']:,}")
        results[period_date] = result

    # ── Шаг 2: интерполяция плохих периодов ──
    print("\nИнтерполяция некорректных периодов...")
    results = interpolate_bad_periods(results)

    # ── Шаг 3: записываем в БД ──
    inserted = 0
    for period_date in sorted(results.keys()):
        result = results[period_date]
        label  = f"{MONTHS_RU[period_date.month]} {period_date.year}"
        rows_to_insert = []

        for key in ROOM_TYPES + ['total']:
            code = INDICATOR_CODES.get(('count', key))
            if code and code in code_to_id:
                rows_to_insert.append((code_to_id[code], period_date, label, result['count'].get(key)))

        for key in ROOM_TYPES + ['total']:
            code = INDICATOR_CODES.get(('area', key))
            if code and code in code_to_id:
                rows_to_insert.append((code_to_id[code], period_date, label, result['area'].get(key)))

        for key in ROOM_TYPES:
            code = INDICATOR_CODES.get(('share', key))
            if code and code in code_to_id:
                rows_to_insert.append((code_to_id[code], period_date, label, result['share'].get(key)))

        for indicator_id, pd_, lbl, val in rows_to_insert:
            if val is None:
                continue
            cur.execute("""
                INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
                VALUES (%s, %s, %s, %s, false)
                ON CONFLICT (indicator_id, period_date) DO UPDATE
                    SET value = EXCLUDED.value,
                        period_label = EXCLUDED.period_label
            """, (indicator_id, pd_, lbl, val))

        inserted += 1

    print("\nОбновляю materialized view ...", end=' ')
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    print("готово")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nГотово. Записано периодов: {inserted}")


if __name__ == '__main__':
    main()
