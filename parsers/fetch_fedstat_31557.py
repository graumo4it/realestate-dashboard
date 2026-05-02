"""
parsers/fetch_fedstat_31557.py

Парсер численности постоянного населения с fedstat.ru/indicator/31557.

Алгоритм:
1. GET /indicator/31557 → JSESSIONID cookie + парсим JS-объект FGrid.filters
2. Из filters получаем реальные ID для: года, региона (РФ / РФ без новых субъектов),
   единицы измерения, типа периода
3. POST /indicator/dataGrid.do с правильным payload → JSON с данными
4. Upsert в data_points, refresh materialized view

Особенности:
- 1990–2022: регион = "Российская Федерация"
- 2023+:     регион = "Российская Федерация без учета новых субъектов (с 01.01.2023)"

ВАЖНО: fedstat блокирует облачные IP. Запускать только локально.

Использование:
    python3 parsers/fetch_fedstat_31557.py                    # все годы 1990–2025
    python3 parsers/fetch_fedstat_31557.py --years 2024 2025  # конкретные годы
    python3 parsers/fetch_fedstat_31557.py --dry-run          # без записи в БД
    python3 parsers/fetch_fedstat_31557.py --dump-filters     # показать все фильтры и выйти
"""

import json
import logging
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

# .env
for _env_path in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path.cwd() / ".env",
]:
    if _env_path.exists():
        load_dotenv(_env_path)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.fedstat.ru"
INDICATOR_ID = "31557"
INDICATOR_CODE = "1.1"
REQUEST_DELAY = 1.3  # сек между запросами


# ─────────────────────────────────────────────────────────────────────────────
# Шаг 1: загружаем страницу, получаем JSESSIONID и парсим filters из JS
# ─────────────────────────────────────────────────────────────────────────────

def load_page_and_parse_filters(session: requests.Session) -> dict:
    """
    Загружает страницу индикатора, получает JSESSIONID cookie,
    извлекает объект filters из JS-кода FGrid({...}).

    Структура filters:
    {
      "0":  {"title": "Показатель", "indicator": True,
             "values": {"31557": {"title": "Численность..."}}},
      "3":  {"title": "Год",
             "values": {"1990": {"title": "1990"}, "1991": ..., "2025": ...}},
      "NN": {"title": "Единица измерения",
             "values": {"XXX": {"title": "тыс. человек"}, ...}},
      "MM": {"title": "...",
             "values": {"YYY": {"title": "Российская Федерация"}, ...}},
      ...
    }
    """
    url = f"{BASE_URL}/indicator/{INDICATOR_ID}"
    log.info(f"GET {url}")
    resp = session.get(url, timeout=90)
    resp.raise_for_status()
    session.headers["Referer"] = url

    log.info(f"  Cookies: {dict(session.cookies)}")

    # Ищем JS-объект переданный в new FGrid({...})
    # Он содержит ключ filters: { 0: {...}, 3: {...}, ... }
    script_text = ""
    for tag in _iter_scripts(resp.text):
        if "FGrid" in tag and "filters" in tag:
            script_text = tag
            log.info(f"  Найден JS-блок FGrid ({len(script_text)} байт)")
            break

    if not script_text:
        raise RuntimeError("JS-блок с FGrid не найден на странице")

    # Извлекаем блок filters: { ... }
    # Используем простой поиск по уровням скобок
    filters_raw = _extract_filters_block(script_text)
    if not filters_raw:
        raise RuntimeError("Не удалось извлечь блок filters из JS")

    # Парсим как JSON (после нормализации JS → JSON)
    filters = _parse_js_object(filters_raw)
    log.info(f"  Распарсено фильтров: {len(filters)}")

    return filters


def _iter_scripts(html: str):
    """Возвращает содержимое всех <script> тегов."""
    for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        yield m.group(1)


def _extract_filters_block(js: str) -> Optional[str]:
    """
    Находит блок filters: { ... } в JS-строке.
    Корректно обрабатывает вложенные скобки.
    """
    m = re.search(r'filters\s*:\s*\{', js)
    if not m:
        return None

    start = m.end() - 1  # позиция открывающей {
    depth = 0
    i = start
    while i < len(js):
        if js[i] == '{':
            depth += 1
        elif js[i] == '}':
            depth -= 1
            if depth == 0:
                return js[start:i+1]
        i += 1
    return None


