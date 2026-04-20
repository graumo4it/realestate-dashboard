"""
migration/excel_to_db.py

Одноразовый импорт данных из Excel-файла в PostgreSQL.
Использование: python migration/excel_to_db.py

Требует .env файл с: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
Excel-файл ожидается в: migration/data/<имя файла>.xlsx
"""

from __future__ import annotations

import os
import re
import sys
import math
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import numpy as np
import openpyxl
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ─── Загрузка .env ───────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent.parent / ".env")

# ─── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ─── Константы ───────────────────────────────────────────────────────────────

MONTH_MAP = {
    "январь": 1,  "февраль": 2,  "март": 3,    "апрель": 4,
    "май": 5,     "июнь": 6,     "июль": 7,    "август": 8,
    "сентябрь": 9,"октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

SKIP_ROW_LABELS = {
    "итого", "динамика", "динамика (к предыдущему периоду)",
    "динамика (к соответствующему периоду прошлого года)",
    "абсолютные значение", "абсолютные значения",
    "источник данных:", "источник данных",
    "дата последнего обновления:", "дата последнего обновления",
    "к содержанию", "месяц", "дата", "год", "квартал",
    "за год", "среднее га год", "среднее за год",
    "январь-март", "январь-июнь", "январь-сентябрь", "январь-декабрь",
    "-",
}

SHEET_PATTERN = {
    "1.1-1.3 Макроданные":                  "C",
    "2.1-2.5 Объем ввода жилья":            "B-cum",
    "2.6-2.8 Объем ввода на душу":          "B-cum",
    "2.9-2.13 Жилфонд":                     "C",
    "3.1-3.7 Строящ жилье (основные)":      "A",
    "3.13-3.16 Квартирография":             "A",
    "3.17-3.19 Ур-нь конк-ции Дом.рф":     "A",
    "4.1 Цены (Дом.рф)":                    "B-simple",
    "4.4-4.5 Цены (Росстат)":               "C",
    "4.8-4.9 Цены на паркинг Дом.рф":      "B-simple",
    "5.1-5.2 Спрос (Росреестр)":           "B-cum",
    "5.3-5.4 Активность спроса":            "C",
    "5.8-5.9 Спрос (Дом.рф)":              "B-simple",
    "5.10-5.11 Доступность жилья":          "C",
    "5.12-5.15 Уровень потребности":        "C",
    "5.20-5.22 Спрос паркинг Дом.рф":      "B-simple",
    "6.1-6.6 Ипотека всего (БР)":          "B-cum",
    "6.7-6.12 Ипотека первич (БР)":        "B-cum",
    "6.13-6.18 Ипотека вторич (БР)":       "B-cum",
    "6.19-6.27 Ипотека (задолжен)":        "A",
    "6.28-6.34 Ипотека (Домклик)":         "B-simple",
    "6.35 Ипотека (Frank RG)":             "A",
    "6.36-6.45 Господдержка всего":         "B-simple",
    "6.46-6.55 Господдержка ДДУ":          "B-simple",
    "6.56-6.65 Доля ГП ДДУ":              "B-simple",
    "6.66-6.67 Доля ипотеки в ДДУ":       "C",
    "6.70-6.75 Ипотека ИЖС всего БР":      "B-cum",
    "6.76-6.81 Ипотека ИЖС созд БР":       "B-cum",
    "6.82-6.87 Ипотека ИЖС покуп БР":      "B-cum",
}

SHEET_CATEGORY = {
    "1.1-1.3 Макроданные":                  "macro",
    "2.1-2.5 Объем ввода жилья":            "supply_volume",
    "2.6-2.8 Объем ввода на душу":          "supply_per_capita",
    "2.9-2.13 Жилфонд":                     "housing_stock",
    "3.1-3.7 Строящ жилье (основные)":      "under_construction",
    "3.13-3.16 Квартирография":             "apartments",
    "3.17-3.19 Ур-нь конк-ции Дом.рф":     "concentration",
    "4.1 Цены (Дом.рф)":                    "prices",
    "4.4-4.5 Цены (Росстат)":               "prices",
    "4.8-4.9 Цены на паркинг Дом.рф":      "prices",
    "5.1-5.2 Спрос (Росреестр)":           "demand",
    "5.3-5.4 Активность спроса":            "demand",
    "5.8-5.9 Спрос (Дом.рф)":              "demand",
    "5.10-5.11 Доступность жилья":          "demand",
    "5.12-5.15 Уровень потребности":        "demand",
    "5.20-5.22 Спрос паркинг Дом.рф":      "demand",
    "6.1-6.6 Ипотека всего (БР)":          "mortgage_total",
    "6.7-6.12 Ипотека первич (БР)":        "mortgage_primary",
    "6.13-6.18 Ипотека вторич (БР)":       "mortgage_secondary",
    "6.19-6.27 Ипотека (задолжен)":        "mortgage_debt",
    "6.28-6.34 Ипотека (Домклик)":         "mortgage_domclick",
    "6.35 Ипотека (Frank RG)":             "mortgage_frankrg",
    "6.36-6.45 Господдержка всего":         "mortgage_subsidy",
    "6.46-6.55 Господдержка ДДУ":          "mortgage_subsidy",
    "6.56-6.65 Доля ГП ДДУ":              "mortgage_subsidy",
    "6.66-6.67 Доля ипотеки в ДДУ":       "mortgage_subsidy",
    "6.70-6.75 Ипотека ИЖС всего БР":      "mortgage_igs",
    "6.76-6.81 Ипотека ИЖС созд БР":       "mortgage_igs",
    "6.82-6.87 Ипотека ИЖС покуп БР":      "mortgage_igs",
}

SHEET_SOURCE = {
    "1.1-1.3 Макроданные":                  "rosstat",
    "2.1-2.5 Объем ввода жилья":            "rosstat",
    "2.6-2.8 Объем ввода на душу":          "rosstat",
    "2.9-2.13 Жилфонд":                     "rosstat",
    "3.1-3.7 Строящ жилье (основные)":      "domrf",
    "3.13-3.16 Квартирография":             "domrf",
    "3.17-3.19 Ур-нь конк-ции Дом.рф":     "domrf",
    "4.1 Цены (Дом.рф)":                    "domrf",
    "4.4-4.5 Цены (Росстат)":               "rosstat",
    "4.8-4.9 Цены на паркинг Дом.рф":      "domrf",
    "5.1-5.2 Спрос (Росреестр)":           "rosreestr",
    "5.3-5.4 Активность спроса":            "rosreestr",
    "5.8-5.9 Спрос (Дом.рф)":              "domrf",
    "5.10-5.11 Доступность жилья":          "rosstat",
    "5.12-5.15 Уровень потребности":        "rosstat",
    "5.20-5.22 Спрос паркинг Дом.рф":      "domrf",
    "6.1-6.6 Ипотека всего (БР)":          "cbr",
    "6.7-6.12 Ипотека первич (БР)":        "cbr",
    "6.13-6.18 Ипотека вторич (БР)":       "cbr",
    "6.19-6.27 Ипотека (задолжен)":        "cbr",
    "6.28-6.34 Ипотека (Домклик)":         "domclick",
    "6.35 Ипотека (Frank RG)":             "cbr",
    "6.36-6.45 Господдержка всего":         "cbr",
    "6.46-6.55 Господдержка ДДУ":          "cbr",
    "6.56-6.65 Доля ГП ДДУ":              "cbr",
    "6.66-6.67 Доля ипотеки в ДДУ":       "cbr",
    "6.70-6.75 Ипотека ИЖС всего БР":      "cbr",
    "6.76-6.81 Ипотека ИЖС созд БР":       "cbr",
    "6.82-6.87 Ипотека ИЖС покуп БР":      "cbr",
}

SOURCES_SEED = [
    ("cbr",       "Банк России",  "https://cbr.ru",              "monthly"),
    ("emiss",     "ЕМИСС",        "https://www.fedstat.ru",       "monthly"),
    ("domrf",     "ДОМ.РФ",       "https://наш.дом.рф",          "daily"),
    ("rosstat",   "Росстат",      "https://rosstat.gov.ru",       "monthly"),
    ("domclick",  "Домклик",      "https://domclick.ru",          "daily"),
    ("sberindex", "Сбериндекс",   "https://sberindex.ru",         "daily"),
    ("rosreestr", "Росреестр",    "https://rosreestr.gov.ru",     "monthly"),
]

CATEGORIES_SEED = [
    ("macro",              "Макроданные",             1),
    ("supply_volume",      "Объём ввода жилья",       2),
    ("supply_per_capita",  "Ввод жилья на душу",      3),
    ("housing_stock",      "Жилищный фонд",           4),
    ("under_construction", "Строящееся жильё",        5),
    ("apartments",         "Квартирография",          6),
    ("concentration",      "Уровень концентрации",    7),
    ("prices",             "Цены",                    8),
    ("demand",             "Спрос",                   9),
    ("mortgage_total",     "Ипотека (всего)",        10),
    ("mortgage_primary",   "Ипотека (первичный)",    11),
    ("mortgage_secondary", "Ипотека (вторичный)",    12),
    ("mortgage_debt",      "Ипотека (задолженность)",13),
    ("mortgage_domclick",  "Ипотека (Домклик)",      14),
    ("mortgage_frankrg",   "Ипотека (Frank RG)",     15),
    ("mortgage_subsidy",   "Господдержка",           16),
    ("mortgage_igs",       "Ипотека ИЖС",            17),
]


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def to_float(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, np.integer)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(v, (int, float)):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)
    if isinstance(v, pd.Timestamp):
        return None
    s = str(v).strip()
    if s in ("х", "x", "X", "Х", "-", "–", "н/д", "", "nan", "NaN", "None"):
        return None
    s = s.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        f = float(s)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def cell_str(v):
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    if isinstance(v, pd.Timestamp):
        return ""
    return str(v).strip()


