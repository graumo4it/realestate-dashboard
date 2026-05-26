"""
Парсер Банка России — ипотечная статистика.
Источник CBR: https://cbr.ru/statistics/bank_sector/mortgage/
Источник субсидий: https://xn--d1aqf.xn--p1ai/programmy-gosudarstvennoj-podderzhki/operational-reporting/

Файлы (прямые статичные URL CBR):
  02_02_Mortgage.xlsx       → 6.1–6.4, 6.19–6.20
  02_03_Scpa_mortgage.xlsx  → 6.7–6.10, 6.22–6.23
  02_41_Mortgage_ihc.xlsx   → 6.70–6.73, 6.76–6.79, 6.82–6.85

Производные (расчёт в парсере):
  6.5  = 6.2 / 6.1          — средний размер кредита (всего)
  6.6  = аннуитет(6.5, 6.3, 6.4) — средний ежемесячный платёж (всего), руб.
  6.11 = 6.8 / 6.7          — средний размер кредита (первичный)
  6.12 = аннуитет(6.11, 6.9, 6.10) — средний ежемесячный платёж (первичный), руб.
  6.13 = 6.1 − 6.7          — количество (вторичный)
  6.14 = 6.2 − 6.8          — объём (вторичный)
  6.15 = back-calc rate      — ставка (вторичный)
  6.16 = back-calc term      — срок (вторичный)
  6.17 = 6.14 / 6.13        — средний размер кредита (вторичный)
  6.18 = аннуитет(6.17, 6.15, 6.16) — средний ежемесячный платёж (вторичный), руб.
  6.21 = 6.20 / 6.19 × 100  — доля просрочки (всего)
  6.24 = 6.23 / 6.22 × 100  — доля просрочки (первичный)
  6.25 = 6.19 − 6.22        — долг (вторичный)
  6.26 = 6.20 − 6.23        — просрочка (вторичный)
  6.27 = 6.26 / 6.25 × 100  — доля просрочки (вторичный)
  6.74 = 6.71 / 6.70        — средний размер кредита ИЖС (всего)
  6.75 = аннуитет(6.74, 6.72, 6.73) — средний платёж ИЖС (всего), руб.
  6.80 = 6.77 / 6.76        — средний размер кредита ИЖС (создание)
  6.81 = аннуитет(6.80, 6.78, 6.79) — средний платёж ИЖС (создание), руб.
  6.86 = 6.83 / 6.82        — средний размер кредита ИЖС (приобретение)
  6.87 = аннуитет(6.86, 6.84, 6.85) — средний платёж ИЖС (приобретение), руб.

Субсидии (6.36–6.45):
  Источник: ДОМ.РФ API → /api/public/content/governmentsupport/reportpreferentialmortgage/
  Файл: «Статистические ряды (РФ)», лист 01_02_01
  Структура: строка 3 = заголовки; col 0 = программа, col 1 = единица,
             col 12+ = monthly dates (ISO datetime strings)

Конвенция дат CBR:
  Столбец «01.MM.YYYY» = данные за MM-1 того же года
  (01.02.2026 → январь 2026 → period_date = 2026-01-01)
"""

import io
import logging
import math
import re
import sys
from datetime import date
from pathlib import Path

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from base import BaseParser

log = logging.getLogger(__name__)

CBR_BASE_URL = "https://cbr.ru"
CBR_MORTGAGE_URL = "https://cbr.ru/statistics/bank_sector/mortgage/"
DOMRF_API_URL = "https://xn--d1aqf.xn--p1ai/api/public/content/governmentsupport/reportpreferentialmortgage/"
DOMRF_BASE_URL = "https://xn--d1aqf.xn--p1ai"

FILES = {
    "total":   "/vfs/statistics/BankSector/Mortgage/02_02_Mortgage.xlsx",
    "primary": "/vfs/statistics/BankSector/Mortgage/02_03_Scpa_mortgage.xlsx",
    "igs":     "/vfs/statistics/banksector/mortgage/02_41_Mortgage_ihc.xlsx",
}

# --------------------------------------------------------------------------- #
#  Маппинг строк → коды (подстрока из col 0 файлов 02_02 / 02_03)
# --------------------------------------------------------------------------- #

TOTAL_ROW_MAP: dict[str, str] = {
    "Количество предоставленных кредитов за месяц":          "6.1",
    "Объем предоставленных кредитов за месяц":               "6.2",
    "Средневзвешенная ставка по кредитам, выданным":         "6.3",
    "Средневзвешенный срок кредитования":                    "6.4",
    # «Задолженность по предоставленным кредитам, млн руб., в том числе»
    # Отличается от «Задолженность  по предоставленным кредитам с учётом приобр.»
    # → ищем по уникальному «млн руб., в том числе»
    "млн руб., в том числе":                                 "6.19",
    "просроченная задолженность по предоставленным":         "6.20",
}

