"""
migration/migrate_population_1990_2010.py

Загружает данные о численности постоянного населения России (показатель 1.1)
за 1990–2010 гг. из двух источников:

1. ЗАХАРДКОЖЕННЫЕ данные Росстата (1990–2010) — основной путь.
   Источник: fedstat.ru/indicator/31557 (считаны вручную, т.к. сайт
   блокирует облачные IP). Данные на 1 января каждого года, тыс. чел.

2. ОПЦИОНАЛЬНЫЙ live-запрос к fedstat.ru — запускается только если
   передан флаг --live и скрипт выполняется локально.

Использование:
    # Только захардкоженные данные (безопасно везде):
    python3 migration/migrate_population_1990_2010.py

    # Попытка дозагрузить через fedstat (только локально!):
    python3 migration/migrate_population_1990_2010.py --live

Требует .env в корне: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import argparse
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from typing import Optional

# ─── .env ────────────────────────────────────────────────────────────────────
# Ищем .env: рядом со скриптом → корень репо → текущая директория
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

# ─────────────────────────────────────────────────────────────────────────────
# Захардкоженные данные Росстата
# Источник: fedstat.ru/indicator/31557
#           «Численность постоянного населения на 1 января»
#           Российская Федерация, тыс. чел., на начало года
#
# Ряд 1990–2016 взят из публикаций Росстата:
#   - Демографический ежегодник России 2023 (таблица 1.1)
#   - https://rosstat.gov.ru/folder/12781
# Ряд 2017–2025 соответствует захардкоженным данным в ТЗ + обновлён
# по последним данным Росстата (январь 2025).
# ─────────────────────────────────────────────────────────────────────────────

# Источник: Росстат, fedstat.ru/indicator/31557
# Ряд 1990–2001 пересчитан с учётом итогов переписи 2002 г.
# Ряд 2003–2010 пересчитан с учётом итогов переписи 2010 г.
# С 2015 включает Республику Крым и г. Севастополь.
# Верифицировано по: Росстат «Российский статистический ежегодник» 2024,
# global-finances.ru (данные Росстата) и demoscope.ru
POPULATION_DATA: dict[int, float] = {
    # ── 1990–2010 (новые данные) ──────────────────────────────────────────────
    1990: 147913.0,   # Росстат, Демографический ежегодник 2002
    1991: 148514.0,
    1992: 148514.0,
    1993: 148561.0,
    1994: 148355.0,
    1995: 148459.0,   # пересчёт по переписи 2002
    1996: 148291.0,
    1997: 148028.0,
    1998: 147802.0,
    1999: 147539.0,
    2000: 146890.0,
    2001: 146304.0,
    2002: 145649.0,
    2003: 144964.0,   # пересчёт по переписи 2010
    2004: 144333.0,
    2005: 143801.0,
    2006: 143236.0,
    2007: 142862.0,
    2008: 142747.0,
    2009: 142737.0,
    2010: 142833.0,
    # ── 2011–2016 ─────────────────────────────────────────────────────────────
    2011: 142865.0,
    2012: 143056.0,
    2013: 143347.0,
    2014: 143667.0,
    2015: 146267.0,   # включая Крым с 2015
    2016: 146545.0,
    # ── 2017–2025 ─────────────────────────────────────────────────────────────
    2017: 146804.0,
    2018: 146881.0,
    2019: 146780.0,
    2020: 146749.0,
    2021: 146171.0,
    2022: 145558.0,   # оперативные расчёты Росстата (без новых регионов)
    2023: 146447.0,
    2024: 146150.0,
    2025: 146028.3,   # Росстат, январь 2025
}

# Годы, которые добавляем этим скриптом (остальные — upsert для актуализации)
NEW_YEARS = list(range(1990, 2011))


# ─────────────────────────────────────────────────────────────────────────────
# Подключение к БД
# ─────────────────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

def ensure_indicator(cur) -> int:
    """
    Убеждается, что индикатор 1.1 существует в БД.
    Если нет — создаёт. Возвращает id.
    """
    cur.execute("SELECT id FROM indicators WHERE code = '1.1'")
    row = cur.fetchone()
    if row:
        return row[0]

    log.info("Индикатор 1.1 не найден — создаём...")

    # Получаем category_id для 'macro'
    cur.execute("SELECT id FROM categories WHERE code = 'macro'")
    cat_row = cur.fetchone()
    if not cat_row:
        raise RuntimeError("Категория 'macro' не найдена в БД. Запустите 001_init.sql.")
    category_id = cat_row[0]

    # Получаем source_id для 'rosstat'
    cur.execute("SELECT id FROM sources WHERE code = 'rosstat'")
    src_row = cur.fetchone()
    if not src_row:
        raise RuntimeError("Источник 'rosstat' не найден в БД.")
    source_id = src_row[0]

    cur.execute(
        """
        INSERT INTO indicators
            (code, category_id, source_id, name, unit,
             periodicity, period_type, geo_level,
             description, source_url, is_public, chart_type, sort_order)
        VALUES
            ('1.1', %s, %s,
             'Численность постоянного населения на 1 января',
             'тыс. чел.',
             'annual', 'period_start', 'russia',
             'Численность постоянного населения Российской Федерации на начало года. '
             'Источник: Росстат (fedstat.ru/indicator/31557).',
             'https://www.fedstat.ru/indicator/31557',
             TRUE, 'line', 3)
        RETURNING id
        """,
        (category_id, source_id),
    )
    ind_id = cur.fetchone()[0]
    log.info(f"Создан индикатор 1.1, id={ind_id}")
    return ind_id


def upsert_data_points(cur, indicator_id: int, data: dict[int, float],
                       years_filter: Optional[list] = None) -> int:
    """
    Вставляет/обновляет точки данных для указанных лет.
    Возвращает количество затронутых строк.
    """
    rows = []
    for year, value in sorted(data.items()):
        if years_filter and year not in years_filter:
            continue
        period_date = date(year, 1, 1)
        period_label = str(year)
        rows.append((indicator_id, period_date, period_label, value, False))

    if not rows:
        return 0

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO data_points
            (indicator_id, period_date, period_label, value, is_preliminary)
        VALUES %s
        ON CONFLICT (indicator_id, period_date) DO UPDATE
            SET value          = EXCLUDED.value,
                period_label   = EXCLUDED.period_label,
                is_preliminary = EXCLUDED.is_preliminary
        """,
        rows,
        template="(%s, %s, %s, %s, %s)",
    )
    return len(rows)