def is_year(v):
    try:
        f = float(str(v).strip())
        if f != int(f):
            return False
        y = int(f)
        return 2000 <= y <= 2035
    except (ValueError, TypeError, AttributeError):
        return False


def is_dynamic_col(v):
    s = cell_str(v)
    return "/" in s or s.lower().startswith("к соответствующему") or s.lower().startswith("динамика")


def extract_code(text):
    if not isinstance(text, str):
        return None
    m = re.match(r"^\s*(\d{1,2}\.\d{1,3}(?:\.\d{1,2})?[а-яёa-z]?)\s+\D", text.strip())
    return m.group(1) if m else None


def extract_unit(name):
    if not isinstance(name, str):
        return ""
    m = re.search(r"\(([^)]+)\)\s*$", name)
    if m:
        return m.group(1).strip()
    for kw in ["млн.руб.", "млн руб.", "тыс. руб.", "руб.", "тыс. кв. м", "кв. м",
               "тыс. ед.", "ед.", "%", "лет", "п.п.", "тыс.", "млн."]:
        if kw in name:
            return kw
    return ""


def make_label(d, periodicity):
    months_ru = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                 "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    if periodicity == "annual":
        return str(d.year)
    return f"{months_ru[d.month]} {d.year}"


def to_date(v):
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    parts = cell_str(v).split()
    if not parts:
        return None
    s = parts[0]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ─── Поиск блоков показателей ────────────────────────────────────────────────

