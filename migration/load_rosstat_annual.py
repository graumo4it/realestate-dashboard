"""
Загрузка официальных годовых значений Росстата из Excel-файлов.

Использование:
    source venv/bin/activate
    cd migration
    python load_rosstat_annual.py --file1 /path/to/urov_10kv.xlsx [--file2 /path/to/zp.xlsx]

Что делает:
  - Читает строки «Год» из Excel Росстата по доходам (1.2) и зарплате (1.3)
  - Сохраняет их в indicators 1.2.y и 1.3.y (periodicity='annual')
  - Обновляет materialized view

Excel-структура (1.2, лист СДД_РФ):
  Строки чередуются: «YYYY год», «1 квартал», «2 квартал», «3 квартал», «4 квартал», «Год».
  Значение — столбец B (index 1), единица — руб. / мес.

Excel-структура (1.3, лист СЗП_РФ или аналогичный):
  Такая же, но значение — среднемесячная зарплата в руб.
"""

import argparse
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

import openpyxl
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).parent.parent / "parsers"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "realestate"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def parse_income_xlsx(path: str) -> list[dict]:
    """
    Парсит Excel Росстата «Среднедушевые денежные доходы».
    Возвращает записи только для строк «Год».
    """
    wb = openpyxl.load_workbook(path, data_only=True)

    # Ищем лист с данными (обычно 'СДД_РФ' или второй лист)
    sheet_names = wb.sheetnames
    ws = None
    for name in sheet_names:
        if name not in ("Содержание",):
            ws = wb[name]
            break
    if ws is None:
        ws = wb.active
    log.info(f"Парсим лист '{ws.title}' из {path}")

    records = []
    current_year = None

    for row in ws.iter_rows(values_only=True):
        label = str(row[0]).strip() if row[0] is not None else ""
        value = row[1]

        # Определяем год
        year_match = re.match(r"^(\d{4})\s*год", label)
        if year_match:
            current_year = int(year_match.group(1))
            continue

        # Строка «Год» — это то, что нам нужно
        if label == "Год" and current_year is not None and value is not None:
            try:
                fval = float(str(value).replace(",", ".").replace(" ", "").replace("\xa0", ""))
            except (ValueError, TypeError):
                log.warning(f"  Пропускаем {current_year}: не удалось распарсить значение {value!r}")
                continue
            records.append({
                "indicator_code": "1.2.y",
                "period_date": date(current_year, 1, 1),
                "period_label": str(current_year),
                "value": fval,
            })
            log.info(f"  1.2.y  {current_year}: {fval:,.1f}")

    return records


def parse_salary_xlsx(path: str) -> list[dict]:
    """
    Парсит Excel Росстата «Среднемесячная номинальная начисленная заработная плата».

    Структура файла (tab9-zpl_*.xlsx):
      - Несколько листов с разными периодами («2012-2017», «с 2018»)
      - Строка 3: заголовки столбцов — годы (2012, 2013, … или «2022 1)» с сноской)
      - Строка 4: «Российская Федерация» — значения по годам
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    records = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 4:
            continue

        # Ищем строку с заголовками-годами (обычно строка 3, индекс 2)
        year_row_idx = None
        year_cols: dict[int, int] = {}  # col_index -> year
        for idx, row in enumerate(rows[:6]):
            for col_i, cell in enumerate(row):
                if cell is None:
                    continue
                # Заголовок года может быть числом (2018) или строкой «2022 1)»
                year_match = re.match(r"(\d{4})", str(cell).strip())
                if year_match:
                    year = int(year_match.group(1))
                    if 2000 <= year <= 2030:
                        year_cols[col_i] = year
                        year_row_idx = idx
        if not year_cols:
            log.warning(f"  Лист '{sheet_name}': не найдены столбцы с годами, пропускаем")
            continue

        log.info(f"  Лист '{sheet_name}': годы {sorted(year_cols.values())}")

        # Ищем строку «Российская Федерация»
        for row in rows[year_row_idx + 1:]:
            label = str(row[0]).strip() if row[0] is not None else ""
            if not re.match(r"Российская\s+Федерация", label):
                continue

            for col_i, year in year_cols.items():
                cell_val = row[col_i] if col_i < len(row) else None
                if cell_val is None:
                    continue
                try:
                    fval = float(str(cell_val).replace(",", ".").replace(" ", "").replace("\xa0", ""))
                except (ValueError, TypeError):
                    log.warning(f"  Пропускаем {year}: {cell_val!r}")
                    continue
                records.append({
                    "indicator_code": "1.3.y",
                    "period_date": date(year, 1, 1),
                    "period_label": str(year),
                    "value": fval,
                })
                log.info(f"  1.3.y  {year}: {fval:,.1f}")
            break  # нашли строку РФ, дальше не идём

    return records


def upsert(conn, records: list[dict]) -> int:
    if not records:
        return 0
    with conn.cursor() as cur:
        rows = []
        for r in records:
            cur.execute("SELECT id FROM indicators WHERE code = %s", (r["indicator_code"],))
            row = cur.fetchone()
            if row is None:
                log.warning(f"Индикатор {r['indicator_code']} не найден в БД, пропускаем")
                continue
            rows.append((row[0], r["period_date"], r["period_label"], r["value"]))

        if rows:
            execute_values(cur, """
                INSERT INTO data_points (indicator_id, period_date, period_label, value)
                VALUES %s
                ON CONFLICT (indicator_id, period_date)
                DO UPDATE SET value = EXCLUDED.value,
                              period_label = EXCLUDED.period_label
            """, rows)
        conn.commit()
    return len(rows)


def refresh_view(conn):
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
        conn.commit()
    log.info("Materialized view обновлён")


def main():
    parser = argparse.ArgumentParser(description="Загрузка годовых данных Росстата в БД")
    parser.add_argument("--file1", required=True,
                        help="Excel Росстата с доходами населения (для 1.2.y)")
    parser.add_argument("--file2", default=None,
                        help="Excel Росстата со средней зарплатой (для 1.3.y, опционально)")
    args = parser.parse_args()

    records = []

    log.info(f"=== Загрузка 1.2.y из {args.file1} ===")
    records += parse_income_xlsx(args.file1)

    if args.file2:
        log.info(f"=== Загрузка 1.3.y из {args.file2} ===")
        records += parse_salary_xlsx(args.file2)
    else:
        log.info("--file2 не передан, 1.3.y пропускаем")

    if not records:
        log.warning("Не найдено ни одной строки «Год»")
        sys.exit(1)

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        n = upsert(conn, records)
        log.info(f"Загружено строк: {n}")
        refresh_view(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    main()