PRIMARY_ROW_MAP: dict[str, str] = {
    "Количество предоставленных кредитов за месяц":          "6.7",
    "Объем предоставленных кредитов за месяц":               "6.8",
    "Средневзвешенная ставка по кредитам, выданным":         "6.9",
    "Средневзвешенный срок кредитования":                    "6.10",
    "млн руб., в том числе":                                 "6.22",
    "просроченная задолженность по предоставленным":         "6.23",
}

# IGS-файл (02_41): метки строк содержат \n — используем row_idx
# row 0: title,  row 1: dates
IGS_ROW_MAP: dict[int, str] = {
    2:  "6.70",   # Количество ИЖС всего
    3:  "6.76",   # Количество создание
    4:  "6.82",   # Количество приобретение
    5:  "6.71",   # Объём ИЖС всего
    6:  "6.77",   # Объём создание
    7:  "6.83",   # Объём приобретение (метка в файле ошибочно «единиц», но это объём)
    11: "6.73",   # Срок всего
    12: "6.79",   # Срок создание
    13: "6.85",   # Срок приобретение
    14: "6.72",   # Ставка всего
    15: "6.78",   # Ставка создание
    16: "6.84",   # Ставка приобретение
}

# Субсидии: ДОМ.РФ файл, лист 01_02_01
# Ключ: (подстрока col0, подстрока col1) → код индикатора
# Строки 4–15 (по row_idx), col0 = программа, col1 = единица
SUBSIDY_CODES: frozenset[str] = frozenset({
    "6.36", "6.37", "6.38", "6.39",
    "6.40", "6.41", "6.42", "6.43",
    "6.44", "6.45",
})

SUBSIDY_PURPOSE_CODES: frozenset[str] = frozenset(
    f"6.{program}.{purpose}.{metric}"
    for program, purposes in {
        52: range(1, 6),
        53: range(1, 6),
        54: range(1, 7),
        55: range(1, 6),
        56: range(1, 6),
        57: range(1, 6),
    }.items()
    for purpose in purposes
    for metric in (1, 2)
)

SUBSIDY_UPDATE_CODES: frozenset[str] = SUBSIDY_CODES | SUBSIDY_PURPOSE_CODES

# Группы индикаторов для раздельного запуска
# group='primary' — ежемесячная ипотека (файлы 02_02 + 02_03 + производные)
PRIMARY_CODES: frozenset[str] = frozenset({
    "6.1",  "6.2",  "6.3",  "6.4",  "6.5",  "6.6",
    "6.7",  "6.8",  "6.9",  "6.10", "6.11", "6.12",
    "6.13", "6.14", "6.15", "6.16", "6.17", "6.18",
    "6.19", "6.20", "6.21", "6.22", "6.23", "6.24",
    "6.25", "6.26", "6.27",
})

# group='ihc' — ИЖС (02_41) + субсидии ДОМ.РФ (6.36–6.45)
IHC_CODES: frozenset[str] = frozenset({
    "6.36", "6.37", "6.38", "6.39", "6.40", "6.41", "6.42", "6.43", "6.44", "6.45",
    *SUBSIDY_PURPOSE_CODES,
    "6.70", "6.71", "6.72", "6.73", "6.74", "6.75",
    "6.76", "6.77", "6.78", "6.79", "6.80", "6.81",
    "6.82", "6.83", "6.84", "6.85", "6.86", "6.87",
})

# Сколько последних периодов перезаписывать при каждом парсинге субсидий
# (данные в первоисточнике регулярно уточняются за ~3 года назад)
SUBSIDY_UPDATE_LOOKBACK = 36  # месяцев

DOMRF_SUBSIDY_ROW_MAP: dict[tuple[str, str], str] = {
    ("Льготная ипотека",               "шт."):      "6.38",
    ("Льготная ипотека",               "млн руб."): "6.39",
    ("Семейная ипотека",               "шт."):      "6.36",
    ("Семейная ипотека",               "млн руб."): "6.37",
    ("Дальневосточная",                "шт."):      "6.40",
    ("Дальневосточная",                "млн руб."): "6.41",
    ("IT ипотека",                     "шт."):      "6.42",
    ("IT ипотека",                     "млн руб."): "6.43",
    ("Ипотека в отдельных регионах",   "шт."):      "6.44",
    ("Ипотека в отдельных регионах",   "млн руб."): "6.45",
}

DOMRF_PURPOSE_PROG_CODES: dict[str, str] = {
    "Все программы": "6.52",
    "Льготная ипотека": "6.53",
    "Семейная ипотека": "6.54",
    "Дальневосточная и арктическая ипотека": "6.55",
    "IT ипотека": "6.56",
    "Ипотека в отдельных регионах": "6.57",
}

