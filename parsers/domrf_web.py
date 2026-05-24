"""
Парсер ДОМ.РФ (публичные агрегированные данные ЕИСЖС).

Источник: наш.дом.рф — «Статистические ряды» жилищного строительства.
Файл: 01_01_stockvariablesexsales.xlsx
URL:  https://наш.дом.рф/site/binaries/content/assets/domrf/xlsdashboard/01_01_stockvariablesexsales.xlsx

Индикаторы (category under_construction_domrf):
  3.1   — Количество возводимых МЖД, ед.
  3.2   — Общая площадь возводимых МЖД, млн кв. м
  3.3   — Жилая площадь возводимых МЖД, млн кв. м
  3.4   — Количество квартир в возводимых МЖД, млн ед.
  3.17  — Количество групп компаний застройщиков, ед.
  3.18  — Индекс Херфиндаля-Хиршмана (средневзвешенное), пунктов
  3.19  — Индекс Херфиндаля-Хиршмана (медианное), пунктов

Структура файла (лист 01_01_00, header=None, 0-индексация):
  Строка 3  — заголовок с датами (даты начиная с колонки 2)
  Строка 4  — Количество МКД (3.1)
  Строка 5  — Общая площадь в кв. м (3.2, делить на 1 000 000 → млн кв. м)
  Строка 6  — Жилая площадь в кв. м (3.3, делить на 1 000 000)
  Строка 7  — Количество квартир в шт. (3.4, делить на 1 000 000 → млн ед.)
  Строка 17 — заголовок концентрационного блока (дубликат дат)
  Строка 18 — Количество групп компаний (3.17)
  Строка 19 — ИХХ средневзвешенное (3.18)
  Строка 20 — ИХХ медианное (3.19)

Данные только по Российской Федерации (агрегат).
Региональная разбивка — в листах 01_01_01 … 01_01_NN.

⚠️  Файл доступен только с российских IP-адресов (ЕИСЖС геоблокирует зарубежные запросы).
    При запуске с зарубежного IP — скачайте файл вручную и укажите LOCAL_FILE_PATH,
    либо используйте флаг --file в CLI-режиме.
"""

import io
import logging
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

# curl_cffi имитирует TLS fingerprint реального браузера Chrome —
# именно это позволяет обойти WAF наш.дом.рф.
# Fallback на стандартный requests, если curl_cffi не установлен.
try:
    from curl_cffi import requests
    _IMPERSONATE = "chrome124"
except ImportError:
    import requests  # type: ignore[no-redef]
    _IMPERSONATE = None

sys.path.insert(0, str(Path(__file__).parent))
from base import BaseParser

log = logging.getLogger(__name__)

# ─── Константы ───────────────────────────────────────────────────────────────

# URL файла на ЕИСЖС (наш.дом.рф = xn--80az8a.xn--d1aqf.xn--p1ai, IP 91.206.127.42).
# ⚠️  WAF блокирует автоматические запросы (403).
#     Файл открывается в браузере, но не через requests/curl.
#     Решение: скачать вручную в браузере и задать LOCAL_FILE_PATH.
FILE_URL = (
    "https://xn--80az8a.xn--d1aqf.xn--p1ai"
    "/site/binaries/content/assets/domrf/xlsdashboard/01_01_stockvariablesexsales.xlsx"
)

# Запасной путь к локальной копии файла (для запуска без доступа к ЕИСЖС)
LOCAL_FILE_PATH: str | None = None

# Лист с агрегированными данными по России
SHEET_NAME: str = "01_01_00"

# Строка с датами (0-индексация, header=None)
DATE_HEADER_ROW: int = 3

# Столбец, с которого начинаются данные
DATE_COL_START: int = 2

# Маппинг: строка (0-based) → (код индикатора, делитель)
# Делитель нужен для перевода единиц:
#   площадь: кв. м → млн кв. м (÷ 1 000 000)
#   квартиры: шт. → млн ед. (÷ 1 000 000)
ROW_MAP: dict[int, tuple[str, float]] = {
    4:  ("3.1",  1.0),           # Количество МКД, шт.
    5:  ("3.2",  1_000_000.0),   # Общая площадь, кв. м → млн кв. м
    6:  ("3.3",  1_000_000.0),   # Жилая площадь, кв. м → млн кв. м
    7:  ("3.4",  1_000_000.0),   # Количество квартир, шт. → млн ед.
    18: ("3.17", 1.0),           # Группы компаний застройщиков, шт.
    19: ("3.18", 1.0),           # ИХХ средневзвешенное, пунктов
    20: ("3.19", 1.0),           # ИХХ медианное, пунктов
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://xn--c1akfdfe.xn--d1aqf.xn--p1ai/",
}

