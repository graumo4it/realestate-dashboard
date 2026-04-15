"""
Миграция данных из Excel → PostgreSQL
Файл: Статистика_рынка_жилой_недвижимости_России_*.xlsx
"""

import os
import re
import sys
import logging
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── Конфигурация подключения ────────────────────────────────────────────────

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "realestate"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ─── Маппинг листов Excel ────────────────────────────────────────────────────

SHEET_META = {
    # sheet_name: (category_code, source_code, pattern, period_type, periodicity)
    "1.1-1.3 Макроданные":            ("macro",              "rosstat", "C",       "period",        "annual"),
    "2.1-2.5 Объем ввода жилья":      ("supply_volume",      "rosstat", "B-cum",   "period",        "monthly"),
    "2.6-2.8 Объем ввода на душу":    ("supply_per_capita",  "rosstat", "B-cum",   "period",        "monthly"),
    "2.9-2.13 Жилфонд":               ("housing_stock",      "rosstat", "C",       "point_in_time", "annual"),
    "3.1-3.7 Строящ жилье (основные)":("under_construction", "domrf",   "A",       "point_in_time", "monthly"),
    "3.13-3.16 Квартирография":       ("apartments",         "domrf",   "A",       "point_in_time", "monthly"),
    "3.17-3.19 Ур-нь конк-ции Дом.рф":("concentration",     "domrf",   "A",       "point_in_time", "monthly"),
    "4.1 Цены (Дом.рф)":              ("prices",             "domrf",   "B-simple","period",        "monthly"),
    "4.4-4.5 Цены (Росстат)":         ("prices",             "rosstat", "B-simple","period",        "monthly"),
    "4.8-4.9 Цены на паркинг Дом.рф": ("prices",            "domrf",   "B-simple","period",        "monthly"),
    "5.1-5.2 Спрос (Росреестр)":      ("demand",             "rosreestr","B-cum",  "period",        "monthly"),
    "5.3-5.4 Активность спроса":      ("demand",             "rosreestr","B-simple","period",       "monthly"),
    "5.8-5.9 Спрос (Дом.рф)":         ("demand",            "domrf",   "B-simple","period",        "monthly"),
    "5.10-5.11 Доступность жилья":    ("demand",             "rosstat", "C",       "period",        "annual"),
    "5.12-5.15 Уровень потребности":  ("demand",             "rosstat", "C",       "period",        "annual"),
    "5.20-5.22 Спрос паркинг Дом.рф": ("demand",            "domrf",   "B-simple","period",        "monthly"),
    "6.1-6.6 Ипотека всего (БР)":     ("mortgage_total",     "cbr",     "B-cum",   "period",        "monthly"),
    "6.7-6.12 Ипотека первич (БР)":   ("mortgage_primary",   "cbr",     "B-cum",   "period",        "monthly"),
    "6.13-6.18 Ипотека вторич (БР)":  ("mortgage_secondary", "cbr",     "B-cum",   "period",        "monthly"),
    "6.19-6.27 Ипотека (задолжен)":   ("mortgage_debt",      "cbr",     "A",       "point_in_time", "monthly"),
    "6.28-6.34 Ипотека (Домклик)":    ("mortgage_domclick",  "domclick","B-simple","period",        "monthly"),
    "6.35 Ипотека (Frank RG)":        ("mortgage_frankrg",   "cbr",     "B-simple","period",        "monthly"),
    "6.36-6.45 Господдержка всего":   ("mortgage_subsidy",   "cbr",     "B-simple","period",        "monthly"),
    "6.46-6.55 Господдержка ДДУ":     ("mortgage_subsidy",   "cbr",     "B-simple","period",        "monthly"),
    "6.56-6.65 Доля ГП ДДУ":          ("mortgage_subsidy",   "cbr",     "B-simple","period",        "monthly"),
    "6.66-6.67 Доля ипотеки в ДДУ":   ("mortgage_subsidy",   "cbr",     "B-simple","period",        "monthly"),
    "6.70-6.75 Ипотека ИЖС всего БР": ("mortgage_igs",       "cbr",     "B-cum",   "period",        "monthly"),
    "6.76-6.81 Ипотека ИЖС созд БР":  ("mortgage_igs",       "cbr",     "B-cum",   "period",        "monthly"),
    "6.82-6.87 Ипотека ИЖС покуп БР": ("mortgage_igs",       "cbr",     "B-cum",   "period",        "monthly"),
}

