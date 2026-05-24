"""
migration/migrate_matrix_projects.py

Рассчитывает показатель 3.6 — доля топ-5 застройщиков (по группе компаний)
в объёме возводимого жилья из файлов «Матрица проектов» (*.xlsb).

Использование:
    python migration/migrate_matrix_projects.py

Структура папки:
    migration/domrf_data/matrix_projects/
        Матрица_проектов_15_04_2026.xlsb
        Матрица_проектов_15_05_2026.xlsb
        ...

Логика:
    - Фильтр: «Статус корпуса» == 'Строится'
    - Числитель: сумма «Жилая площадь» топ-5 групп компаний
    - Знаменатель: сумма «Жилая площадь» всех строящихся корпусов
    - Результат: % (0–100)
    - Перед загрузкой: DELETE все существующие точки по indicator code='3.6'
    - period_date: первый день месяца из имени файла (напр. 15_04_2026 → 2026-04-01)
    - period_label: 'Апрель 2026'
    - period_type: point_in_time, periodicity: monthly
"""

import os
import re
import sys
from pathlib import Path
from datetime import date

import psycopg2
from dotenv import load_dotenv
from pyxlsb import open_workbook

load_dotenv()

MONTHS_RU = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель',
    5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
    9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь',
}

DATA_DIR = Path(__file__).parent / 'domrf_data' / 'matrix_projects'
INDICATOR_CODE = '3.6'


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ.get('DB_PORT', 5432),
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    )


def parse_date_from_filename(filename: str) -> object:
    """Извлекает дату из имени файла.
    Поддерживает форматы:
      - 'Матрица проектов 15.04.2026.xlsb'  → DD.MM.YYYY
      - 'Матрица_проектов_15_04_2026.xlsb'  → DD_MM_YYYY
    """
    m = re.search(r'(\d{2})[._](\d{2})[._](\d{4})', filename)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(year, month, 1)


def calc_top5_share(filepath: Path) -> float | None:
    """
    Читает xlsb и возвращает долю топ-5 групп компаний в % или None при ошибке.
    """
    groups: dict[str, float] = {}
    total = 0.0

    with open_workbook(str(filepath)) as wb:
        with wb.get_sheet(1) as sheet:
            headers = None
            for row in sheet.rows():
                vals = [c.v for c in row]
                if headers is None:
                    headers = vals
                    try:
                        # Новые файлы: 'Статус корпуса', старые (2022–2023): 'статус'
                        headers_lower = [h.lower() if h else '' for h in headers]
                        if 'статус корпуса' in headers_lower:
                            idx_status = headers_lower.index('статус корпуса')
                        elif 'статус' in headers_lower:
                            idx_status = headers_lower.index('статус')
                        else:
                            raise ValueError("Статус корпуса / статус")
                        idx_area = headers.index('Жилая площадь')
                        idx_group = headers.index('Группа компаний')
                    except ValueError as e:
                        print(f"  Ошибка: столбец не найден — {e}")
                        return None
                    continue

                status = vals[idx_status] if idx_status < len(vals) else None
                if not status or status.strip().lower() != 'строится':
                    continue

                area = vals[idx_area] if idx_area < len(vals) else None
                group = vals[idx_group] if idx_group < len(vals) else None

                if not area or not group:
                    continue

                try:
                    area = float(area)
                except (TypeError, ValueError):
                    continue

                groups[group] = groups.get(group, 0.0) + area
                total += area

    if total == 0:
        print("  Предупреждение: суммарная жилая площадь = 0")
        return None

    top5_area = sum(sorted(groups.values(), reverse=True)[:5])
    return round(top5_area / total * 100, 4)


def main():
    if not DATA_DIR.exists():
        print(f"Папка не найдена: {DATA_DIR}")
        print("Создайте migration/domrf_data/matrix_projects/ и положите туда xlsb-файлы.")
        sys.exit(1)

    files = sorted(f for f in DATA_DIR.glob('*.xlsb') if not f.name.startswith('~$'))
    if not files:
        print(f"Нет xlsb-файлов в {DATA_DIR}")
        sys.exit(1)

    conn = get_db_conn()
    cur = conn.cursor()

    # Получаем indicator_id
    cur.execute("SELECT id FROM indicators WHERE code = %s", (INDICATOR_CODE,))
    row = cur.fetchone()
    if not row:
        print(f"Индикатор {INDICATOR_CODE} не найден в БД")
        sys.exit(1)
    indicator_id = row[0]

    # Удаляем все существующие данные по 3.6
    cur.execute("DELETE FROM data_points WHERE indicator_id = %s", (indicator_id,))
    deleted = cur.rowcount
    print(f"Удалено существующих точек: {deleted}")

    inserted = 0
    for filepath in files:
        period_date = parse_date_from_filename(filepath.name)
        if not period_date:
            print(f"  Пропуск (не удалось распознать дату): {filepath.name}")
            continue

        print(f"Обрабатываю {filepath.name} → {period_date} ...", end=' ')
        share = calc_top5_share(filepath)

        if share is None:
            print("пропущено (нет данных)")
            continue

        label = f"{MONTHS_RU[period_date.month]} {period_date.year}"
        print(f"{share:.2f}%")

        cur.execute("""
            INSERT INTO data_points (indicator_id, period_date, period_label, value, is_preliminary)
            VALUES (%s, %s, %s, %s, false)
            ON CONFLICT (indicator_id, period_date) DO UPDATE
                SET value = EXCLUDED.value,
                    period_label = EXCLUDED.period_label
        """, (indicator_id, period_date, label, share))
        inserted += 1

    # Обновляем materialized view
    print("\nОбновляю materialized view ...", end=' ')
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY data_points_with_dynamics")
    print("готово")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nГотово. Записано точек: {inserted}")
    print(f"Upserted: {inserted} rows")


if __name__ == '__main__':
    main()