# Русские названия месяцев для формирования period_label
_MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель",
    "Май", "Июнь", "Июль", "Август",
    "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def _parse_col_date(val) -> date | None:
    """Парсит дату из ячейки заголовка (datetime / Timestamp / строка)."""
    if isinstance(val, pd.Timestamp):
        return date(val.year, val.month, 1)
    if hasattr(val, "year"):
        return date(val.year, val.month, 1)
    s = str(val).strip().lower()
    if not s or s in ("nan", "none", ""):
        return None
    # «2024-01» или «01.2024»
    m = re.match(r"(\d{4})[.\-](\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    m2 = re.match(r"(\d{2})[.\-](\d{4})", s)
    if m2:
        try:
            return date(int(m2.group(2)), int(m2.group(1)), 1)
        except ValueError:
            pass
    return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s in ("", "-", "–", "х", "x", "н/д", "..."):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _period_label(d: date) -> str:
    return f"{_MONTHS_RU[d.month - 1]} {d.year}"


# ─── Парсер ──────────────────────────────────────────────────────────────────

class DomRFWebParser(BaseParser):
    """
    Парсер ЕИСЖС «Статистические ряды жилищного строительства».

    Покрывает индикаторы: 3.1, 3.2, 3.3, 3.4, 3.17, 3.18, 3.19.

    fetch_raw() — скачивает файл с наш.дом.рф (доступен только с российских IP).
    parse()     — извлекает данные из листа 01_01_00 (только строки по РФ в целом).
    """

    source_code = "domrf"

    def fetch_raw(self) -> bytes:
        """
        Скачивает Excel-файл с ЕИСЖС.

        Если LOCAL_FILE_PATH задан — читает локальный файл.
        Иначе — скачивает с FILE_URL.
        """
        if LOCAL_FILE_PATH:
            log.info(f"[domrf_web] Читаю локальный файл: {LOCAL_FILE_PATH}")
            return Path(LOCAL_FILE_PATH).read_bytes()

        log.info(f"[domrf_web] Скачиваю файл: {FILE_URL}")
        session = requests.Session()
        kwargs: dict = {"timeout": 120, "headers": HEADERS}
        if _IMPERSONATE:
            kwargs["impersonate"] = _IMPERSONATE
        try:
            resp = session.get(FILE_URL, **kwargs)
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(
                f"Не удалось скачать файл с ЕИСЖС: {e}\n"
                f"URL: {FILE_URL}\n"
                f"Убедитесь, что установлен curl_cffi: pip install curl_cffi\n"
                f"Либо скачайте файл вручную и укажите LOCAL_FILE_PATH в parsers/domrf_web.py"
            ) from e

        log.info(f"[domrf_web] Файл скачан: {len(resp.content):,} байт")
        return resp.content

    def parse(self, raw: bytes) -> list[dict]:
        """
        Парсит Excel-файл, извлекает данные по РФ из листа 01_01_00.

        Возвращает:
          [{"indicator_code": str, "period_date": date,
            "period_label": str, "value": float|None}, ...]
        """
        df = pd.read_excel(
            io.BytesIO(raw),
            sheet_name=SHEET_NAME,
            header=None,
        )
        log.info(f"[domrf_web] Лист {SHEET_NAME}: {df.shape[0]} строк × {df.shape[1]} столбцов")

        if df.empty:
            log.warning("[domrf_web] Датафрейм пустой")
            return []

        # Извлекаем даты из строки DATE_HEADER_ROW
        date_row = df.iloc[DATE_HEADER_ROW]
        col_dates: dict[int, date] = {}
        for col in range(DATE_COL_START, len(date_row)):
            d = _parse_col_date(date_row.iloc[col])
            if d is not None:
                col_dates[col] = d

        if not col_dates:
            log.warning("[domrf_web] Не удалось распарсить даты из строки-заголовка")
            return []

        log.info(
            f"[domrf_web] Дат: {len(col_dates)} "
            f"({min(col_dates.values())} – {max(col_dates.values())})"
        )

        records: list[dict] = []
        for row_idx, (code, divisor) in ROW_MAP.items():
            if row_idx >= len(df):
                log.warning(f"[domrf_web] Строка {row_idx} выходит за пределы датафрейма")
                continue

            row = df.iloc[row_idx]
            row_records = 0
            for col, d in col_dates.items():
                val = _safe_float(row.iloc[col] if col < len(row) else None)
                if val is not None and divisor != 1.0:
                    val = round(val / divisor, 7)
                records.append({
                    "indicator_code": code,
                    "period_date":    d,
                    "period_label":   _period_label(d),
                    "value":          val,
                })
                row_records += 1

            log.debug(f"[domrf_web] {code}: {row_records} записей")

        unique_codes = len({r["indicator_code"] for r in records})
        log.info(f"[domrf_web] Распарсено: {len(records)} записей по {unique_codes} кодам")
        return records


# ─── Точка входа ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(description="DomRF ЕИСЖС parser (01_01_stockvariablesexsales.xlsx)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Только fetch+parse, без записи в БД")
    ap.add_argument("--file", help="Путь к локальному xlsx (пропустить скачивание)")
    args = ap.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = DomRFWebParser()

    if args.dry_run or args.file:
        if args.file:
            raw = Path(args.file).read_bytes()
            log.info(f"Читаю локальный файл: {args.file}")
        else:
            raw = parser.fetch_raw()
        records = parser.parse(raw)
        from collections import Counter
        by_code = Counter(r["indicator_code"] for r in records)
        print(f"\nИтого: {len(records)} записей")
        print(f"Коды: {sorted(by_code.keys())}")
        if records:
            dates = [r["period_date"] for r in records]
            print(f"Диапазон дат: {min(dates)} — {max(dates)}")
            print(f"Последняя дата: {max(dates)}")
        for code in sorted(by_code.keys()):
            n = by_code[code]
            latest = max(r["period_date"] for r in records if r["indicator_code"] == code)
            latest_val = next(r["value"] for r in records
                              if r["indicator_code"] == code and r["period_date"] == latest)
            print(f"  {code}: {n} точек, последняя {latest} = {latest_val}")
    else:
        result = parser.run()
        print(result)
