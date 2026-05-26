#!/usr/bin/env python3
"""
Загрузка детальных данных по льготной ипотеке из трёх листов
файла Статистические_ряды.xlsx в таблицу data_points.

Предварительно: миграция 008_subsidy_detail.sql должна быть применена.

Листы:
  01_02_05 — Характеристики кредитов → коды 6.46.x–6.51.x
  01_02_03 — Цели кредитования      → коды 6.52.x–6.57.x
  01_02_04 — Типы семей              → коды 6.58.1–6.58.6

Запуск:
  python migrate_subsidy_detail.py [путь/к/Статистические_ряды.xlsx]
"""

import sys
import os
import datetime
import openpyxl
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# ── Загрузка .env ──────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DB = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME",     "realestate"),
    "user":     os.getenv("DB_USER",     "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

EXCEL_PATH = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.path.join(os.path.dirname(__file__), "data", "Статистические_ряды.xlsx")
)

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def period_label(dt: datetime.datetime) -> str:
    return f"{MONTHS_RU[dt.month - 1]} {dt.year}"


# ══════════════════════════════════════════════════════════════════════════════
#  Общая утилита: читаем строку заголовков (row 4) и возвращаем
#  словарь {col_index_1based: datetime} только для столбцов с datetime
# ══════════════════════════════════════════════════════════════════════════════

def read_date_cols(ws) -> dict[int, datetime.datetime]:
    """Возвращает {col (1-based): datetime} из строки 4."""
    date_cols = {}
    for row in ws.iter_rows(min_row=4, max_row=4, values_only=True):
        for col_idx, val in enumerate(row, 1):
            if isinstance(val, datetime.datetime):
                date_cols[col_idx] = val
    return date_cols


def read_full_sheet(ws) -> list[list]:
    """Читает весь лист в список строк (list of lists)."""
    return [list(row) for row in ws.iter_rows(values_only=True)]


# ══════════════════════════════════════════════════════════════════════════════
#  ЛИСТ 01_02_05 — Характеристики кредитов
#  6 программ × 7 метрик = 42 индикатора, коды 6.46.x–6.51.x
# ══════════════════════════════════════════════════════════════════════════════

# Маппинг: имя программы (без пробелов/регистр) → базовый код
PROG_CODES_05 = {
    "Все программы":                 "6.46",
    "Льготная ипотека":              "6.47",
    "Семейная ипотека":              "6.48",
    "Дальневосточная и арктическая ипотека": "6.49",
    "IT ипотека":                    "6.50",
    "Ипотека в отдельных регионах":  "6.51",
}

# Паттерны строк-данных → суффикс индикатора
# Сопоставляем по подстрокам (в порядке приоритета!)
ROW_PATTERNS_05 = [
    ("Средняя сумма кредита",                               ".1"),
    ("Средневзвешенный размер текущей процентной ставки",   ".2"),
    ("Размер собственных средств",                          ".3"),
    ("Средний срок кредита",                                ".4"),
    ("Средняя стоимость помещения",                         ".5"),
    ("Средняя площадь",                                     ".6"),
    ("Средняя стоимость 1",                                 ".7"),
]


def extract_sheet_05(ws) -> dict[str, list[tuple]]:
    """
    Возвращает {код_индикатора: [(datetime, value), ...]}
    """
    date_cols = read_date_cols(ws)
    rows = read_full_sheet(ws)

    result: dict[str, list[tuple]] = {}
    current_base = None

    for row in rows:
        label = row[0]
        if label is None:
            continue
        raw_label = str(label)          # оригинал — для определения отступа
        label_str = raw_label.strip()   # очищенный — для сравнения с паттернами

        if raw_label.startswith("   "):
            # ── Строка данных (есть ведущий отступ) ──
            if current_base is None:
                continue
            suffix = None
            for pattern, sfx in ROW_PATTERNS_05:
                if pattern in label_str:
                    suffix = sfx
                    break
            if suffix is None:
                continue

            code = current_base + suffix
            points = []
            for col_idx, dt in date_cols.items():
                raw = row[col_idx - 1]
                if raw is None:
                    continue
                try:
                    points.append((dt, float(raw)))
                except (TypeError, ValueError):
                    pass
            result[code] = points

        else:
            # ── Заголовок блока программы (нет отступа) ──
            if label_str in PROG_CODES_05:
                current_base = PROG_CODES_05[label_str]
            # else: служебные строки («Перейти в начало», «Программы», и т.д.) — пропуск

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  ЛИСТ 01_02_03 — Цели кредитования
#  6 программ × 3 метрики = 18 индикаторов, коды 6.52.x–6.57.x
#
#  Структура блока на программу (только строки с «шт.»):
#    «Всего, шт.»           — пропускаем
#    «Покупка по ДДУ, шт.» — → .1
#    «... ДКП у застройщика, шт.» — пропускаем
#    «Индивидуальное жилищное строительство, шт.» — → .2 (слагаемое A)
#    «Готовый индивидуальный жилой дом, шт.»       — → .2 (слагаемое B)
#    «... вторичке ..., шт.»  — → .3 (может быть несколько строк!)
#    «Нет данных, шт.»      — пропускаем
#    «Всего, млн руб.»      — сигнал конца шт.-блока (пропускаем до след.программы)
# ══════════════════════════════════════════════════════════════════════════════

