"""
migration/calc_affordability_fcp.py
Расчёт показателя 5.11 — Доступность жилья (методика ФЦП «Жилище»)

Формула за квартал Q:
    5.11 = (цена_кв_м × площадь_2к) / (зарплата × 2 × 12 × 0.3)

где:
    цена_кв_м   — средневзвешенная цена кв.м квартир на первичном рынке за квартал
                  = SUM(«Продано квартир, руб.») / SUM(«Продано квартир, м2»)
                  за три месяца квартала из файла «Матрица продаж»

    площадь_2к  — среднее значение apartments_area_2k за три месяца квартала (кв. м)

    зарплата    — значение 1.3 нарастающим итогом:
                  Q1 → period_date = YYYY-01-01 (янв-мар)
                  Q2 → period_date = YYYY-04-01 (янв-июн)
                  Q3 → period_date = YYYY-07-01 (янв-сен)
                  Q4 → period_date = YYYY-10-01 (янв-дек)

Результат: лет (период накопления)
Периодичность: quarterly
period_date: первый день первого месяца квартала (Q1→YYYY-01-01 и т.д.)
period_label: 'Q1 YYYY', 'Q2 YYYY', 'Q3 YYYY', 'Q4 YYYY'

Матрица продаж: migration/domrf_data/sales_matrix/Матрица продаж 01.2021-03.2026.xlsx

Запуск:
    python migration/calc_affordability_fcp.py [--dry-run]

Зависимости: psycopg2, python-dotenv, openpyxl
"""

import os
import sys
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
from openpyxl import load_workbook

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv

MATRIX_DIR = Path(__file__).parent / "domrf_data" / "sales_matrix"

MONTH_MAP = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

# Квартал → первый месяц квартала (для period_date)
QUARTER_FIRST_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}

def month_to_quarter(month: int) -> int:
    return (month - 1) // 3 + 1

def quarter_period_date(year: int, quarter: int) -> date:
    return date(year, QUARTER_FIRST_MONTH[quarter], 1)

def quarter_label(year: int, quarter: int) -> str:
    return f"Q{quarter} {year}"

def parse_month_cell(value) -> tuple:
    if not isinstance(value, str):
        return None
    parts = value.strip().split()
    if len(parts) != 2:
        return None
    month_name = parts[0].lower()
    if month_name not in MONTH_MAP:
        return None
    try:
        year = int(parts[1])
    except ValueError:
        return None
    return year, MONTH_MAP[month_name]


def _find_matrix_path() -> Path:
    """Находит актуальный файл матрицы продаж (единственный .xlsx в директории)."""
    files = sorted(MATRIX_DIR.glob("*.xlsx"))
    if not files:
        raise FileNotFoundError(f"Нет .xlsx файлов в {MATRIX_DIR}")
    if len(files) > 1:
        log.warning(f"Найдено {len(files)} файлов матрицы, используем последний: {files[-1].name}")
    return files[-1]