def find_indicator_rows(df):
    results = []
    nrows = df.shape[0]
    for i in range(nrows):
        v = df.iloc[i, 0]
        s = cell_str(v)
        code = extract_code(s)
        if code:
            results.append((i, code, s))
    return results


# ─── ПАТТЕРН A ───────────────────────────────────────────────────────────────

def parse_A(df):
    records = []
    nrows, ncols = df.shape
    indicator_rows = find_indicator_rows(df)

    for idx, (row_i, code, full_name) in enumerate(indicator_rows):
        next_row = indicator_rows[idx + 1][0] if idx + 1 < len(indicator_rows) else nrows

        header_row = None
        for r in range(row_i + 1, min(row_i + 5, next_row)):
            row_vals = df.iloc[r].tolist()
            if any(is_year(v) and not is_dynamic_col(v) for v in row_vals):
                header_row = r
                break

        if header_row is not None:
            headers = df.iloc[header_row].tolist()
            seen_years = set()
            year_cols = []
            for ci, h in enumerate(headers):
                if is_year(h) and not is_dynamic_col(h):
                    yr = int(float(str(h)))
                    if yr not in seen_years:
                        seen_years.add(yr)
                        year_cols.append((ci, yr))
            if year_cols:
                dp_list = []
                for r in range(header_row + 1, next_row):
                    first = df.iloc[r, 0]
                    d = to_date(first)
                    if d is None:
                        continue
                    for ci, year in year_cols:
                        if d.year != year:
                            continue
                        if ci >= ncols:
                            continue
                        val = to_float(df.iloc[r, ci])
                        if val is None:
                            continue
                        dp_list.append({
                            "period_date": d,
                            "period_label": make_label(d, "monthly"),
                            "value": val,
                        })
                if dp_list:
                    records.append({
                        "indicator_code": code,
                        "indicator_name": full_name,
                        "unit": extract_unit(full_name),
                        "period_type": "point_in_time",
                        "periodicity": "monthly",
                        "data_points": dp_list,
                    })
                continue

        long_header_row = None
        for r in range(row_i + 1, min(row_i + 5, next_row)):
            v = cell_str(df.iloc[r, 0]).lower()
            if v == "дата":
                long_header_row = r
                break

        if long_header_row is None:
            continue

        dp_list = []
        for r in range(long_header_row + 1, next_row):
            first = df.iloc[r, 0]
            d = to_date(first)
            if d is None:
                continue
            val = to_float(df.iloc[r, 1]) if ncols > 1 else None
            if val is None:
                continue
            dp_list.append({
                "period_date": d,
                "period_label": make_label(d, "monthly"),
                "value": val,
            })

        if dp_list:
            records.append({
                "indicator_code": code,
                "indicator_name": full_name,
                "unit": extract_unit(full_name),
                "period_type": "point_in_time",
                "periodicity": "monthly",
                "data_points": dp_list,
            })

    return records