PROG_CODES_03 = {
    "Все программы":                 "6.52",
    "Льготная ипотека":              "6.53",
    "Семейная ипотека":              "6.54",
    "Дальневосточная и арктическая ипотека": "6.55",
    "IT ипотека":                    "6.56",
    "Ипотека в отдельных регионах":  "6.57",
}


def sum_series(
    a: list[tuple[datetime.datetime, float]],
    b: list[tuple[datetime.datetime, float]],
) -> list[tuple[datetime.datetime, float]]:
    """Суммирует два ряда по датам. Результат содержит только даты из 'a'."""
    b_map = {dt: v for dt, v in b}
    result = []
    for dt, va in a:
        vb = b_map.get(dt, 0.0)
        result.append((dt, va + vb))
    return result


def extract_sheet_03(ws) -> dict[str, list[tuple]]:
    date_cols = read_date_cols(ws)
    rows = read_full_sheet(ws)

    result: dict[str, list[tuple]] = {}
    current_base = None
    in_sht_block = True   # в блоке шт. (до «Всего, млн руб.»)

    # Накопитель для .2 (сумма ИЖС + Готовый ИЖД)
    acc_ijc: dict[datetime.datetime, float] = {}

    def flush_ijc(base_code: str):
        """Сохраняет накопленный ряд .2 в result."""
        if acc_ijc:
            result[base_code + ".2"] = list(acc_ijc.items())

    def read_row_points(row: list) -> list[tuple[datetime.datetime, float]]:
        pts = []
        for col_idx, dt in date_cols.items():
            raw = row[col_idx - 1]
            if raw is None:
                continue
            try:
                pts.append((dt, float(raw)))
            except (TypeError, ValueError):
                pass
        return pts

    for row in rows:
        label = row[0]
        if label is None:
            continue
        raw_label = str(label)          # оригинал — для определения отступа
        label_str = raw_label.strip()   # очищенный — для сравнения с паттернами

        if not raw_label.startswith("   "):
            # ── Нет отступа: либо заголовок блока программы, либо служебная строка ──
            if label_str in PROG_CODES_03:
                # Завершаем предыдущий шт.-блок
                if current_base is not None:
                    flush_ijc(current_base)
                acc_ijc = {}
                in_sht_block = True
                current_base = PROG_CODES_03[label_str]
            # else: «Всего, шт.», «Всего, млн руб.», «Программы», заголовки — пропуск
            continue

        # ── Есть отступ: строка данных ──
        if current_base is None:
            continue

        # Переключатель шт. → млн руб. внутри блока
        if "млн руб" in label_str:
            if in_sht_block:
                flush_ijc(current_base)
                acc_ijc = {}
                in_sht_block = False
            continue  # млн руб. строки нас не интересуют

        if not in_sht_block:
            continue

        # ── .1: ДДУ ──
        if "Покупка по ДДУ" in label_str and "шт." in label_str:
            result[current_base + ".1"] = read_row_points(row)

        # ── .2: ИЖС (накапливаем) ──
        elif ("Индивидуальное жилищное строительство" in label_str
              or "Готовый индивидуальный жилой дом" in label_str) and "шт." in label_str:
            for dt, v in read_row_points(row):
                acc_ijc[dt] = acc_ijc.get(dt, 0.0) + v

        # ── .3: Вторичка (накапливаем все строки с «вторичке») ──
        elif "вторичке" in label_str.lower() and "шт." in label_str:
            code3 = current_base + ".3"
            pts = read_row_points(row)
            if code3 in result:
                existing_map = {dt: v for dt, v in result[code3]}
                for dt, v in pts:
                    existing_map[dt] = existing_map.get(dt, 0.0) + v
                result[code3] = list(existing_map.items())
            else:
                result[code3] = pts

    # Последний блок
    if current_base is not None:
        flush_ijc(current_base)

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  ЛИСТ 01_02_04 — Типы семей Семейной ипотеки
#  6 индикаторов: 6.58.1–6.58.6
# ══════════════════════════════════════════════════════════════════════════════