DOMRF_PURPOSE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Покупка квартир по ДКП на вторичке в городах без стройки", "5"),
    ("Покупка квартир по ДКП на вторичке, прочее", "6"),
    ("Покупка квартир по ДКП на вторичке", "5"),
    ("Покупка по ДДУ", "1"),
    ("Покупка по ДКП у застройщика", "2"),
    ("Индивидуальное жилищное строительство", "3"),
    ("Готовый индивидуальный жилой дом", "4"),
)

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель",
    "Май", "Июнь", "Июль", "Август",
    "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


# --------------------------------------------------------------------------- #
#  Вспомогательные функции
# --------------------------------------------------------------------------- #

def _cbr_date_to_period(date_str: str) -> date:
    """
    «01.MM.YYYY» (отчётная дата) → period_date первого числа предыдущего месяца.
    Пример: 01.02.2026 → date(2026, 1, 1).
    """
    parts = date_str.strip().split(".")
    mm, yyyy = int(parts[1]), int(parts[2])
    month = mm - 1
    year = yyyy
    if month == 0:
        month = 12
        year -= 1
    return date(year, month, 1)


def _period_label(d: date) -> str:
    return f"{MONTHS_RU[d.month - 1]} {d.year}"


def _parse_dates(df: pd.DataFrame) -> dict[int, date]:
    """Строка 1 → {col_idx: period_date}."""
    result: dict[int, date] = {}
    for col_idx in range(1, len(df.columns)):
        val = str(df.iloc[1, col_idx]).strip()
        if re.match(r"^\d{2}\.\d{2}\.\d{4}$", val):
            try:
                result[col_idx] = _cbr_date_to_period(val)
            except (ValueError, IndexError):
                pass
    return result