# ─── ПАТТЕРН B-simple ────────────────────────────────────────────────────────

def parse_B_simple(df):
    records = []
    nrows, ncols = df.shape
    indicator_rows = find_indicator_rows(df)

    for idx, (row_i, code, full_name) in enumerate(indicator_rows):
        next_row = indicator_rows[idx + 1][0] if idx + 1 < len(indicator_rows) else nrows

        header_row = None
        for r in range(row_i + 1, min(row_i + 6, next_row)):
            row_vals = df.iloc[r].tolist()
            has_years = any(is_year(v) and not is_dynamic_col(v) for v in row_vals)
            first_s = cell_str(row_vals[0]).lower()
            if has_years and first_s in ("дата", "месяц", ""):
                header_row = r
                break
            if has_years and first_s == "":
                header_row = r
                break

        if header_row is None:
            for r in range(row_i + 1, min(row_i + 6, next_row)):
                row_vals = df.iloc[r].tolist()
                if any(is_year(v) and not is_dynamic_col(v) for v in row_vals):
                    header_row = r
                    break

        if header_row is None:
            continue

        headers = df.iloc[header_row].tolist()
        year_cols = [
            (ci, int(float(str(h)))) for ci, h in enumerate(headers)
            if is_year(h) and not is_dynamic_col(h)
        ]

        if not year_cols:
            continue

        dp_list = []
        for r in range(header_row + 1, next_row):
            first_s = cell_str(df.iloc[r, 0]).lower()

            if first_s in SKIP_ROW_LABELS or first_s == "":
                continue

            month_num = MONTH_MAP.get(first_s)
            if month_num is None:
                continue

            for ci, year in year_cols:
                if ci >= ncols:
                    continue
                val = to_float(df.iloc[r, ci])
                if val is None:
                    continue
                d = date(year, month_num, 1)
                dp_list.append({
                    "period_date": d,
                    "period_label": make_label(d, "monthly"),
                    "value": val,
                })

        if dp_list:
            records.append({
                "indicator_code": code,
                "indicator_name": full_name,
                "unit": extract_unit(full_name),
                "period_type": "period",
                "periodicity": "monthly",
                "data_points": dp_list,
            })

    return records


