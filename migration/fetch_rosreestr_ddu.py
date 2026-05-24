"""
migration/fetch_rosreestr_ddu.py

Скрипт для обновления индикатора 5.1 «Количество ДДУ (Росреестр)»
из открытых данных на rosreestr.gov.ru.

Источник:
  https://rosreestr.gov.ru/open-service/statistika-i-analitika/
  ~svedeniya--analiticheskie-otchety-ca/svedeniya-po-pokazatelyam-...

Формат файлов:
  Накопительные XLS-файлы за каждый период внутри года:
    январь-март       → Q1 (period_date = YYYY-01-01)
    январь-июнь       → Q2 = H1 − Q1 (period_date = YYYY-04-01)
    январь-сентябрь   → Q3 = 9M − H1 (period_date = YYYY-07-01)
    январь-декабрь    → Q4 = Y − 9M  (period_date = YYYY-10-01)

  Нужная строка: «Российская Федерация*», колонка 1 (общее кол-во ДДУ).

⚠️  rosreestr.gov.ru использует самоподписанный российский сертификат.
    Подключение через subprocess curl -sk (обходит проверку сертификата).

ЗАПУСКАТЬ ЛОКАЛЬНО.

Использование:
  source venv/bin/activate
  python migration/fetch_rosreestr_ddu.py          # все доступные периоды
  python migration/fetch_rosreestr_ddu.py --dry-run  # без записи в БД
"""

import os, sys, re, subprocess, logging, argparse
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import xlrd
import psycopg2, psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ─── Константы ────────────────────────────────────────────────────────────────

PAGE_URL = (
    "https://rosreestr.gov.ru/open-service/statistika-i-analitika/"
    "~svedeniya--analiticheskie-otchety-ca/"
    "svedeniya-po-pokazatelyam-kolichestvo-zaregistrirovannykh-"
    "ddu-kolichestvo-zaregistrirovannykh-ddu/"
)
BASE_URL = "https://rosreestr.gov.ru"

# Накопительный период → (label квартала, месяц начала квартала)
PERIOD_MAP = {
    "январь-март":     ("Q1",  1),
    "январь-июнь":     ("H1",  4),   # cumulative H1 → вычтем Q1 → Q2
    "январь-сентябрь": ("9M",  7),   # cumulative 9M → вычтем H1 → Q3
    "январь-декабрь":  ("Y",  10),   # cumulative Y  → вычтем 9M → Q4
}


# ─── HTTP helper (curl subprocess) ────────────────────────────────────────────

def curl_fetch(url: str) -> bytes:
    """Скачивает URL через curl -sk (обход самоподписанного сертификата)."""
    result = subprocess.run(
        ["curl", "-sk", url, "-H", "User-Agent: Mozilla/5.0"],
        capture_output=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr.decode()[:200]}")
    return result.stdout


# ─── Парсинг страницы ──────────────────────────────────────────────────────────

def find_xls_links(html: str) -> list[str]:
    """Возвращает список relative-путей к .xls файлам ДДУ."""
    return re.findall(r'href="(/upload/[^"]*\.xls[^"]*)"', html)


def detect_year(url_path: str) -> int | None:
    m = re.search(r'(\d{4})', unquote(url_path))
    return int(m.group(1)) if m else None


def detect_period(url_path: str) -> tuple[str, int] | None:
    """Возвращает (period_label, start_month) для накопительного периода."""
    fn = unquote(url_path).lower()
    for key, val in PERIOD_MAP.items():
        if key in fn:
            return val
    return None


# ─── Парсинг XLS ──────────────────────────────────────────────────────────────

def extract_rf_total(content: bytes) -> int | None:
    """
    Извлекает значение «Российская Федерация» (строка 2, столбец 1) из XLS.
    Возвращает int или None, если строка не найдена.
    """
    wb = xlrd.open_workbook(file_contents=content)
    sh = wb.sheet_by_index(0)
    for row_i in range(min(sh.nrows, 10)):
        cell_text = str(sh.cell_value(row_i, 0)).lower()
        if "российская федерация" in cell_text:
            raw = str(sh.cell_value(row_i, 1))
            # Убираем nbsp, пробелы, звёздочки
            raw = re.sub(r'[\s*\xa0   ]', '', raw)
            try:
                return int(float(raw.replace(',', '.')))
            except ValueError:
                log.warning(f"  Не удалось разобрать значение: {repr(raw)}")
                return None
    log.warning("  Строка 'Российская Федерация' не найдена в файле")
    return None