def load_matrix_prices() -> dict:
    """
    Читает матрицу продаж, возвращает средневзвешенную цену кв.м по кварталам:
    {(year, quarter): price_per_sqm}
    """
    matrix_path = _find_matrix_path()
    log.info(f"Читаем матрицу продаж: {matrix_path}")
    wb = load_workbook(matrix_path, read_only=True, data_only=True)
    ws = wb.active

    headers = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    col_month = col_rubles = col_sqm = None
    for i, h in enumerate(headers):
        if h == "Месяц" and col_month is None:
            col_month = i
        if h == "Продано квартир, руб.":
            col_rubles = i
        if h == "Продано квартир, м2":
            col_sqm = i

    if any(c is None for c in [col_month, col_rubles, col_sqm]):
        raise ValueError(f"Не найдены столбцы: Месяц={col_month}, руб.={col_rubles}, м2={col_sqm}")

    log.info(f"Столбцы: Месяц={col_month}, руб.={col_rubles}, м2={col_sqm}")

    quarters = defaultdict(lambda: {"rubles": 0.0, "sqm": 0.0})
    rows_read = rows_skipped = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        parsed = parse_month_cell(row[col_month])
        if parsed is None:
            rows_skipped += 1
            continue
        year, month = parsed
        quarter = month_to_quarter(month)
        rubles = row[col_rubles]
        sqm    = row[col_sqm]
        if not rubles or not sqm:
            rows_read += 1
            continue
        try:
            quarters[(year, quarter)]["rubles"] += float(rubles)
            quarters[(year, quarter)]["sqm"]    += float(sqm)
        except (TypeError, ValueError):
            rows_skipped += 1
            continue
        rows_read += 1

    wb.close()
    log.info(f"Строк обработано: {rows_read}, пропущено: {rows_skipped}")

    prices = {}
    for (year, quarter), agg in sorted(quarters.items()):
        if agg["sqm"] <= 0:
            log.warning(f"Q{quarter} {year}: площадь = 0, пропускаем")
            continue
        prices[(year, quarter)] = agg["rubles"] / agg["sqm"]
        log.info(f"Q{quarter} {year}: цена кв.м = {prices[(year, quarter)]:,.0f} руб.")

    return prices


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_indicator_id(cur, code: str) -> int:
    cur.execute("SELECT id FROM indicators WHERE code = %s", (code,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Indicator '{code}' not found in DB")
    return row[0]


def load_salary(cur, indicator_id: int) -> dict:
    """
    Возвращает {(year, quarter): salary} из данных 1.3 (нарастающий итог).
    period_date = первый день первого месяца квартала:
        Q1 → 01-01, Q2 → 04-01, Q3 → 07-01, Q4 → 10-01
    """
    cur.execute(
        """
        SELECT period_date, value
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    result = {}
    for period_date, value in cur.fetchall():
        month = period_date.month
        if month in (1, 4, 7, 10):
            quarter = month_to_quarter(month)
            result[(period_date.year, quarter)] = float(value)
    return result


def load_area_2k(cur, indicator_id: int) -> dict:
    """
    Возвращает среднее apartments_area_2k по кварталам:
    {(year, quarter): avg_area}
    Берём среднее за три месяца квартала.
    """
    cur.execute(
        """
        SELECT period_date, value
        FROM data_points
        WHERE indicator_id = %s AND value IS NOT NULL
        ORDER BY period_date
        """,
        (indicator_id,),
    )
    by_quarter = defaultdict(list)
    for period_date, value in cur.fetchall():
        quarter = month_to_quarter(period_date.month)
        by_quarter[(period_date.year, quarter)].append(float(value))

    return {
        key: sum(vals) / len(vals)
        for key, vals in by_quarter.items()
    }


def main():
    log.info("=== Расчёт 5.11 — Доступность жилья (методика ФЦП «Жилище») ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    # 1. Цены из матрицы продаж
    prices = load_matrix_prices()

    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                id_salary = get_indicator_id(cur, "1.3")
                id_area   = get_indicator_id(cur, "apartments_area_2k")
                id_out    = get_indicator_id(cur, "5.11")

                # 2. Зарплата (нарастающий итог)
                salary = load_salary(cur, id_salary)
                log.info(f"1.3 — зарплата: {len(salary)} квартальных точек")

                # 3. Средняя площадь 2к по кварталам
                area_2k = load_area_2k(cur, id_area)
                log.info(f"apartments_area_2k — площадь: {len(area_2k)} квартальных точек")

                # 4. Пересечение кварталов
                common = sorted(
                    set(prices) & set(salary)
                )
                log.info(f"Совпадающих кварталов: {len(common)}")

                rows = []
                for (year, quarter) in common:
                    price  = prices[(year, quarter)]      # руб./кв.м
                    area   = area_2k.get((year, quarter), 58.0)     # кв.м, фолбэк 58 для 2021
                    sal    = salary[(year, quarter)]      # руб./мес.

                    # Стоимость квартиры
                    flat_cost = price * area              # руб.

                    # Годовой объём накоплений: 2 работающих × 12 мес. × 30% зарплаты
                    annual_savings = sal * 2 * 12 * 0.3  # руб./год

                    value = round(flat_cost / annual_savings, 4)

                    pd_   = quarter_period_date(year, quarter)
                    label = quarter_label(year, quarter)

                    log.info(
                        f"{label}: цена={price:,.0f} руб/кв.м, "
                        f"площадь={area:.1f} кв.м, "
                        f"зарплата={sal:,.0f} руб/мес "
                        f"→ {value:.2f} лет"
                    )

                    rows.append((
                        id_out,
                        pd_,
                        label,
                        value,
                        False,
                        datetime.now(),
                    ))

                if not rows:
                    log.error("Нет данных для записи — проверьте пересечение периодов")
                    return

                log.info(f"Итого рассчитано: {len(rows)} точек")

                if DRY_RUN:
                    log.info("DRY RUN — пропускаем запись в БД")
                    return

                execute_values(
                    cur,
                    """
                    INSERT INTO data_points
                        (indicator_id, period_date, period_label, value, is_preliminary, created_at)
                    VALUES %s
                    ON CONFLICT (indicator_id, period_date)
                    DO UPDATE SET
                        value          = EXCLUDED.value,
                        period_label   = EXCLUDED.period_label,
                        is_preliminary = EXCLUDED.is_preliminary
                    """,
                    rows,
                )
                log.info(f"Записано/обновлено в data_points: {cur.rowcount} строк")

                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e} (данные записаны)")

        log.info("=== Готово. Проверьте: http://localhost:3000/chart.html?code=5.11 ===")
        log.info("Ожидаемый диапазон: ~4–8 лет")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