def _parse_js_object(js_obj: str) -> dict:
    """
    Конвертирует JS-объект в Python dict.
    Обрабатывает: числовые ключи, одинарные кавычки, Unicode-escapes,
    trailing commas, unquoted keys.
    """
    # Unicode escapes → реальные символы
    text = js_obj.encode().decode('unicode_escape', errors='replace')

    # Числовые ключи объектов: { 1990: → { "1990":
    text = re.sub(r'(\{|,)\s*(\d+)\s*:', r'\1"\2":', text)

    # Unquoted string ключи: { title: → { "title":
    text = re.sub(r'(\{|,)\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', text)

    # Одинарные кавычки → двойные (аккуратно)
    text = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", lambda m: json.dumps(m.group(1)), text)

    # Trailing commas: ,} и ,]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Fallback: regex-парсинг ключей и values
        log.warning(f"JSON parse failed ({e}), используем regex fallback")
        return _regex_parse_filters(js_obj)


def _regex_parse_filters(js_obj: str) -> dict:
    """Fallback парсер: извлекает filter_id → {title, values} через regex."""
    result = {}
    # Ищем блоки вида: "123": { title: '...', values: { ... } }
    for m in re.finditer(r'["\']?(\d+)["\']?\s*:\s*\{', js_obj):
        fid = m.group(1)
        block_start = m.end() - 1
        block = _extract_block(js_obj, block_start)
        if not block:
            continue

        title_m = re.search(r'title\s*:\s*["\']([^"\']+)["\']', block)
        title = title_m.group(1) if title_m else ""

        # Извлекаем values
        values = {}
        values_m = re.search(r'values\s*:\s*\{', block)
        if values_m:
            val_start = values_m.end() - 1
            val_block = _extract_block(block, val_start)
            if val_block:
                for vm in re.finditer(
                    r'["\']?(\d+)["\']?\s*:\s*\{[^}]*title\s*:\s*["\']([^"\']+)["\']',
                    val_block
                ):
                    values[vm.group(1)] = {"title": vm.group(2)}

        result[fid] = {"title": title, "values": values}
    return result


def _extract_block(text: str, start: int) -> Optional[str]:
    """Извлекает сбалансированный {}-блок начиная с позиции start."""
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
        i += 1
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Шаг 2: определяем нужные filter ID из структуры filters
# ─────────────────────────────────────────────────────────────────────────────

def resolve_filter_ids(filters: dict) -> dict:
    """
    Из словаря filters определяет:
      year_fid       — filter_id для года (обычно "3")
      region_fid     — filter_id для региона
      region_rf_vid  — value_id "Российская Федерация" (1990–2022)
      region_new_vid — value_id "РФ без учета новых субъектов" (2023+)
      unit_fid       — filter_id единицы измерения
      unit_thous_vid — value_id "тыс. человек"
      period_fid     — filter_id типа периода (на начало/конец года)
      period_jan_vid — value_id "на начало года" / "январь"

    Возвращает dict с этими полями (None если не найдено).
    """
    result = {
        "year_fid": None,
        "region_fid": None, "region_rf_vid": None, "region_new_vid": None,
        "unit_fid": None, "unit_thous_vid": None,
        "period_fid": None, "period_jan_vid": None,
    }

    for fid, fdata in filters.items():
        if not isinstance(fdata, dict):
            continue
        values = fdata.get("values", {})
        if not isinstance(values, dict):
            continue

        titles = {vid: (v.get("title", "") if isinstance(v, dict) else str(v))
                  for vid, v in values.items()}
        titles_lower = {k: v.lower() for k, v in titles.items()}

        # Фильтр года: значения совпадают с годами
        if any(t.strip() in [str(y) for y in range(1985, 2030)]
               for t in titles.values()):
            result["year_fid"] = fid
            log.info(f"  Год: filter_id={fid}, "
                     f"доступные={sorted(titles.keys())[:5]}...{sorted(titles.keys())[-3:]}")
            continue

        # Фильтр региона: есть "российская федерация"
        if any("российская федерация" in t for t in titles_lower.values()):
            result["region_fid"] = fid

            # Точное совпадение "Российская Федерация" (без доп. слов)
            rf_vid = next(
                (vid for vid, t in titles_lower.items()
                 if t.strip() == "российская федерация"),
                None
            )
            # "РФ без учета новых субъектов"
            rf_new_vid = next(
                (vid for vid, t in titles_lower.items()
                 if "без учета новых субъектов" in t),
                None
            )
            # Fallback если нет точного совпадения
            if not rf_vid:
                rf_vid = next(
                    (vid for vid, t in titles_lower.items()
                     if "российская федерация" in t and "без учета" not in t),
                    None
                )

            result["region_rf_vid"] = rf_vid
            result["region_new_vid"] = rf_new_vid
            log.info(f"  Регион: filter_id={fid}, "
                     f"РФ={rf_vid}, РФ_без_новых={rf_new_vid}")
            log.info(f"    Все варианты: {list(titles.items())[:8]}")
            continue

        # Фильтр единицы: есть "тыс"
        if any("тыс" in t for t in titles_lower.values()):
            result["unit_fid"] = fid
            thous_vid = next(
                (vid for vid, t in titles_lower.items() if "тыс" in t),
                None
            )
            result["unit_thous_vid"] = thous_vid
            log.info(f"  Единица: filter_id={fid}, тыс={thous_vid}, "
                     f"варианты={list(titles.items())[:5]}")
            continue

        # Фильтр периода: есть "начал" или "январ"
        if any("начал" in t or "январ" in t for t in titles_lower.values()):
            result["period_fid"] = fid
            jan_vid = next(
                (vid for vid, t in titles_lower.items()
                 if "начал" in t or "январ" in t),
                None
            )
            result["period_jan_vid"] = jan_vid
            log.info(f"  Период: filter_id={fid}, янв={jan_vid}, "
                     f"варианты={list(titles.items())[:5]}")
            continue

    # Проверка
    if not result["year_fid"]:
        raise RuntimeError("Не найден фильтр года в структуре filters")
    if not result["region_fid"]:
        log.warning("Фильтр региона не найден — запрос будет без него")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Шаг 3: запрашиваем данные