MONTH_MAP = {
    "январь": 1,  "февраль": 2,  "март": 3,    "апрель": 4,
    "май": 5,     "июнь": 6,     "июль": 7,    "август": 8,
    "сентябрь": 9,"октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

# ─── Вспомогательные функции ─────────────────────────────────────────────────

def get_visible_sheets(filepath: str) -> list[str]:
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    visible = [
        name for name in wb.sheetnames
        if wb[name].sheet_state == "visible" and name != "Содержание"
    ]
    wb.close()
    return visible


def extract_indicator_code(text: str) -> str | None:
    """Извлекает код вида '6.1' из строки заголовка блока."""
    m = re.match(r"^(\d+\.\d+)\s", str(text).strip())
    return m.group(1) if m else None


def extract_unit(text: str) -> str:
    """Извлекает единицу измерения из названия показателя."""
    patterns = [
        r"\(([^)]*(?:руб\.|кв\. ?м|ед\.|%|млн|млрд|тыс\.|лет|чел)[^)]*)\)",
        r",\s*(млн руб\.|тыс\. кв\. м|тыс\. ед\.|%|руб\.|кв\. м|ед\.)",
    ]
    for p in patterns:
        m = re.search(p, str(text), re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def parse_value(v) -> float | None:
    """Парсит ячейку в float, возвращает None для 'х' и пустых."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "х", "x", "-", "н/д", "н.д.", "…", "..."):
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def is_dynamic_col(col_header: str) -> bool:
    """Колонки с '/' в заголовке — это динамика, пропускаем."""
    return "/" in str(col_header)


def month_to_date(month_str: str, year: int) -> date | None:
    m = MONTH_MAP.get(str(month_str).strip().lower())
    if m:
        return date(year, m, 1)
    return None

# ─── Парсеры по паттернам ────────────────────────────────────────────────────

def parse_pattern_A(df: pd.DataFrame) -> list[dict]:
    """
    ПАТТЕРН A: данные на дату (point_in_time), первый столбец = datetime.
    Листы: 3.x, 6.19-6.27
    """
    records = []
    # Ищем блоки: строки-заголовки с кодом показателя
    header_rows = []
    for idx, row in df.iterrows():
        first = str(row.iloc[0]).strip() if row.iloc[0] is not None else ""
        code = extract_indicator_code(first)
        if code:
            header_rows.append((idx, code, first))

    for i, (h_idx, code, title) in enumerate(header_rows):
        # Строка заголовков столбцов
        col_row_idx = h_idx + 1
        if col_row_idx >= len(df):
            continue
        col_headers = df.iloc[col_row_idx].tolist()

        # Определяем годовые столбцы (числа, без '/')
        year_cols = {}
        for j, h in enumerate(col_headers):
            if j == 0:
                continue
            try:
                y = int(float(str(h)))
                if 2011 <= y <= 2030 and not is_dynamic_col(str(h)):
                    year_cols[j] = y
            except (ValueError, TypeError):
                pass

        # Строки данных
        data_start = col_row_idx + 1
        data_end = header_rows[i + 1][0] if i + 1 < len(header_rows) else len(df)

        for r_idx in range(data_start, data_end):
            row = df.iloc[r_idx]
            date_val = row.iloc[0]
            if pd.isnull(date_val) or str(date_val).strip() == "":
                continue
            try:
                if isinstance(date_val, (pd.Timestamp, date)):
                    period_date = pd.Timestamp(date_val).date()
                else:
                    period_date = pd.Timestamp(str(date_val)).date()
            except Exception:
                continue

            for col_j, year in year_cols.items():
                v = parse_value(row.iloc[col_j])
                if v is not None:
                    records.append({
                        "indicator_code": code,
                        "indicator_name": title,
                        "period_date": period_date,
                        "period_label": period_date.strftime("%B %Y"),
                        "value": v,
                    })
    return records


def parse_pattern_B_simple(df: pd.DataFrame) -> list[dict]:
    """
    ПАТТЕРН B-simple: один столбец на год, строки = месяцы.
    """
    records = []
    header_rows = []
    for idx, row in df.iterrows():
        first = str(row.iloc[0]).strip() if row.iloc[0] is not None else ""
        code = extract_indicator_code(first)
        if code:
            header_rows.append((idx, code, first))

    for i, (h_idx, code, title) in enumerate(header_rows):
        col_row_idx = h_idx + 1
        if col_row_idx >= len(df):
            continue
        col_headers = df.iloc[col_row_idx].tolist()

        year_cols = {}
        for j, h in enumerate(col_headers):
            if j == 0:
                continue
            if is_dynamic_col(str(h)):
                continue
            try:
                y = int(float(str(h)))
                if 2011 <= y <= 2030:
                    year_cols[j] = y
            except (ValueError, TypeError):
                pass

        data_start = col_row_idx + 1
        data_end = header_rows[i + 1][0] if i + 1 < len(header_rows) else len(df)

        for r_idx in range(data_start, data_end):
            row = df.iloc[r_idx]
            month_str = str(row.iloc[0]).strip().lower()
            if month_str in ("итого", "итог", "всего", ""):
                continue
            if month_str not in MONTH_MAP:
                continue

            for col_j, year in year_cols.items():
                v = parse_value(row.iloc[col_j])
                if v is not None:
                    period_date = date(year, MONTH_MAP[month_str], 1)
                    records.append({
                        "indicator_code": code,
                        "indicator_name": title,
                        "period_date": period_date,
                        "period_label": f"{row.iloc[0].strip()} {year}",
                        "value": v,
                    })
    return records


def parse_pattern_B_cum(df: pd.DataFrame) -> list[dict]:
    """
    ПАТТЕРН B-cum: два подстолбца на год ('за период с начала года' и 'в том числе месяц').
    Берём только 'в том числе месяц'.
    """
    records = []
    header_rows = []
    for idx, row in df.iterrows():
        first = str(row.iloc[0]).strip() if row.iloc[0] is not None else ""
        code = extract_indicator_code(first)
        if code:
            header_rows.append((idx, code, first))

    for i, (h_idx, code, title) in enumerate(header_rows):
        # Два ряда заголовков: год (row +1) и подтип (row +2)
        year_row_idx = h_idx + 1
        sub_row_idx = h_idx + 2
        if sub_row_idx >= len(df):
            continue

        year_headers = df.iloc[year_row_idx].tolist()
        sub_headers = df.iloc[sub_row_idx].tolist()

        # Заполняем год вперёд (merged cells представлены как NaN после первого)
        current_year = None
        month_cols = []  # (col_index, year)
        for j, (yh, sh) in enumerate(zip(year_headers, sub_headers)):
            if j == 0:
                continue
            if is_dynamic_col(str(yh)):
                continue
            try:
                y = int(float(str(yh)))
                if 2011 <= y <= 2030:
                    current_year = y
            except (ValueError, TypeError):
                pass
            if current_year and "месяц" in str(sh).lower():
                month_cols.append((j, current_year))

        data_start = sub_row_idx + 1
        data_end = header_rows[i + 1][0] if i + 1 < len(header_rows) else len(df)

        for r_idx in range(data_start, data_end):
            row = df.iloc[r_idx]
            month_str = str(row.iloc[0]).strip().lower()
            if month_str in ("итого", "итог", "всего", ""):
                continue
            if month_str not in MONTH_MAP:
                continue

            for col_j, year in month_cols:
                v = parse_value(row.iloc[col_j])
                if v is not None:
                    period_date = date(year, MONTH_MAP[month_str], 1)
                    records.append({
                        "indicator_code": code,
                        "indicator_name": title,
                        "period_date": period_date,
                        "period_label": f"{row.iloc[0].strip()} {year}",
                        "value": v,
                    })
    return records


def parse_pattern_C(df: pd.DataFrame) -> list[dict]:
    """
    ПАТТЕРН C: годовые данные, первый столбец = 'Год' или годовые строки.
    """
    records = []
    header_rows = []
    for idx, row in df.iterrows():
        first = str(row.iloc[0]).strip() if row.iloc[0] is not None else ""
        code = extract_indicator_code(first)
        if code:
            header_rows.append((idx, code, first))

    for i, (h_idx, code, title) in enumerate(header_rows):
        col_row_idx = h_idx + 1
        if col_row_idx >= len(df):
            continue

        col_headers = df.iloc[col_row_idx].tolist()
        # Для паттерна C: строки — это годы, столбцы могут быть показателями
        # или наоборот: столбцы — годы.
        # Определяем структуру: если первый столбец = 'Год', то строки — годы
        first_col = str(col_headers[0]).strip().lower()
        if "год" in first_col or "year" in first_col:
            # Структура: строки — годы, data_col = 1
            data_start = col_row_idx + 1
            data_end = header_rows[i + 1][0] if i + 1 < len(header_rows) else len(df)
            for r_idx in range(data_start, data_end):
                row = df.iloc[r_idx]
                year_val = row.iloc[0]
                try:
                    year = int(float(str(year_val)))
                    if not (2011 <= year <= 2030):
                        continue
                except (ValueError, TypeError):
                    continue
                v = parse_value(row.iloc[1]) if len(row) > 1 else None
                if v is not None:
                    records.append({
                        "indicator_code": code,
                        "indicator_name": title,
                        "period_date": date(year, 1, 1),
                        "period_label": str(year),
                        "value": v,
                    })
        else:
            # Структура: столбцы — годы
            year_cols = {}
            for j, h in enumerate(col_headers):
                if j == 0:
                    continue
                if is_dynamic_col(str(h)):
                    continue
                try:
                    y = int(float(str(h)))
                    if 2011 <= y <= 2030:
                        year_cols[j] = y
                except (ValueError, TypeError):
                    pass

            data_start = col_row_idx + 1
            data_end = header_rows[i + 1][0] if i + 1 < len(header_rows) else len(df)
            for r_idx in range(data_start, data_end):
                row = df.iloc[r_idx]
                row_label = str(row.iloc[0]).strip().lower()
                if row_label in ("итого", "итог", ""):
                    continue
                for col_j, year in year_cols.items():
                    v = parse_value(row.iloc[col_j])
                    if v is not None:
                        records.append({
                            "indicator_code": code,
                            "indicator_name": title,
                            "period_date": date(year, 1, 1),
                            "period_label": str(year),
                            "value": v,
                        })
    return records

# ─── Работа с БД ─────────────────────────────────────────────────────────────

def get_or_create_indicator(
    cur, code: str, name: str, category_code: str,
    source_code: str, period_type: str, periodicity: str, unit: str
) -> int:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("SELECT id FROM categories WHERE code = %s", (category_code,))
    cat = cur.fetchone()
    category_id = cat[0] if cat else None

    cur.execute("SELECT id FROM sources WHERE code = %s", (source_code,))
    src = cur.fetchone()
    source_id = src[0] if src else None

    cur.execute("""
        INSERT INTO indicators (code, name, category_id, source_id, period_type, periodicity, unit)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (code, name, category_id, source_id, period_type, periodicity, unit))
    return cur.fetchone()[0]


def upsert_data_points(cur, rows: list[tuple]) -> int:
    if not rows:
        return 0
    execute_values(cur, """
        INSERT INTO data_points (indicator_id, period_date, period_label, value)
        VALUES %s
        ON CONFLICT (indicator_id, period_date)
        DO UPDATE SET value = EXCLUDED.value, period_label = EXCLUDED.period_label
    """, rows)
    return len(rows)

# ─── Основной процесс ────────────────────────────────────────────────────────

def migrate(filepath: str):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    visible_sheets = get_visible_sheets(filepath)
    total_rows = 0

    for sheet_name in visible_sheets:
        if sheet_name not in SHEET_META:
            log.info(f"SKIPPED (no meta): {sheet_name}")
            continue

        category_code, source_code, pattern, period_type, periodicity = SHEET_META[sheet_name]

        try:
            df = pd.read_excel(filepath, sheet_name=sheet_name, header=None)
        except Exception as e:
            log.error(f"ERROR reading sheet '{sheet_name}': {e}")
            continue

        try:
            if pattern == "A":
                records = parse_pattern_A(df)
            elif pattern == "B-simple":
                records = parse_pattern_B_simple(df)
            elif pattern == "B-cum":
                records = parse_pattern_B_cum(df)
            elif pattern == "C":
                records = parse_pattern_C(df)
            else:
                log.warning(f"Unknown pattern '{pattern}' for sheet '{sheet_name}'")
                continue
        except Exception as e:
            log.error(f"ERROR parsing sheet '{sheet_name}': {e}", exc_info=True)
            continue

        # Группируем по показателям
        by_indicator: dict[str, list] = {}
        for r in records:
            key = r["indicator_code"]
            by_indicator.setdefault(key, []).append(r)

        sheet_rows = 0
        for ind_code, ind_records in by_indicator.items():
            first = ind_records[0]
            unit = extract_unit(first["indicator_name"])
            ind_id = get_or_create_indicator(
                cur, ind_code, first["indicator_name"],
                category_code, source_code, period_type, periodicity, unit
            )
            rows = [
                (ind_id, r["period_date"], r["period_label"], r["value"])
                for r in ind_records
            ]
            upserted = upsert_data_points(cur, rows)
            sheet_rows += upserted

        conn.commit()
        total_rows += sheet_rows
        log.info(f"SUCCESS: {sheet_name} | indicators={len(by_indicator)} | points={sheet_rows}")

    # Обновляем materialized view
    log.info("Refreshing materialized view data_points_with_dynamics...")
    try:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
        conn.commit()
    except Exception as e:
        log.warning(f"Could not refresh materialized view: {e}")

    cur.close()
    conn.close()
    log.info(f"Migration complete. Total rows upserted: {total_rows}")


if __name__ == "__main__":
    excel_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/Статистика_рынка_жилой_недвижимости_России.xlsx")
    if not excel_path.exists():
        log.error(f"File not found: {excel_path}")
        sys.exit(1)
    migrate(str(excel_path))