# ─── ПАТТЕРН B-cum ───────────────────────────────────────────────────────────

_MONTH_SUBHEADERS = (
    "в том числе месяц",
    "в т.ч. месяц",
    "по кредитам, выданным в течение месяца",
)

def _is_month_subheader(s):
    return any(kw in s for kw in _MONTH_SUBHEADERS)


def parse_B_cum(df):
    records = []
    nrows, ncols = df.shape
    indicator_rows = find_indicator_rows(df)

    for idx, (row_i, code, full_name) in enumerate(indicator_rows):
        next_row = indicator_rows[idx + 1][0] if idx + 1 < len(indicator_rows) else nrows

        year_header_row = None
        for r in range(row_i + 1, min(row_i + 8, next_row)):
            row_vals = df.iloc[r].tolist()
            clean_years = sum(
                1 for v in row_vals
                if is_year(v) and not is_dynamic_col(v)
            )
            if clean_years >= 2:
                year_header_row = r
                break

        if year_header_row is None:
            continue

        sub_header_row = None
        sub_headers = []
        for offset in (1, 2):
            r = year_header_row + offset
            if r >= next_row:
                break
            candidates = [cell_str(v).lower() for v in df.iloc[r].tolist()]
            if any(_is_month_subheader(s) for s in candidates):
                sub_header_row = r
                sub_headers = candidates
                break

        if sub_header_row is None:
            continue

        year_headers = df.iloc[year_header_row].tolist()
        month_cols = {}

        for ci, s in enumerate(sub_headers):
            if not _is_month_subheader(s):
                continue
            for ci2 in range(ci - 1, -1, -1):
                if is_year(year_headers[ci2]) and not is_dynamic_col(year_headers[ci2]):
                    year = int(float(str(year_headers[ci2])))
                    month_cols[year] = ci
                    break

        if not month_cols:
            continue

        dp_list = []
        data_start = sub_header_row + 1

        for r in range(data_start, next_row):
            row_vals_cur = df.iloc[r].tolist()
            first_s = cell_str(row_vals_cur[0]).lower()

            if "динамика" in first_s:
                break

            clean_year_count = sum(
                1 for v in row_vals_cur
                if is_year(v) and not is_dynamic_col(v)
            )
            if clean_year_count >= 2:
                break

            if first_s in SKIP_ROW_LABELS or first_s == "" or first_s == "итого":
                continue

            month_num = MONTH_MAP.get(first_s)
            if month_num is None:
                continue

            for year, ci in month_cols.items():
                if ci >= ncols:
                    continue
                val = to_float(df.iloc[r, ci])
                if val is None:
                    continue
                d = date(year, month_num, 1)
                dp_list.append({
                    "period_date": d,
                    "period_label": make_label(d, "monthly"),
                    "value": val,
                })

        if dp_list:
            records.append({
                "indicator_code": code,
                "indicator_name": full_name,
                "unit": extract_unit(full_name),
                "period_type": "period",
                "periodicity": "monthly",
                "data_points": dp_list,
            })

    return records