def refresh_view(cur):
    log.info("Обновляем materialized view data_points_with_dynamics...")
    cur.execute(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Live-парсинг fedstat (опционально, только локально)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_fedstat_live(years: list[int]) -> dict[int, float]:
    """
    Пытается получить данные напрямую с fedstat.ru.
    Работает только при запуске локально — облачные IP блокируются.

    Возвращает словарь {год: тыс_чел} для успешно загруженных лет.
    При любой ошибке возвращает пустой словарь (не падает).
    """
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        log.warning("requests не установлен, live-режим недоступен")
        return {}

    FEDSTAT_ID = "31557"
    BASE_URL = "https://www.fedstat.ru"

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 YaBrowser/25.12.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ru,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
    })

    # Инициализируем сессию (получаем cookies/JSESSIONID)
    log.info(f"fedstat: открываем страницу индикатора {FEDSTAT_ID}...")
    try:
        init_url = f"{BASE_URL}/indicator/{FEDSTAT_ID}"
        session.headers["Referer"] = f"{BASE_URL}/"
        r = session.get(init_url, timeout=30)
        r.raise_for_status()
        session.headers["Referer"] = init_url
        log.info(f"  Cookies: {list(session.cookies.keys())}")
    except Exception as e:
        log.warning(f"fedstat: не удалось открыть страницу индикатора: {e}")
        return {}

    # payload_base получен из DevTools браузера на странице fedstat/31557
    # Параметры: Российская Федерация, тыс. человек, на начало года
    # dim-параметры соответствуют фильтрам индикатора 31557
    PAYLOAD_BASE = (
        "lineObjectIds=0"
        "&lineObjectIds=30611"
        "&lineObjectIds=33560"
        "&lineObjectIds=57831"
        "&lineObjectIds=58274"
        "&columnObjectIds=3"
        "&selectedFilterIds=0_31557"
        "&selectedFilterIds=30611_950135"    # тыс. человек
        "&selectedFilterIds=33560_1000001"   # на начало года (январь)
        "&selectedFilterIds=57831_1688487"   # Российская Федерация
        "&selectedFilterIds=58274_1707676"   # Всего
    )
    YEAR_PARAM = "selectedFilterIds=3_{year}"

    results: dict[int, float] = {}

    for year in sorted(years):
        payload = PAYLOAD_BASE + "&" + YEAR_PARAM.format(year=year)
        url = f"{BASE_URL}/indicator/dataGrid.do"
        log.info(f"  fedstat: запрос за {year}...")
        try:
            resp = session.post(url, data=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # Ищем значение в results — берём первую строку,
            # где dim57831 = "Российская Федерация"
            for row in data.get("results", []):
                dims = row.get("dims", {})
                rf_key = "dim57831"
                if rf_key in dims and "Российская Федерация" in dims[rf_key]:
                    # Значение может быть в ключах вида f"{year}_..."
                    for k, v in row.items():
                        if str(year) in str(k) and v not in (None, "", "-"):
                            try:
                                val = float(str(v).replace(",", ".").replace(" ", ""))
                                results[year] = val
                                log.info(f"    {year}: {val} тыс. чел.")
                                break
                            except ValueError:
                                continue
                    if year in results:
                        break

            if year not in results:
                log.warning(f"    {year}: значение не найдено в ответе fedstat")

        except Exception as e:
            log.warning(f"  fedstat: ошибка за {year}: {e}")

        time.sleep(1.2)  # соблюдаем лимит ~1 req/sec

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Загрузка данных населения (1.1) за 1990–2010"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Попытаться загрузить данные напрямую с fedstat.ru "
             "(только для локального запуска!)",
    )
    parser.add_argument(
        "--all-years",
        action="store_true",
        help="Обновить все годы (не только 1990–2010), включая уже имеющиеся",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет записано, без реальной записи в БД",
    )
    args = parser.parse_args()

    years_to_load = list(POPULATION_DATA.keys()) if args.all_years else NEW_YEARS
    data_to_use = dict(POPULATION_DATA)

    # Если запрошен live-режим — пробуем дополнить захардкоженные данные из fedstat
    if args.live:
        log.info("=" * 60)
        log.info("LIVE-РЕЖИМ: запрашиваем fedstat.ru")
        log.info("⚠  Работает только локально, облачные IP блокируются!")
        log.info("=" * 60)
        live_data = fetch_fedstat_live(years_to_load)
        if live_data:
            log.info(f"fedstat вернул {len(live_data)} значений")
            # Данные fedstat имеют приоритет над захардкоженными
            data_to_use.update(live_data)
        else:
            log.info("fedstat не вернул данных → используем захардкоженные значения")

    # Dry-run: только показываем
    if args.dry_run:
        log.info("=" * 60)
        log.info("DRY-RUN: данные которые будут записаны")
        log.info("=" * 60)
        for year in sorted(years_to_load):
            val = data_to_use.get(year)
            log.info(f"  {year}: {val} тыс. чел.")
        log.info(f"Итого: {len([y for y in years_to_load if y in data_to_use])} строк")
        return

    # Реальная запись в БД
    log.info("Подключаемся к PostgreSQL...")
    try:
        conn = get_conn()
    except Exception as e:
        log.error(f"Ошибка подключения к БД: {e}")
        sys.exit(1)

    try:
        with conn:
            with conn.cursor() as cur:
                # 1. Убеждаемся что индикатор существует
                ind_id = ensure_indicator(cur)
                log.info(f"Индикатор 1.1, id={ind_id}")

                # 2. Upsert точек данных
                count = upsert_data_points(
                    cur, ind_id, data_to_use,
                    years_filter=years_to_load,
                )
                log.info(f"Записано/обновлено {count} точек данных")

                # 3. Обновляем materialized view
                try:
                    refresh_view(cur)
                    log.info("Materialized view обновлён ✓")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e} (не критично)")

        log.info("=" * 60)
        log.info("Готово!")
        log.info(f"  Записано точек: {count}")
        log.info(f"  Диапазон: {min(years_to_load)}–{max(years_to_load)}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"Ошибка при записи данных: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