# ─── БД ───────────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_last_date(conn, code: str) -> date | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(dp.period_date)
            FROM data_points dp
            JOIN indicators i ON i.id = dp.indicator_id
            WHERE i.code = %s
        """, (code,))
        row = cur.fetchone()
        return row[0] if row else None


def upsert_points(conn, code: str, points: list[dict]) -> int:
    """Вставляет новые точки с DO NOTHING (не перезаписывает существующие)."""
    if not points:
        return 0
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Индикатор {code!r} не найден в таблице indicators")
        ind_id = row[0]

        psycopg2.extras.execute_values(cur, """
            INSERT INTO data_points (indicator_id, period_date, period_label, value)
            VALUES %s
            ON CONFLICT (indicator_id, period_date) DO NOTHING
        """, [(ind_id, p["date"], p["label"], p["value"]) for p in points])
        return cur.rowcount


# ─── Основная логика ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Загружает 5.1 ДДУ из rosreestr.gov.ru")
    parser.add_argument("--dry-run", action="store_true",
                        help="Не писать в БД — только вывести рассчитанные точки")
    args = parser.parse_args()

    conn = get_conn()
    last_date = get_last_date(conn, "5.1")
    if args.dry_run:
        conn.close()
        conn = None
    log.info(f"5.1 ДДУ — последняя точка в БД: {last_date}")
    log.info(f"Источник: {PAGE_URL}\n")

    # Скачиваем страницу
    log.info("Скачиваем индексную страницу rosreestr.gov.ru ...")
    html = curl_fetch(PAGE_URL).decode("utf-8", errors="replace")
    links = find_xls_links(html)
    log.info(f"Найдено файлов: {len(links)}")

    # Скачиваем и парсим каждый файл
    cumulative: dict[int, dict[int, int]] = {}  # {year: {month: cumulative_value}}

    for link in links:
        year = detect_year(link)
        period = detect_period(link)
        if not year or not period:
            log.warning(f"  Пропуск (нет года/периода): {unquote(link)}")
            continue
        period_label, month = period
        short_name = unquote(link).split("/")[-1]

        log.info(f"  {year} {period_label:3s} — {short_name}")
        try:
            content = curl_fetch(BASE_URL + link)
            val = extract_rf_total(content)
            if val is None:
                log.warning(f"    → значение не найдено, пропуск")
                continue
            log.info(f"    → {val:,} ДДУ")
            cumulative.setdefault(year, {})[month] = val
        except Exception as e:
            log.error(f"    → ошибка: {e}")

    # Вычисляем квартальные значения (разности накопительных)
    log.info("\n=== Расчёт квартальных значений ===")
    points = []
    for year in sorted(cumulative.keys()):
        d = cumulative[year]
        q1_val = d.get(1)
        h1_val = d.get(4)
        m9_val = d.get(7)
        fy_val = d.get(10)

        quarters = [
            ("Q1", 1,  q1_val),
            ("Q2", 4,  (h1_val - q1_val) if (h1_val and q1_val) else None),
            ("Q3", 7,  (m9_val - h1_val) if (m9_val and h1_val) else None),
            ("Q4", 10, (fy_val - m9_val) if (fy_val and m9_val) else None),
        ]

        for ql, mon, val in quarters:
            period_date = date(year, mon, 1)
            if val is None:
                log.info(f"  {year} {ql}: — (нет данных)")
                continue
            is_new = last_date is None or period_date > last_date
            log.info(f"  {year} {ql}: {val:>10,}  [{period_date}] {'← NEW' if is_new else '(уже в БД)'}")
            points.append({"date": period_date, "label": f"{ql} {year}", "value": val})

    if args.dry_run:
        log.info(f"\n[DRY-RUN] Точек к вставке (всего, с DO NOTHING): {len(points)}")
        return

    # Вставка в БД
    log.info(f"\nВставка в БД ...")
    n = upsert_points(conn, "5.1", points)
    conn.commit()
    log.info(f"  Вставлено новых точек: {n}")

    # Обновляем materialized view
    log.info("Обновление materialized view ...")
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    conn.commit()
    log.info("Готово.")

    conn.close()
    log.info(f"\nИтого загружено: {n} точек")


if __name__ == "__main__":
    main()
