"""
migration/fetch_income_rosstat.py

Загружает показатели 1.2 и 1.2.y из Excel Росстата.

Источник: https://rosstat.gov.ru/folder/13397
Файл:     urov_10kv_{N}kv-{YYYY}.xlsx  (обновляется ежеквартально)
Лист:     СДД_РФ

Структура файла:
  YYYY год         ← маркер года
  1 квартал   <v>  → 1.2, period_date = YYYY-01-01
  2 квартал   <v>  → 1.2, period_date = YYYY-04-01
  3 квартал   <v>  → 1.2, period_date = YYYY-07-01
  4 квартал   <v>  → 1.2, period_date = YYYY-10-01
  Год         <v>  → 1.2.y, period_date = YYYY-01-01 (официальное годовое среднее)
  1 полугодие      ← пропускаем
  9 месяцев        ← пропускаем

Единица: рублей / месяц (столбец B).

1.2.y — companion-индикатор (periodicity='annual', is_public=false):
  отображается на chart.html в режиме «Год» для квартального графика 1.2.
  Официальное годовое значение Росстата, может незначительно отличаться
  от среднего четырёх кварталов (1.3.y считается именно так, но для 1.2
  Росстат публикует отдельную строку «Год» — используем её).

Запуск:
  source venv/bin/activate
  python migration/fetch_income_rosstat.py [--dry-run]

ЗАПУСК ТОЛЬКО ЛОКАЛЬНО — rosstat.gov.ru недоступен с зарубежных IP (SSL verify=False).
"""

import argparse
import io
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

import openpyxl
import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