# ─────────────────────────────────────────────────────────────────────────────

def fetch_years(session: requests.Session,
                filters: dict,
                fids: dict,
                years: list) -> dict:
    """
    Для каждого года делает POST /indicator/dataGrid.do.
    Возвращает {год: значение_тыс_чел}.
    """
    url = f"{BASE_URL}/indicator/dataGrid.do"
    session.headers.update({
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": BASE_URL,
    })

    # Доступные годы в фильтре
    year_fid = fids["year_fid"]
    available_years = set(filters.get(year_fid, {}).get("values", {}).keys())

    results = {}

    for year in sorted(years):
        year_str = str(year)

        if year_str not in available_years:
            log.warning(f"  {year}: год недоступен в фильтре, пропускаем")
            continue

        # Выбор региона по году
        if year >= 2023 and fids.get("region_new_vid"):
            region_vid = fids["region_new_vid"]
            log.debug(f"  {year}: используем 'РФ без новых субъектов' (vid={region_vid})")
        else:
            region_vid = fids.get("region_rf_vid")
            log.debug(f"  {year}: используем 'Российская Федерация' (vid={region_vid})")

        # Формируем payload
        # lineObjectIds: оси строк — год (3) + показатель (0)
        # columnObjectIds: ось столбцов — 0 (сам показатель уже там)
        # selectedFilterIds: выбранные значения каждого фильтра
        parts = []
        parts.append(f"lineObjectIds=0")          # ось: показатель
        parts.append(f"lineObjectIds={year_fid}") # ось: год
        parts.append(f"columnObjectIds=0")         # столбец: значение

        # Год
        parts.append(f"selectedFilterIds={year_fid}_{year_str}")

        # Показатель (filter 0)
        parts.append(f"selectedFilterIds=0_{INDICATOR_ID}")

        # Регион
        if fids.get("region_fid") and region_vid:
            parts.append(f"selectedFilterIds={fids['region_fid']}_{region_vid}")

        # Единица измерения (тыс. человек)
        if fids.get("unit_fid") and fids.get("unit_thous_vid"):
            parts.append(f"selectedFilterIds={fids['unit_fid']}_{fids['unit_thous_vid']}")

        # Тип периода (на начало года)
        if fids.get("period_fid") and fids.get("period_jan_vid"):
            parts.append(f"selectedFilterIds={fids['period_fid']}_{fids['period_jan_vid']}")

        payload = "&".join(parts)
        log.debug(f"  Payload: {payload}")

        try:
            resp = session.post(url, data=payload, timeout=90)
            resp.raise_for_status()

            # Проверяем что получили JSON, а не HTML
            ct = resp.headers.get("content-type", "")
            if "html" in ct or resp.text.strip().startswith("<!"):
                log.error(f"  {year}: получен HTML вместо JSON — сессия истекла или "
                          f"неверный payload")
                log.debug(f"  Response (200 chars): {resp.text[:200]}")
                break

            data = resp.json()
            value = _parse_value(data, year_str)

            if value is not None:
                results[year] = value
                log.info(f"  {year}: {value:,.1f} тыс. чел.")
            else:
                log.warning(f"  {year}: значение не найдено. "
                            f"Ответ: {json.dumps(data, ensure_ascii=False)[:300]}")

        except requests.HTTPError as e:
            log.warning(f"  {year}: HTTP {e}")
        except ValueError as e:
            log.warning(f"  {year}: не JSON ({e}). "
                        f"Начало ответа: {resp.text[:100]}")
        except Exception as e:
            log.warning(f"  {year}: {type(e).__name__}: {e}")

        time.sleep(REQUEST_DELAY)

    return results