# ─── ПАТТЕРН C ───────────────────────────────────────────────────────────────

def parse_C(df):
    records = []
    nrows, ncols = df.shape
    indicator_rows = find_indicator_rows(df)

    for idx, (row_i, code, full_name) in enumerate(indicator_rows):
        next_row = indicator_rows[idx + 1][0] if idx + 1 < len(indicator_rows) else nrows

        header_row = None
        for r in range(row_i + 1, min(row_i + 8, next_row)):
            row_vals = df.iloc[r].tolist()
            year_count = sum(1 for v in row_vals if is_year(v))
            if year_count >= 2:
                header_row = r
                break

        if header_row is None:
            continue

        headers = df.iloc[header_row].tolist()
        year_cols = [
            (ci, int(float(str(h)))) for ci, h in enumerate(headers)
            if is_year(h)
        ]

        if not year_cols:
            continue

        dp_list = []
        for r in range(header_row + 1, next_row):
            first_s = cell_str(df.iloc[r, 0]).lower()

            if "динамика" in first_s:
                break
            if first_s in ("", "абсолютные значение", "абсолютные значения"):
                continue
            if any(kw in first_s for kw in ("источник", "дата последнего", "к содержанию")):
                break

            is_summary = first_s in (
                "итого", "значение", "за год",
                "среднее га год", "среднее за год",
                "среднегодовое значение",
            )

            if not is_summary:
                continue

            for ci, year in year_cols:
                if ci >= ncols:
                    continue
                val = to_float(df.iloc[r, ci])
                if val is None:
                    continue
                d = date(year, 1, 1)
                dp_list.append({
                    "period_date": d,
                    "period_label": str(year),
                    "value": val,
                })
            if dp_list:
                break

        if dp_list:
            records.append({
                "indicator_code": code,
                "indicator_name": full_name,
                "unit": extract_unit(full_name),
                "period_type": "period",
                "periodicity": "annual",
                "data_points": dp_list,
            })

    return records


# ─── Диспетчер паттернов ─────────────────────────────────────────────────────

PATTERN_PARSERS = {
    "A":        parse_A,
    "B-simple": parse_B_simple,
    "B-cum":    parse_B_cum,
    "C":        parse_C,
}


# ─── БД ──────────────────────────────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def seed_references(conn):
    with conn.cursor() as cur:
        for code, name, base_url, freq in SOURCES_SEED:
            cur.execute("""
                INSERT INTO sources (code, name, base_url, update_freq)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (code) DO NOTHING
            """, (code, name, base_url, freq))
        for code, name, sort in CATEGORIES_SEED:
            cur.execute("""
                INSERT INTO categories (code, name, sort_order)
                VALUES (%s, %s, %s)
                ON CONFLICT (code) DO NOTHING
            """, (code, name, sort))
    conn.commit()


def get_id(conn, table, code):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM {} WHERE code = %s".format(table), (code,))
        row = cur.fetchone()
        return row[0] if row else None


def upsert_indicator(conn, rec, category_id, source_id, sort_order):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO indicators
                (code, name, unit, period_type, periodicity, category_id, source_id,
                 geo_level, is_public, chart_type, sort_order, last_updated)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'russia',TRUE,'line',%s,NOW())
            ON CONFLICT (code) DO UPDATE SET
                name         = EXCLUDED.name,
                unit         = EXCLUDED.unit,
                period_type  = EXCLUDED.period_type,
                periodicity  = EXCLUDED.periodicity,
                last_updated = NOW()
            RETURNING id
        """, (
            rec["indicator_code"], rec["indicator_name"], rec["unit"],
            rec["period_type"], rec["periodicity"],
            category_id, source_id, sort_order,
        ))
        return cur.fetchone()[0]


def upsert_data_points(conn, indicator_id, dp_list):
    if not dp_list:
        return 0
    deduped = {}
    for dp in dp_list:
        if dp.get("value") is not None:
            deduped[dp["period_date"]] = dp
    rows = [
        (indicator_id, dp["period_date"], dp.get("period_label", ""),
         float(dp["value"]), False)
        for dp in deduped.values()
    ]
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO data_points
                (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO UPDATE SET
                value          = EXCLUDED.value,
                period_label   = EXCLUDED.period_label,
                is_preliminary = EXCLUDED.is_preliminary
        """, rows, template="(%s,%s,%s,%s,%s)")
    return len(rows)


