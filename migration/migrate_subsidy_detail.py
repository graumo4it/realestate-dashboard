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
#  Новая сетка: 6 программ × цели из первоисточника × 2 метрики.
#  Старые агрегированные коды 6.52.1–6.57.3 остаются legacy и здесь не грузятся.
#
#  Период считается валидным для всего листа, только если во всех 12 строках
#  «Нет данных» (6 программ × шт./млн руб.) стоит 0 или пусто. Пустые ячейки
#  внутри валидного периода загружаются как NULL.
# ══════════════════════════════════════════════════════════════════════════════

PROG_CODES_03 = {
    "Все программы":                 "6.52",
    "Льготная ипотека":              "6.53",
    "Семейная ипотека":              "6.54",
    "Дальневосточная и арктическая ипотека": "6.55",
    "IT ипотека":                    "6.56",
    "Ипотека в отдельных регионах":  "6.57",
}

PURPOSE_PATTERNS_03 = [
    ("Покупка квартир по ДКП на вторичке в городах без стройки", "5"),
    ("Покупка квартир по ДКП на вторичке, прочее", "6"),
    ("Покупка квартир по ДКП на вторичке", "5"),
    ("Покупка по ДДУ", "1"),
    ("Покупка по ДКП у застройщика", "2"),
    ("Индивидуальное жилищное строительство", "3"),
    ("Готовый индивидуальный жилой дом", "4"),
]


def _safe_float_or_none(raw):
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_no_data_ok(raw) -> bool:
    val = _safe_float_or_none(raw)
    return val is None or val == 0.0


def extract_sheet_03(ws) -> dict[str, list[tuple]]:
    date_cols = read_date_cols(ws)
    rows = read_full_sheet(ws)

    result: dict[str, list[tuple]] = {}
    current_base = None
    no_data_ok_by_date: dict[datetime.datetime, list[bool]] = {dt: [] for dt in date_cols.values()}
    pending_rows: list[tuple[str, list]] = []

    def metric_suffix(label_str: str) -> str | None:
        if "шт." in label_str:
            return "1"
        if "млн руб" in label_str:
            return "2"
        return None

    def purpose_suffix(label_str: str) -> str | None:
        for pattern, suffix in PURPOSE_PATTERNS_03:
            if pattern in label_str:
                return suffix
        return None

    for row in rows:
        label = row[0]
        if label is None:
            continue
        raw_label = str(label)          # оригинал — для определения отступа
        label_str = raw_label.strip()   # очищенный — для сравнения с паттернами

        if not raw_label.startswith("   "):
            if label_str in PROG_CODES_03:
                current_base = PROG_CODES_03[label_str]
            continue

        if current_base is None:
            continue

        metric = metric_suffix(label_str)
        if metric is None:
            continue

        if "Нет данных" in label_str:
            for col_idx, dt in date_cols.items():
                no_data_ok_by_date[dt].append(_is_no_data_ok(row[col_idx - 1]))
            continue

        purpose = purpose_suffix(label_str)
        if purpose is None:
            continue

        code = f"{current_base}.{purpose}.{metric}"
        pending_rows.append((code, row))

    valid_dates = {
        dt for dt, checks in no_data_ok_by_date.items()
        if len(checks) == len(PROG_CODES_03) * 2 and all(checks)
    }

    for code, row in pending_rows:
        points = []
        for col_idx, dt in date_cols.items():
            if dt not in valid_dates:
                continue
            points.append((dt, _safe_float_or_none(row[col_idx - 1])))
        result[code] = points

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
    Вставляет данные через ON CONFLICT DO UPDATE.
    Пустые ячейки валидных периодов загружаются как NULL.
    Возвращает кол-во вставленных/обновлённых строк.
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
        ]

        if not rows_to_insert:
            print(f"  {code}: нет данных")
            continue

        execute_values(
            cur,
            """
            INSERT INTO data_points
              (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO UPDATE
              SET period_label = EXCLUDED.period_label,
                  value        = EXCLUDED.value
            """,
            rows_to_insert,
        )
        n = cur.rowcount
        inserted += n
        print(f"  {code}: загружено {n}/{len(rows_to_insert)} строк")

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
    print(f"  Извлечено рядов: {len(data_03)}  (ожидается 62)")
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