def _parse_value(data, year_str: str) -> Optional[float]:
    """
    Извлекает числовое значение из ответа dataGrid.do.
    Fedstat возвращает что-то вроде:
    {"cells": [{"y":0,"x":0,"value":"142737"}], "rowTitles": [...], "colTitles": [...]}
    или {"results": [{"0_0": "142737", ...}]}
    """
    # Формат 1: cells[]
    for cell in data.get("cells", []):
        v = cell.get("value") or cell.get("v")
        if v and str(v) not in ("", "-", "…", "н/д"):
            try:
                return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
            except ValueError:
                pass

    # Формат 2: results[]
    for row in data.get("results", []):
        for k, v in row.items():
            if v and str(v) not in ("", "-", "…", "н/д"):
                try:
                    return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
                except ValueError:
                    pass

    # Формат 3: data[][]
    for row in data.get("data", []):
        if isinstance(row, list):
            for v in row:
                if v and str(v) not in ("", "-"):
                    try:
                        return float(str(v).replace(",", "."))
                    except (ValueError, TypeError):
                        pass

    # Формат 4: плоский dict
    for k, v in data.items():
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v not in ("", "-"):
            try:
                return float(v.replace("\xa0", "").replace(" ", "").replace(",", "."))
            except ValueError:
                pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# БД
# ─────────────────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def upsert(cur, data: dict) -> int:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (INDICATOR_CODE,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Индикатор {INDICATOR_CODE} не найден. "
                           f"Запустите migrate_population_1990_2010.py")
    ind_id = row[0]

    rows = [
        (ind_id, date(year, 1, 1), str(year), value, False)
        for year, value in sorted(data.items())
    ]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO data_points
            (indicator_id, period_date, period_label, value, is_preliminary)
        VALUES %s
        ON CONFLICT (indicator_id, period_date) DO UPDATE
            SET value          = EXCLUDED.value,
                is_preliminary = EXCLUDED.is_preliminary
        """,
        rows,
        template="(%s, %s, %s, %s, %s)",
    )
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Парсер fedstat.ru/indicator/31557 — население РФ"
    )
    parser.add_argument("--years", nargs="+", type=int,
                        help="Конкретные годы (напр. --years 2023 2024 2025)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Показать данные без записи в БД")
    parser.add_argument("--dump-filters", action="store_true",
                        help="Вывести полную структуру фильтров и выйти")
    args = parser.parse_args()

    years = args.years or list(range(1990, 2026))

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })

    # Шаг 1: загружаем страницу и парсим filters (retry до 3 раз)
    log.info("Шаг 1: загружаем страницу и парсим структуру фильтров...")
    filters = None
    for attempt in range(1, 4):
        try:
            filters = load_page_and_parse_filters(session)
            break
        except requests.exceptions.Timeout:
            log.warning(f"  Попытка {attempt}/3: таймаут, ждём 15 сек...")
            time.sleep(15)
        except Exception as e:
            log.error(f"Ошибка: {e}")
            sys.exit(1)
    if filters is None:
        log.error("Сайт не отвечает после 3 попыток. Проверьте соединение.")
        sys.exit(1)

    # --dump-filters: показать всё и выйти
    if args.dump_filters:
        log.info("=== Полная структура фильтров ===")
        for fid, fdata in sorted(filters.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
            title = fdata.get("title", "") if isinstance(fdata, dict) else ""
            values = fdata.get("values", {}) if isinstance(fdata, dict) else {}
            log.info(f"Filter {fid}: '{title}'")
            for vid, vdata in list(values.items())[:10]:
                vtitle = vdata.get("title", "") if isinstance(vdata, dict) else str(vdata)
                log.info(f"  {vid}: '{vtitle}'")
            if len(values) > 10:
                log.info(f"  ... ещё {len(values)-10} значений")
        return

    time.sleep(REQUEST_DELAY)

    # Шаг 2: определяем нужные filter ID
    log.info("Шаг 2: определяем filter ID...")
    try:
        fids = resolve_filter_ids(filters)
    except RuntimeError as e:
        log.error(str(e))
        log.info("Запустите --dump-filters для анализа структуры")
        sys.exit(1)

    # Шаг 3: загружаем данные
    log.info(f"Шаг 3: загружаем данные за {min(years)}–{max(years)}...")
    data = fetch_years(session, filters, fids, years)

    if not data:
        log.error("Не получено ни одного значения.")
        sys.exit(1)

    log.info(f"Итого получено: {len(data)} значений")

    if args.dry_run:
        log.info("─" * 40)
        for year, val in sorted(data.items()):
            log.info(f"  {year}: {val:,.1f} тыс. чел.")
        return

    # Шаг 4: пишем в БД
    log.info("Шаг 4: записываем в БД...")
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                count = upsert(cur, data)
                log.info(f"Записано: {count} строк")
                cur.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                )
                log.info("Materialized view обновлён ✓")
    finally:
        conn.close()

    log.info("Готово!")


if __name__ == "__main__":
    main()