ROW_PATTERNS_04 = [
    ("Семьи с ребенком до 7 лет, шт",         "6.58.1"),
    ("Семьи с детьми до 18 лет, шт",          "6.58.2"),
    ("Дети с инвалидностью, шт",              "6.58.3"),
    ("Семьи с ребенком до 7 лет, млн руб",    "6.58.4"),
    ("Семьи с детьми до 18 лет, млн руб",     "6.58.5"),
    ("Дети с инвалидностью, млн руб",         "6.58.6"),
]


def extract_sheet_04(ws) -> dict[str, list[tuple]]:
    date_cols = read_date_cols(ws)
    rows = read_full_sheet(ws)
    result: dict[str, list[tuple]] = {}

    for row in rows:
        label = row[0]
        if label is None:
            continue
        label_str = str(label).strip()

        for pattern, code in ROW_PATTERNS_04:
            if pattern in label_str:
                pts = []
                for col_idx, dt in date_cols.items():
                    raw = row[col_idx - 1]
                    if raw is None:
                        continue
                    try:
                        pts.append((dt, float(raw)))
                    except (TypeError, ValueError):
                        pass
                result[code] = pts
                break

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Загрузка в БД
# ══════════════════════════════════════════════════════════════════════════════

def upsert_data(cur, ind_map: dict[str, int], data: dict[str, list[tuple]]) -> int:
    """
    Вставляет данные через ON CONFLICT DO NOTHING.
    Возвращает кол-во вставленных строк.
    """
    inserted = 0
    for code, points in sorted(data.items()):
        ind_id = ind_map.get(code)
        if ind_id is None:
            print(f"  ⚠️  {code}: индикатор не найден в БД — пропуск")
            continue

        rows_to_insert = [
            (ind_id, dt.date(), period_label(dt), val, False)
            for dt, val in points
            # пропускаем None и нули (None уже отфильтрованы при чтении)
        ]

        if not rows_to_insert:
            print(f"  {code}: нет данных")
            continue

        before = cur.rowcount if cur.rowcount >= 0 else 0

        execute_values(
            cur,
            """
            INSERT INTO data_points
              (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO NOTHING
            """,
            rows_to_insert,
        )
        n = cur.rowcount
        inserted += n
        print(f"  {code}: вставлено {n}/{len(rows_to_insert)} строк")

    return inserted


# ══════════════════════════════════════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"Читаем: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True)

    # ── Извлечение данных из трёх листов ──────────────────────────────────────
    print("\n─── Лист 01_02_05 (Характеристики кредитов) ───")
    data_05 = extract_sheet_05(wb["01_02_05"])
    print(f"  Извлечено рядов: {len(data_05)}  (ожидается 42)")
    for code in sorted(data_05):
        n = len(data_05[code])
        print(f"    {code}: {n} точек")

    print("\n─── Лист 01_02_03 (Цели кредитования) ───")
    data_03 = extract_sheet_03(wb["01_02_03"])
    print(f"  Извлечено рядов: {len(data_03)}  (ожидается 18)")
    for code in sorted(data_03):
        n = len(data_03[code])
        print(f"    {code}: {n} точек")

    print("\n─── Лист 01_02_04 (Типы семей) ───")
    data_04 = extract_sheet_04(wb["01_02_04"])
    print(f"  Извлечено рядов: {len(data_04)}  (ожидается 6)")
    for code in sorted(data_04):
        n = len(data_04[code])
        print(f"    {code}: {n} точек")

    # ── Подключение к БД ──────────────────────────────────────────────────────
    print("\nПодключаемся к БД...")
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # Загружаем словарь code → indicator_id для всех нужных кодов
    all_codes = list(data_05) + list(data_03) + list(data_04)
    if not all_codes:
        print("Нет данных для загрузки.")
        conn.close()
        return

    cur.execute(
        "SELECT code, id FROM indicators WHERE code = ANY(%s)",
        (all_codes,),
    )
    ind_map: dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}
    print(f"  Найдено индикаторов в БД: {len(ind_map)}/{len(all_codes)}")

    # ── Upsert ────────────────────────────────────────────────────────────────
    print("\n─── Загрузка 01_02_05 ───")
    n05 = upsert_data(cur, ind_map, data_05)

    print("\n─── Загрузка 01_02_03 ───")
    n03 = upsert_data(cur, ind_map, data_03)

    print("\n─── Загрузка 01_02_04 ───")
    n04 = upsert_data(cur, ind_map, data_04)

    print(f"\n  Итого вставлено: {n05 + n03 + n04} строк")
    print(f"    01_02_05: {n05}")
    print(f"    01_02_03: {n03}")
    print(f"    01_02_04: {n04}")

    # ── Обновляем materialized view ───────────────────────────────────────────
    print("\nОбновляем materialized view...")
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")

    conn.commit()
    cur.close()
    conn.close()
    print("\n✅ Готово!")


if __name__ == "__main__":
    main()