for _env in [Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PAGE_URL = "https://rosstat.gov.ru/folder/13397"
FILE_PATTERN = re.compile(r"/storage/mediabank/(urov_10kv_\d+kv-\d+\.xlsx)", re.I)

QUARTER_MAP = {
    "1 квартал": (1,  "Q1"),
    "2 квартал": (4,  "Q2"),
    "3 квартал": (7,  "Q3"),
    "4 квартал": (10, "Q4"),
}
SKIP_LABELS = {"1 полугодие", "9 месяцев"}

CODE_QUARTERLY = "1.2"
CODE_ANNUAL    = "1.2.y"


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    s = requests.Session()
    s.verify = False   # rosstat.gov.ru — проблемы с SSL-цепочкой
    s.headers.update({"User-Agent": "Mozilla/5.0 (compatible; realestate-dashboard/1.0)"})
    return s


def find_file_url(session: requests.Session) -> str:
    """Находит актуальный URL xlsx-файла на странице /folder/13397."""
    log.info(f"Запрашиваем страницу {PAGE_URL} ...")
    r = session.get(PAGE_URL, timeout=30)
    r.raise_for_status()
    matches = FILE_PATTERN.findall(r.text)
    if not matches:
        raise RuntimeError(
            f"Не нашли ссылку urov_10kv_*.xlsx на странице {PAGE_URL}. "
            "Возможно, Росстат изменил имя файла."
        )
    filename = matches[0]   # первое вхождение — самое свежее
    url = f"https://rosstat.gov.ru/storage/mediabank/{filename}"
    log.info(f"Найден файл: {filename}")
    return url


def download_xlsx(session: requests.Session, url: str) -> bytes:
    log.info(f"Скачиваем {url} ...")
    r = session.get(url, timeout=60)
    r.raise_for_status()
    log.info(f"Скачано {len(r.content):,} байт")
    return r.content


# ── Парсинг Excel ─────────────────────────────────────────────────────────────

def _to_float(raw) -> float | None:
    """Приводит сырое значение ячейки к float; None если не удалось."""
    if raw is None:
        return None
    try:
        # Убираем сноски вида «74 9324)» → «74932» и лишние пробелы
        cleaned = re.sub(r"\s+", "", str(raw))   # убираем пробелы внутри числа
        cleaned = re.sub(r"\d\)$", "", cleaned)  # убираем trailing сноску «4)»
        return float(cleaned.replace(",", "."))
    except (ValueError, TypeError):
        return None


def parse_xlsx(content: bytes) -> tuple[list[dict], list[dict]]:
    """
    Парсит лист данных xlsx и возвращает (quarterly_records, annual_records).

    quarterly_records: {year, month, period_label, value}  → indicator 1.2
    annual_records:    {year, period_label, value}          → indicator 1.2.y
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)

    ws = None
    for name in wb.sheetnames:
        if name.strip() != "Содержание":
            ws = wb[name]
            break
    if ws is None:
        raise RuntimeError("Не нашли лист данных в xlsx.")
    log.info(f"Парсим лист «{ws.title}»")

    quarterly: list[dict] = []
    annual:    list[dict] = []
    current_year: int | None = None

    for row in ws.iter_rows(values_only=True):
        label = str(row[0]).strip() if row[0] is not None else ""
        raw   = row[1] if len(row) > 1 else None

        # Маркер года: «2024 год», «2025 год 3)» и т.п.
        m = re.match(r"^(\d{4})\s*год", label)
        if m:
            current_year = int(m.group(1))
            continue

        if current_year is None or label in SKIP_LABELS or not label:
            continue

        value = _to_float(raw)
        if value is None:
            log.debug(f"Пропускаем нечисловое: {label} {current_year} → {raw!r}")
            continue

        # Годовая строка → 1.2.y
        if label == "Год":
            annual.append({
                "year":         current_year,
                "period_label": str(current_year),
                "value":        round(value, 4),
            })
            continue

        # Квартальная строка → 1.2
        q_info = QUARTER_MAP.get(label)
        if q_info is None:
            continue
        start_month, quarter_label = q_info
        quarterly.append({
            "year":         current_year,
            "month":        start_month,
            "period_label": f"{quarter_label} {current_year}",
            "value":        round(value, 4),
        })

    log.info(f"Квартальных записей: {len(quarterly)} | Годовых (1.2.y): {len(annual)}")
    return quarterly, annual


# ── БД ───────────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "realestate"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def get_indicator_id(cur, code: str) -> int:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Индикатор '{code}' не найден в БД.")
    return row[0]


def upsert_quarterly(cur, indicator_id: int, records: list[dict]) -> int:
    rows = [
        (indicator_id, date(r["year"], r["month"], 1), r["period_label"], r["value"], False)
        for r in records
    ]
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


def upsert_annual(cur, indicator_id: int, records: list[dict]) -> int:
    rows = [
        (indicator_id, date(r["year"], 1, 1), r["period_label"], r["value"], False)
        for r in records
    ]
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


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Загрузка 1.2 (квартал) и 1.2.y (год) из Excel Росстата"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Не записывать в БД, только показать что нашли")
    args = parser.parse_args()

    session = _session()

    try:
        url = find_file_url(session)
    except Exception as e:
        log.error(f"Ошибка поиска файла: {e}")
        sys.exit(1)

    try:
        content = download_xlsx(session, url)
    except Exception as e:
        log.error(f"Ошибка загрузки файла: {e}")
        sys.exit(1)

    quarterly, annual = parse_xlsx(content)

    if not quarterly:
        log.error("Не найдено ни одной квартальной записи — проверьте структуру файла.")
        sys.exit(1)

    if args.dry_run:
        log.info("=== DRY RUN ===")
        log.info(f"1.2  — первые 8 квартальных записей:")
        for r in quarterly[:8]:
            log.info(f"  {r['period_label']:12s}  {r['value']:>10.2f} руб./мес.")
        log.info(f"1.2.y — годовые записи:")
        for r in annual:
            log.info(f"  {r['period_label']:6s}  {r['value']:>10.2f} руб./мес.")
        log.info(f"Итого: 1.2={len(quarterly)} кварталов, 1.2.y={len(annual)} лет. БД не тронута.")
        return len(quarterly) + len(annual)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            id_12  = get_indicator_id(cur, CODE_QUARTERLY)
            id_12y = get_indicator_id(cur, CODE_ANNUAL)

            n_q = upsert_quarterly(cur, id_12,  quarterly)
            n_a = upsert_annual   (cur, id_12y, annual)

            log.info(f"Обновляю materialized view ...")
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")

        conn.commit()
        log.info(f"✅ 1.2: {n_q} строк  |  1.2.y: {n_a} строк")
        return n_q + n_a

    except Exception as e:
        log.error(f"Ошибка записи в БД: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
