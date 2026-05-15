"""
migration/calc_affordability.py
Расчёт показателя 5.10 — Доступность жилья (отношение зарплаты к стоимости жилья)

Формула:
    5.10 = зарплата (1.3) / средневзвешенная цена кв.м по матрице продаж

Зарплата (1.3):
    Данные нарастающим итогом с начала года. Для каждого квартала берём
    соответствующую накопленную точку:
        Q1 → period_label содержит 'янв' и 'мар' (или period_date = YYYY-03-01)
        Q2 → period_date = YYYY-06-01
        Q3 → period_date = YYYY-09-01
        Q4 → period_date = YYYY-12-01

Средневзвешенная цена кв.м:
    = SUM(«Продано квартир, руб.») / SUM(«Продано квартир, м2»)
    за три месяца квартала из файла migration/domrf_data/Матрица продаж 01.2021-03.2026.xlsx

Результат:
    Безразмерный коэффициент (руб./мес. / руб./кв.м = кв.м/мес.)
    period_date = первый день последнего месяца квартала:
        Q1 → YYYY-03-01, Q2 → YYYY-06-01, Q3 → YYYY-09-01, Q4 → YYYY-12-01
    period_label = 'Q1 YYYY', 'Q2 YYYY', 'Q3 YYYY', 'Q4 YYYY'
    periodicity = 'quarterly'

Запуск:
    python migration/calc_affordability.py [--dry-run]

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

# Путь к файлу матрицы продаж
MATRIX_PATH = Path(__file__).parent / "domrf_data" / "sales_matrix" / "Матрица продаж 01.2021-03.2026.xlsx"

# Месяц → номер
MONTH_MAP = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

# Месяц → квартал
def month_to_quarter(month: int) -> int:
    return (month - 1) // 3 + 1

# period_date для квартала = первый день последнего месяца квартала
QUARTER_LAST_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}

def quarter_period_date(year: int, quarter: int) -> date:
    return date(year, QUARTER_LAST_MONTH[quarter], 1)

def quarter_label(year: int, quarter: int) -> str:
    return f"Q{quarter} {year}"


def parse_month_cell(value) -> tuple[int, int] | None:
    """Парсит 'Январь 2026' → (2026, 1). Возвращает None при ошибке."""
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


def load_matrix() -> dict:
    """
    Читает матрицу продаж и возвращает агрегированные данные по кварталам:
    {(year, quarter): {'rubles': float, 'sqm': float}}
    """
    if not MATRIX_PATH.exists():
        raise FileNotFoundError(f"Файл матрицы не найден: {MATRIX_PATH}")

    log.info(f"Читаем матрицу продаж: {MATRIX_PATH}")
    wb = load_workbook(MATRIX_PATH, read_only=True, data_only=True)
    ws = wb.active

    # Определяем индексы нужных столбцов по заголовку
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
        raise ValueError(
            f"Не найдены столбцы: Месяц={col_month}, "
            f"руб.={col_rubles}, м2={col_sqm}"
        )

    log.info(f"Столбцы: Месяц={col_month}, руб.={col_rubles}, м2={col_sqm}")

    # Агрегируем по кварталам
    quarters: dict = defaultdict(lambda: {"rubles": 0.0, "sqm": 0.0})
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

        # Пропускаем строки с нулями или None (нет продаж)
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
    log.info(f"Кварталов с данными: {len(quarters)}")
    return dict(quarters)


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
    period_date = первый день последнего месяца квартала:
        Q1 → 03-01, Q2 → 06-01, Q3 → 09-01, Q4 → 12-01
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
        # Проверяем что это последний месяц квартала
        if month in (1, 4, 7, 10):
            quarter = month_to_quarter(month)
            result[(period_date.year, quarter)] = float(value)
    return result


def main():
    log.info("=== Расчёт 5.10 — Доступность жилья (зарплата / цена кв.м) ===")
    if DRY_RUN:
        log.info("Режим DRY RUN — данные в БД не записываются")

    # 1. Загружаем матрицу
    matrix = load_matrix()

    # 2. Считаем средневзвешенную цену по кварталам
    prices = {}
    for (year, quarter), agg in sorted(matrix.items()):
        if agg["sqm"] <= 0:
            log.warning(f"Q{quarter} {year}: площадь = 0, пропускаем")
            continue
        price = agg["rubles"] / agg["sqm"]
        prices[(year, quarter)] = price
        log.info(
            f"Q{quarter} {year}: продано {agg['rubles']:,.0f} руб., "
            f"{agg['sqm']:,.1f} кв.м → цена {price:,.0f} руб/кв.м"
        )

    # 3. Загружаем зарплату из БД
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                id_salary = get_indicator_id(cur, "1.3")
                id_out    = get_indicator_id(cur, "5.10")

                salary = load_salary(cur, id_salary)
                log.info(f"1.3 — зарплата: {len(salary)} квартальных точек")
                for (y, q), v in sorted(salary.items()):
                    log.info(f"  Q{q} {y}: {v:,.0f} руб/мес")

                # 4. Считаем 5.10
                common = sorted(set(prices) & set(salary))
                log.info(f"Совпадающих кварталов: {len(common)}")

                rows = []
                for (year, quarter) in common:
                    sal   = salary[(year, quarter)]
                    price = prices[(year, quarter)]
                    value = round(sal / price, 4)

                    pd_   = quarter_period_date(year, quarter)
                    label = quarter_label(year, quarter)

                    log.info(
                        f"{label}: зарплата={sal:,.0f}, цена кв.м={price:,.0f} "
                        f"→ коэф. доступности={value:.4f}"
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

                # 5. Upsert
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

                # 6. Refresh materialized view
                try:
                    log.info("Обновляем materialized view...")
                    cur.execute(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics"
                    )
                    log.info("Materialized view обновлён")
                except Exception as e:
                    log.warning(f"Не удалось обновить view: {e} (данные записаны)")

        log.info("=== Готово. Проверьте: http://localhost:3000/chart.html?code=5.10 ===")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