# ─── Основная функция ────────────────────────────────────────────────────────

def find_excel_file():
    data_dir = Path(__file__).parent / "data"
    for pattern in ("*.xlsx", "*.xls"):
        files = list(data_dir.glob(pattern))
        if files:
            return files[0]
    raise FileNotFoundError(
        f"Excel-файл не найден в {data_dir}. "
        "Поместите файл в migration/data/ и перезапустите скрипт."
    )


def normalize_sheet_name(name):
    return name.strip()


def main():
    filepath = find_excel_file()
    log.info(f"Excel-файл: {filepath}\n")

    wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
    all_sheets = {name: wb[name].sheet_state for name in wb.sheetnames}
    wb.close()

    visible_sheets = [
        name for name, state in all_sheets.items()
        if state == "visible" and name.strip() != "Содержание"
    ]
    log.info(f"Видимых листов (без 'Содержание'): {len(visible_sheets)}\n")

    conn = get_connection()
    seed_references(conn)

    stats = {"total": len(all_sheets), "success": 0, "skipped": 0, "error": 0, "total_points": 0}

    for sheet_name, state in all_sheets.items():
        norm_name = normalize_sheet_name(sheet_name)

        if state != "visible" or norm_name == "Содержание":
            log.info(f"[SKIPPED] Лист «{sheet_name}»: {'скрытый лист' if state != 'visible' else 'содержание'}")
            stats["skipped"] += 1
            continue

        pattern = SHEET_PATTERN.get(norm_name)
        if pattern is None:
            log.info(f"[SKIPPED] Лист «{sheet_name}»: паттерн не определён")
            stats["skipped"] += 1
            continue

        try:
            df = pd.read_excel(str(filepath), sheet_name=sheet_name, header=None)
            parser_fn = PATTERN_PARSERS[pattern]
            parsed_records = parser_fn(df)

            category_id = get_id(conn, "categories", SHEET_CATEGORY.get(norm_name, ""))
            source_id   = get_id(conn, "sources",    SHEET_SOURCE.get(norm_name, ""))

            sheet_indicators = 0
            sheet_points = 0

            for sort_idx, rec in enumerate(parsed_records):
                ind_id = upsert_indicator(conn, rec, category_id, source_id, sort_idx)
                pts = upsert_data_points(conn, ind_id, rec["data_points"])
                sheet_indicators += 1
                sheet_points += pts

            conn.commit()
            stats["success"] += 1
            stats["total_points"] += sheet_points

            log.info(
                f"[SUCCESS] Лист «{sheet_name}»: "
                f"{sheet_indicators} показателей, {sheet_points} точек данных"
            )

        except Exception as exc:
            conn.rollback()
            stats["error"] += 1
            log.info(f"[ERROR]   Лист «{sheet_name}»: {exc}")
            import traceback
            traceback.print_exc()

    try:
        log.info("\nОбновление materialized view data_points_with_dynamics...")
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
        conn.commit()
        log.info("Materialized view обновлён.")
    except Exception as exc:
        log.info(f"[WARNING] Не удалось обновить materialized view: {exc}")

    conn.close()

    log.info("\n" + "=" * 60)
    log.info("ИТОГО:")
    log.info(f"  Всего листов:   {stats['total']}")
    log.info(f"  Успешно:        {stats['success']}")
    log.info(f"  Пропущено:      {stats['skipped']}")
    log.info(f"  Ошибок:         {stats['error']}")
    log.info(f"  Точек данных:   {stats['total_points']}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()