def _safe_float(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s in ("", "-", "х", "x", "–"):
        return None
    try:
        return float(s.replace(" ", "").replace(",", ".").replace("\xa0", ""))
    except (ValueError, TypeError):
        return None


def _parse_mortgage_file(
    data: bytes,
    row_map: dict[str, str],
) -> dict[str, dict[date, float]]:
    """
    Парсит файл 02_02 или 02_03 (лист «в рублях»).
    Возвращает {indicator_code: {period_date: value}}.
    """
    df = pd.read_excel(io.BytesIO(data), sheet_name="в рублях", header=None)
    dates_by_col = _parse_dates(df)

    if not dates_by_col:
        log.warning("_parse_mortgage_file: не найдены колонки с датами")
        return {}

    result: dict[str, dict[date, float]] = {}
    for row_idx in range(2, len(df)):
        label_raw = str(df.iloc[row_idx, 0])
        label = label_raw.strip().lower()
        if not label or label == "nan":
            continue

        for substring, code in row_map.items():
            if substring.lower() in label:
                series: dict[date, float] = {}
                for col_idx, period_date in dates_by_col.items():
                    v = _safe_float(df.iloc[row_idx, col_idx])
                    if v is not None:
                        series[period_date] = v
                result[code] = series
                break  # каждая строка — один код

    return result


def _parse_igs_file(data: bytes) -> dict[str, dict[date, float]]:
    """Парсит 02_41_Mortgage_ihc.xlsx (лист «в рублях»), маппинг по row_idx."""
    df = pd.read_excel(io.BytesIO(data), sheet_name="в рублях", header=None)
    dates_by_col = _parse_dates(df)

    if not dates_by_col:
        log.warning("_parse_igs_file: не найдены колонки с датами")
        return {}

    result: dict[str, dict[date, float]] = {}
    for row_idx, code in IGS_ROW_MAP.items():
        if row_idx >= len(df):
            continue
        series: dict[date, float] = {}
        for col_idx, period_date in dates_by_col.items():
            v = _safe_float(df.iloc[row_idx, col_idx])
            if v is not None:
                series[period_date] = v
        if series:
            result[code] = series

    return result


def _series_to_records(
    series_by_code: dict[str, dict[date, float]],
) -> list[dict]:
    records = []
    for code, series in series_by_code.items():
        for period_date, value in series.items():
            records.append({
                "indicator_code": code,
                "period_date":    period_date,
                "period_label":   _period_label(period_date),
                "value":          value,
            })
    return records


# --------------------------------------------------------------------------- #
#  Аннуитетный платёж
# --------------------------------------------------------------------------- #

def _annuity(loan_mln_rub: float, annual_rate_pct: float, term_months: float) -> float | None:
    """
    Аннуитетный ежемесячный платёж (в рублях).
      loan_mln_rub    — размер кредита в млн руб.
      annual_rate_pct — годовая ставка, %
      term_months     — срок кредита, месяцев

    Формула: M = P × r / (1 − (1+r)^{−n})
    """
    if not loan_mln_rub or not annual_rate_pct or not term_months:
        return None
    P = loan_mln_rub * 1_000_000          # руб.
    r = annual_rate_pct / 12.0 / 100.0    # месячная ставка в долях
    n = int(round(term_months))
    if r <= 0 or n <= 0:
        return None
    try:
        M = P * r / (1.0 - math.pow(1.0 + r, -n))
        return round(M, 2)
    except (ZeroDivisionError, OverflowError, ValueError):
        return None


# --------------------------------------------------------------------------- #
#  Расчёт производных показателей
# --------------------------------------------------------------------------- #

def _calc_derived(
    total: dict[str, dict[date, float]],
    primary: dict[str, dict[date, float]],
    igs: dict[str, dict[date, float]],
) -> list[dict]:
    """Вычисляет все производные коды на основе базовых рядов."""
    records: list[dict] = []

    def _add(code: str, period_date: date, value: float | None) -> None:
        if value is None:
            return
        records.append({
            "indicator_code": code,
            "period_date":    period_date,
            "period_label":   _period_label(period_date),
            "value":          value,
        })

    # Общие периоды total × primary
    t_periods = set(total.get("6.1", {}).keys()) | set(total.get("6.2", {}).keys())

    for period_date in sorted(t_periods):
        cnt_tot = total.get("6.1", {}).get(period_date)
        vol_tot = total.get("6.2", {}).get(period_date)
        rate_tot = total.get("6.3", {}).get(period_date)
        term_tot = total.get("6.4", {}).get(period_date)
        debt_tot = total.get("6.19", {}).get(period_date)
        overdue_tot = total.get("6.20", {}).get(period_date)

        cnt_prim = primary.get("6.7", {}).get(period_date)
        vol_prim = primary.get("6.8", {}).get(period_date)
        rate_prim = primary.get("6.9", {}).get(period_date)
        term_prim = primary.get("6.10", {}).get(period_date)
        debt_prim = primary.get("6.22", {}).get(period_date)
        overdue_prim = primary.get("6.23", {}).get(period_date)

        # 6.5 — средний размер кредита (всего)
        loan_tot = None
        if cnt_tot and vol_tot:
            loan_tot = vol_tot / cnt_tot
            _add("6.5", period_date, loan_tot)

        # 6.6 — средний ежемесячный платёж (всего)
        _add("6.6", period_date, _annuity(loan_tot, rate_tot, term_tot))

        # 6.11 — средний размер кредита (первичный)
        loan_prim = None
        if cnt_prim and vol_prim:
            loan_prim = vol_prim / cnt_prim
            _add("6.11", period_date, loan_prim)

        # 6.12 — средний ежемесячный платёж (первичный)
        _add("6.12", period_date, _annuity(loan_prim, rate_prim, term_prim))

        # 6.13–6.18 — вторичный рынок (поток)
        rate_sec = None
        term_sec = None
        loan_sec = None

        if cnt_tot is not None and cnt_prim is not None:
            cnt_sec = cnt_tot - cnt_prim
            _add("6.13", period_date, cnt_sec)

            if vol_tot is not None and vol_prim is not None:
                vol_sec = vol_tot - vol_prim
                _add("6.14", period_date, vol_sec)

                # 6.17 — средний размер (вторичный)
                if cnt_sec and cnt_sec > 0:
                    loan_sec = vol_sec / cnt_sec
                    _add("6.17", period_date, loan_sec)

                # 6.15 — ставка вторичного рынка (back-calculation по объёму)
                if rate_tot is not None and rate_prim is not None and vol_sec and vol_sec > 0:
                    rate_sec = (rate_tot * vol_tot - rate_prim * vol_prim) / vol_sec
                    _add("6.15", period_date, round(rate_sec, 4))

                # 6.16 — срок вторичного рынка (back-calculation по кол-ву)
                if term_tot is not None and term_prim is not None and cnt_sec and cnt_sec > 0:
                    term_sec = (term_tot * cnt_tot - term_prim * cnt_prim) / cnt_sec
                    _add("6.16", period_date, round(term_sec, 2))

        # 6.18 — средний ежемесячный платёж (вторичный)
        _add("6.18", period_date, _annuity(loan_sec, rate_sec, term_sec))

        # 6.21 — доля просрочки (всего)
        if debt_tot and overdue_tot is not None:
            _add("6.21", period_date, round(overdue_tot / debt_tot * 100, 4))

        # 6.24 — доля просрочки (первичный)
        if debt_prim and overdue_prim is not None:
            _add("6.24", period_date, round(overdue_prim / debt_prim * 100, 4))

        # 6.25–6.27 — долговые вторичного рынка
        if debt_tot is not None and debt_prim is not None:
            debt_sec = debt_tot - debt_prim
            _add("6.25", period_date, debt_sec)

            if overdue_tot is not None and overdue_prim is not None:
                overdue_sec = overdue_tot - overdue_prim
                _add("6.26", period_date, overdue_sec)

                if debt_sec and debt_sec > 0:
                    _add("6.27", period_date, round(overdue_sec / debt_sec * 100, 4))

    # 6.74/6.75, 6.80/6.81, 6.86/6.87 — средний размер + аннуитетный платёж ИЖС
    igs_groups = [
        ("6.70", "6.71", "6.72", "6.73", "6.74", "6.75"),  # всего
        ("6.76", "6.77", "6.78", "6.79", "6.80", "6.81"),  # создание
        ("6.82", "6.83", "6.84", "6.85", "6.86", "6.87"),  # приобретение
    ]
    for cnt_code, vol_code, rate_code, term_code, size_code, payment_code in igs_groups:
        all_dates = sorted(
            set(igs.get(cnt_code, {}).keys()) |
            set(igs.get(vol_code, {}).keys())
        )
        for period_date in all_dates:
            cnt = igs.get(cnt_code, {}).get(period_date)
            vol = igs.get(vol_code, {}).get(period_date)
            rate = igs.get(rate_code, {}).get(period_date)
            term = igs.get(term_code, {}).get(period_date)

            loan = None
            if cnt and vol and cnt > 0:
                loan = vol / cnt
                _add(size_code, period_date, loan)

            _add(payment_code, period_date, _annuity(loan, rate, term))

    return records


# --------------------------------------------------------------------------- #
#  Субсидии
# --------------------------------------------------------------------------- #

def _fetch_domrf_subsidy(session: requests.Session) -> bytes | None:
    """
    Скачивает файл «Статистические ряды (РФ)» с ДОМ.РФ через JSON API.
    Endpoint: GET /api/public/content/governmentsupport/reportpreferentialmortgage/
    Структура ответа: {"success": true, "data": [{"statistic": {"src": "..."}, ...}]}
    Ключ "statistic" — это RF-уровень (224 КБ), "statistic_region" — регионы (13 МБ).
    """
    try:
        resp = session.get(
            DOMRF_API_URL, timeout=30,
            headers={"Accept": "application/json, */*"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.warning(f"Не удалось получить список документов ДОМ.РФ: {e}")
        return None

    # Извлекаем список записей
    items: list = []
    if isinstance(data, dict):
        for key in ("data", "results", "items"):
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
    elif isinstance(data, list):
        items = data

    if not items:
        log.warning("API ДОМ.РФ вернул пустой список документов — субсидии пропущены.")
        return None

    # Берём последний (самый свежий) отчёт, поле "statistic" = RF-уровень
    item = items[0]
    statistic = item.get("statistic") if isinstance(item, dict) else None
    if not isinstance(statistic, dict):
        log.warning(f"Поле 'statistic' не найдено в ответе ДОМ.РФ: {list(item.keys())}")
        return None

    src = statistic.get("src", "")
    if not src:
        log.warning("Поле 'statistic.src' пустое в ответе ДОМ.РФ")
        return None

    file_url = src if src.startswith("http") else f"{DOMRF_BASE_URL}{src}"
    log.info(f"Скачиваю субсидийный файл ДОМ.РФ: {file_url}")
    try:
        r = session.get(file_url, timeout=60)
        r.raise_for_status()
        log.info(f"Субсидийный файл скачан: {len(r.content):,} байт")
        return r.content
    except requests.RequestException as e:
        log.warning(f"Не удалось скачать субсидийный файл: {e}")
        return None


def _parse_subsidy_file(data: bytes) -> list[dict]:
    """
    Парсит файл «Статистические_ряды.xlsx»:
      • 01_02_01 — базовые ряды по программам господдержки (6.36–6.45)
      • 01_02_03 — цели кредитования в новой детальной сетке (6.52.x.x–6.57.x.x)
    Логика взята из migration/migrate_subsidy_update.py.
    """
    import datetime as dt_module

    records: list[dict] = []

    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name="01_02_01", header=None)
    except Exception as e:
        log.warning(f"Не удалось открыть лист 01_02_01: {e}")
        df = None

    if df is not None:
        # Даты: строка 3, столбцы 12+
        date_cols: dict[int, date] = {}
        for col in range(12, min(200, df.shape[1])):
            val = df.iloc[3, col]
            if pd.notna(val) and isinstance(val, (dt_module.datetime, dt_module.date)):
                d = val if isinstance(val, dt_module.datetime) else dt_module.datetime.combine(val, dt_module.time())
                date_cols[col] = date(d.year, d.month, 1)

        if not date_cols:
            log.warning("_parse_subsidy_file: колонки дат 01_02_01 не найдены")
        else:
            # Сканируем строки 4–20 (данные начинаются с индекса 4 по структуре ДОМ.РФ)
            for row_idx in range(4, min(25, len(df))):
                prog_cell = str(df.iloc[row_idx, 0]).strip()
                unit_cell = str(df.iloc[row_idx, 1]).strip()
                if not prog_cell or prog_cell == "nan":
                    continue

                code = None
                for (prog_sub, unit_sub), c in DOMRF_SUBSIDY_ROW_MAP.items():
                    if prog_sub.lower() in prog_cell.lower() and unit_sub.lower() in unit_cell.lower():
                        code = c
                        break
                if not code:
                    log.debug(f"Субсидии: строка {row_idx} ('{prog_cell}' / '{unit_cell}') — не сопоставлена")
                    continue

                for col, period_date in date_cols.items():
                    raw = df.iloc[row_idx, col]
                    val = _safe_float(raw)
                    # Льготная программа завершена с 2025 → нули → NULL
                    if code in ("6.38", "6.39") and val == 0.0:
                        val = None
                    if val is not None:
                        records.append({
                            "indicator_code": code,
                            "period_date":    period_date,
                            "period_label":   _period_label(period_date),
                            "value":          val,
                        })

    records.extend(_parse_subsidy_purpose_file(data, dt_module))

    return records


def _parse_subsidy_purpose_file(data: bytes, dt_module) -> list[dict]:
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name="01_02_03", header=None)
    except Exception as e:
        log.warning(f"Не удалось открыть лист 01_02_03: {e}")
        return []

    date_cols: dict[int, date] = {}
    for col in range(0, df.shape[1]):
        val = df.iloc[3, col]
        if pd.notna(val) and isinstance(val, (dt_module.datetime, dt_module.date)):
            d = val if isinstance(val, dt_module.datetime) else dt_module.datetime.combine(val, dt_module.time())
            date_cols[col] = date(d.year, d.month, 1)

    if not date_cols:
        log.warning("_parse_subsidy_purpose_file: колонки дат 01_02_03 не найдены")
        return []

    def metric_suffix(label: str) -> str | None:
        if "шт." in label:
            return "1"
        if "млн руб" in label:
            return "2"
        return None

    def purpose_suffix(label: str) -> str | None:
        for pattern, suffix in DOMRF_PURPOSE_PATTERNS:
            if pattern in label:
                return suffix
        return None

    def no_data_ok(raw) -> bool:
        val = _safe_float(raw)
        return val is None or val == 0.0

    current_base = None
    no_data_checks: dict[date, list[bool]] = {period_date: [] for period_date in date_cols.values()}
    pending_rows: list[tuple[str, int]] = []

    for row_idx in range(0, len(df)):
        label_raw = df.iloc[row_idx, 0]
        if pd.isna(label_raw):
            continue

        raw_label = str(label_raw)
        label = raw_label.strip()

        if not raw_label.startswith("   "):
            if label in DOMRF_PURPOSE_PROG_CODES:
                current_base = DOMRF_PURPOSE_PROG_CODES[label]
            continue

        if current_base is None:
            continue

        metric = metric_suffix(label)
        if metric is None:
            continue

        if "Нет данных" in label:
            for col, period_date in date_cols.items():
                no_data_checks[period_date].append(no_data_ok(df.iloc[row_idx, col]))
            continue

        purpose = purpose_suffix(label)
        if purpose is None:
            continue

        pending_rows.append((f"{current_base}.{purpose}.{metric}", row_idx))

    expected_checks = len(DOMRF_PURPOSE_PROG_CODES) * 2
    valid_dates = {
        period_date for period_date, checks in no_data_checks.items()
        if len(checks) == expected_checks and all(checks)
    }
    if valid_dates:
        log.info(
            "  01_02_03: валидные периоды до %s (по строкам 'Нет данных')",
            max(valid_dates),
        )
    else:
        log.warning("  01_02_03: валидные периоды не найдены")

    records: list[dict] = []
    for code, row_idx in pending_rows:
        for col, period_date in date_cols.items():
            if period_date not in valid_dates:
                continue
            records.append({
                "indicator_code": code,
                "period_date":    period_date,
                "period_label":   _period_label(period_date),
                "value":          _safe_float(df.iloc[row_idx, col]),
            })

    return records


# --------------------------------------------------------------------------- #
#  Хелперы для субсидийного парсинга
# --------------------------------------------------------------------------- #

def _filter_completed_months(records: list[dict]) -> list[dict]:
    """
    Возвращает только записи за завершённые месяцы.

    «Завершённый» = месяц, который уже закончился.
    Например, если сегодня 23 мая 2026, то апрель и ранее — завершённые,
    май — ещё не завершён и исключается.

    Логика: period_date для месяца M = первое число M (2026-05-01).
    Первое число текущего месяца = граница: всё строго меньше — завершено.
    """
    from datetime import date as _date
    today = _date.today()
    current_month_start = _date(today.year, today.month, 1)
    return [r for r in records if r["period_date"] < current_month_start]


def _subsidy_lookback_cutoff(records: list[dict]) -> date:
    """
    Возвращает дату начала скользящего окна обновления.

    Окно = SUBSIDY_UPDATE_LOOKBACK месяцев, считая от самого позднего
    period_date в переданных записях.

    Пример: max = 2026-05-01, lookback = 36 →
        total_months = 2026*12 + 5 - 35 = 24317 - 35 = 24282
        year = (24282-1)//12 = 2023, month = 24282 - 2023*12 = 6
        → 2023-06-01 (охватываем июнь 2023 — май 2026 включительно, 36 периодов)
    """
    if not records:
        return date.min
    max_date = max(r["period_date"] for r in records)
    total_months = max_date.year * 12 + max_date.month - (SUBSIDY_UPDATE_LOOKBACK - 1)
    year = (total_months - 1) // 12
    month = total_months - year * 12
    return date(year, month, 1)


# --------------------------------------------------------------------------- #
#  Основной класс
# --------------------------------------------------------------------------- #

class CBRParser(BaseParser):
    source_code = "cbr"

    def __init__(self, group: str | None = None):
        """
        group='primary' — только 6.1–6.27 (ежемесячная ипотека, файлы 02_02/02_03).
        group='ihc'     — только 6.36–6.87 (ИЖС 02_41 + субсидии ДОМ.РФ).
        group=None      — всё (обратная совместимость, запускает сразу оба набора).
        """
        super().__init__()
        if group not in (None, "primary", "ihc"):
            raise ValueError(f"group must be 'primary', 'ihc', or None, got {group!r}")
        self.group = group

    def run(self) -> dict:
        """
        Переопределяем run() для разделения логики:
          • Субсидии (6.36–6.45, 6.52.x.x–6.57.x.x): только завершённые месяцы,
            DO UPDATE за 36 периодов.
          • Остальные CBR-показатели: стандартный DO NOTHING, только новые периоды.
        """
        self._connect()
        self._get_source_id()
        self._start_job()

        try:
            raw = self._fetch_with_retry()
            records = self.parse(raw)

            # ── 1. Субсидии: перезаписываем последние 36 завершённых периодов ─
            sub_all = [r for r in records if r["indicator_code"] in SUBSIDY_UPDATE_CODES]
            sub_completed = _filter_completed_months(sub_all)

            if sub_completed:
                cutoff = _subsidy_lookback_cutoff(sub_completed)
                sub_window = [r for r in sub_completed if r["period_date"] >= cutoff]
                sub_rows = self.upsert_update_to_db(sub_window)
                log.info(
                    f"[cbr] Субсидии: {sub_rows} записей обновлено"
                    f" (окно {cutoff} – {max(r['period_date'] for r in sub_window)})"
                )
            else:
                sub_rows = 0
                log.info("[cbr] Субсидии: нет завершённых периодов для обновления")

            # ── 2. Остальные: только новые периоды, DO NOTHING ─────────────────
            other = [r for r in records if r["indicator_code"] not in SUBSIDY_UPDATE_CODES]
            codes = list({r["indicator_code"] for r in other})
            last_dates = self.get_last_dates(codes)
            new_other = [
                r for r in other
                if r["period_date"] > last_dates.get(r["indicator_code"], date.min)
            ]
            log.info(f"[cbr] Прочие показатели: {len(other)} записей → {len(new_other)} новых")
            other_rows = self.upsert_to_db(new_other)

            total_rows = sub_rows + other_rows
            self._finish_job("success", total_rows)
            self._refresh_view()
            log.info(f"[cbr] Done. Rows upserted/updated: {total_rows}")
            return {"status": "success", "rows": total_rows, "error": None}

        except Exception as e:
            log.error(f"[cbr] Error: {e}", exc_info=True)
            self._finish_job("error", 0, str(e))
            return {"status": "error", "rows": 0, "error": str(e)}
        finally:
            if self.conn:
                self.conn.close()

    def fetch_raw(self) -> dict:
        """
        Скачивает файлы в зависимости от self.group.
          group='primary' → только 02_02 + 02_03
          group='ihc'     → только 02_41 + субсидийный файл
          group=None      → все три файла + субсидии
        Возвращает {"total": bytes|None, "primary": bytes|None, "igs": bytes|None, "subsidy": bytes|None}.
        """
        session = requests.Session()
        session.headers["User-Agent"] = (
            "Mozilla/5.0 (compatible; realestate-dashboard-bot/1.0)"
        )
        raw: dict[str, bytes | None] = {"total": None, "primary": None, "igs": None, "subsidy": None}

        # Определяем, какие файлы скачивать
        if self.group == "primary":
            files_to_fetch = {"total": FILES["total"], "primary": FILES["primary"]}
        elif self.group == "ihc":
            files_to_fetch = {"igs": FILES["igs"]}
        else:
            files_to_fetch = FILES  # all

        for key, path in files_to_fetch.items():
            url = f"{CBR_BASE_URL}{path}"
            log.info(f"Скачиваю {url}")
            try:
                r = session.get(url, timeout=60)
                r.raise_for_status()
                raw[key] = r.content
                log.info(f"  OK: {len(r.content):,} байт")
            except requests.RequestException as e:
                raise RuntimeError(f"Не удалось скачать {url}: {e}") from e

        # Субсидии — только для group='ihc' или group=None
        if self.group in ("ihc", None):
            log.info("Запрашиваю субсидийный файл через API ДОМ.РФ…")
            raw["subsidy"] = _fetch_domrf_subsidy(session)

        return raw

    def parse(self, raw: dict) -> list[dict]:
        """
        Парсит скачанные файлы в список записей для upsert.
        Обрабатывает только те файлы, которые присутствуют в raw (не None).
        Возвращает [{"indicator_code", "period_date", "period_label", "value"}, ...].
        """
        records: list[dict] = []

        # ── 1. Файл 02_02 (всего) ─────────────────────────────────────────────
        if raw.get("total"):
            log.info("Парсю 02_02_Mortgage.xlsx (всего)…")
            total = _parse_mortgage_file(raw["total"], TOTAL_ROW_MAP)
            log.info(f"  Найдено кодов: {sorted(total.keys())}, периодов: {len(next(iter(total.values()), {}))}")
        else:
            total = {}

        # ── 2. Файл 02_03 (первичный рынок) ──────────────────────────────────
        if raw.get("primary"):
            log.info("Парсю 02_03_Scpa_mortgage.xlsx (первичный рынок)…")
            primary = _parse_mortgage_file(raw["primary"], PRIMARY_ROW_MAP)
            log.info(f"  Найдено кодов: {sorted(primary.keys())}, периодов: {len(next(iter(primary.values()), {}))}")
        else:
            primary = {}

        # ── 3. Файл 02_41 (ИЖС) ──────────────────────────────────────────────
        if raw.get("igs"):
            log.info("Парсю 02_41_Mortgage_ihc.xlsx (ИЖС)…")
            igs = _parse_igs_file(raw["igs"])
            log.info(f"  Найдено кодов: {sorted(igs.keys())}")
        else:
            igs = {}

        # ── 4. Записи из базовых файлов ──────────────────────────────────────
        records.extend(_series_to_records(total))
        records.extend(_series_to_records(primary))
        records.extend(_series_to_records(igs))

        # ── 5. Производные (только если есть базовые данные) ─────────────────
        if total or primary or igs:
            log.info("Рассчитываю производные показатели…")
            derived = _calc_derived(total, primary, igs)
            log.info(f"  Производных записей: {len(derived)}")
            records.extend(derived)

        # ── 6. Субсидии ──────────────────────────────────────────────────────
        if raw.get("subsidy"):
            log.info("Парсю субсидийный файл…")
            sub = _parse_subsidy_file(raw["subsidy"])
            log.info(f"  Субсидийных записей: {len(sub)}")
            records.extend(sub)
        elif self.group in ("ihc", None):
            log.info("Субсидийный файл недоступен — раздел 6.36–6.45 пропущен.")

        # ── 7. Фильтрация по группе (если задана) ────────────────────────────
        if self.group == "primary":
            records = [r for r in records if r["indicator_code"] in PRIMARY_CODES]
        elif self.group == "ihc":
            records = [r for r in records if r["indicator_code"] in IHC_CODES]

        # ── 8. Дедупликация в пределах одного запуска ────────────────────────
        seen: set[tuple[str, date]] = set()
        unique: list[dict] = []
        for r in records:
            key = (r["indicator_code"], r["period_date"])
            if key not in seen:
                seen.add(key)
                unique.append(r)

        codes = sorted({r["indicator_code"] for r in unique})
        log.info(f"CBR parse (group={self.group!r}): итого {len(unique)} записей, коды: {codes}")
        return unique


# --------------------------------------------------------------------------- #
#  CLI запуск
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    import sys as _sys
    # Поддержка: python cbr.py [--group primary|ihc] [--dry-run]
    group_arg = None
    if "--group" in _sys.argv:
        idx = _sys.argv.index("--group")
        if idx + 1 < len(_sys.argv):
            group_arg = _sys.argv[idx + 1]

    if "--dry-run" in _sys.argv or "-n" in _sys.argv:
        # Только fetch + parse, без записи в БД
        log.info(f"=== DRY RUN (fetch + parse only, group={group_arg!r}) ===")
        p = CBRParser(group=group_arg)
        raw = p.fetch_raw()
        recs = p.parse(raw)
        from collections import Counter
        by_code = Counter(r["indicator_code"] for r in recs)
        print(f"\nИтого: {len(recs)} записей")
        print(f"Коды ({len(by_code)}): {sorted(by_code.keys())}")
        if recs:
            dates = [r["period_date"] for r in recs]
            print(f"Диапазон дат: {min(dates)} — {max(dates)}")
            print(f"\nПо кодам:")
            for code in sorted(by_code.keys()):
                print(f"  {code}: {by_code[code]} точек")
    else:
        result = CBRParser(group=group_arg).run()
        print(result)
