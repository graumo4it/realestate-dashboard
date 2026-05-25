"""
update_indicator_status.py
──────────────────────────
Обновляет два столбца в indicator_update_map.xlsx:
  • «Актуальный период» — человекочитаемое обозначение MAX(period_date) из БД
                          (например «апрель 2026», «1 кв. 2026», «2025»)
  • «Статус»            — сравнение актуального периода с ожидаемым по расписанию:
                          ✅ Актуально / ⏳ Ожидается / ⚠️ Просрочено / ❌ Нет обновления

Запуск: python migration/update_indicator_status.py
        (из корня проекта, venv активирован)

Логика статуса:
  1. Вычислить «ожидаемый период» для каждого индикатора:
       Ежемесячный  → первый день прошлого месяца (если сегодня ≥ run_day)
                      или первый день позапрошлого месяца (если сегодня < run_day)
       Ежеквартальный → начало последнего завершённого квартала, данные которого
                        должны быть доступны по расписанию
       Ежегодный    → 1 января прошлого года (если сегодня ≥ run_date этого года)
                      или 1 января позапрошлого года (если run_date ещё не наступил)
  2. Сравнить MAX(period_date) с ожидаемым:
       ≥ ожидаемого       → ✅ Актуально
       < ожидаемого И run_date ещё не прошёл в этом цикле → ⏳ Ожидается
       < ожидаемого И run_date уже прошёл                 → ⚠️ Просрочено
       нет данных / парсер отключён                       → ❌ Нет обновления
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

load_dotenv(Path(__file__).parent.parent / ".env")

EXCEL_PATH = Path(__file__).parent.parent / "indicator_update_map.xlsx"

# ── Цвета статусов ─────────────────────────────────────────────────────────────
CLR_OK       = "C6EFCE"   # зелёный  — актуально
CLR_WAIT     = "FFEB9C"   # жёлтый   — ожидается
CLR_OVERDUE  = "FFC7CE"   # красный  — просрочено
CLR_DISABLED = "F2F2F2"   # серый    — нет обновления
CLR_HEADER   = "4472C4"   # синий    — заголовок

MONTHS_RU = [
    "январь","февраль","март","апрель","май","июнь",
    "июль","август","сентябрь","октябрь","ноябрь","декабрь",
]
MONTHS_RU_GEN = [
    "января","февраля","марта","апреля","мая","июня",
    "июля","августа","сентября","октября","ноября","декабря",
]


# ── Расписание ─────────────────────────────────────────────────────────────────
#
# Каждая запись описывает параметры расписания для группы индикаторов.
# Поля:
#   codes        — список кодов индикаторов (str), которые обновляются этим job'ом
#   periodicity  — 'monthly' | 'quarterly' | 'annual'
#   run_day      — день месяца запуска (для monthly и quarterly/annual в нужном месяце)
#   run_months   — список месяцев запуска (только для quarterly и annual)
#                  None → запускается каждый месяц (monthly)
#   disabled     — True если индикатор намеренно отключён

SCHEDULE = [
    # ── Ежемесячные ────────────────────────────────────────────────────────────
    {   # CBR primary: 6.1–6.27
        # ЦБ публикует данные в последний день отчётного месяца (лаг 1 мес.):
        # март → 30 апреля; парсер 1 мая забирает мартовские данные.
        "codes": [
            "6.1","6.2","6.3","6.4","6.5","6.6",
            "6.7","6.8","6.9","6.10","6.11","6.12",
            "6.13","6.14","6.15","6.16","6.17","6.18",
            "6.19","6.20","6.21","6.22","6.23","6.24",
            "6.25","6.26","6.27",
        ],
        "periodicity": "monthly",
        "run_day": 1,
        "run_months": None,
        "lag_months": 1,   # ЦБ публикует данные за N-1 месяц в конце месяца N
    },
    {   # DomRF Web: 3.1–3.4, 3.17–3.19 + расчётные 3.5
        "codes": ["3.1","3.2","3.3","3.4","3.5","3.17","3.18","3.19"],
        "periodicity": "monthly",
        "run_day": 5,
        "run_months": None,
    },
    {   # CBR IHC + субсидии: 6.36–6.87
        # Тот же лаг ЦБ: мартовские данные по ИЖС и субсидиям → конец апреля.
        "codes": [
            "6.36","6.37","6.38","6.39","6.40","6.41","6.42","6.43","6.44","6.45",
            "6.70","6.71","6.72","6.73","6.74","6.75",
            "6.76","6.77","6.78","6.79","6.80","6.81",
            "6.82","6.83","6.84","6.85","6.86","6.87",
        ],
        "periodicity": "monthly",
        "run_day": 7,
        "run_months": None,
        "lag_months": 1,   # ЦБ публикует данные за N-1 месяц в конце месяца N
    },
    {   # DomRF оркестратор + расчётные: 5.x, 4.x, uc_*, apartments_*, etc.
        "codes": [
            "3.6","3.7","4.1","4.8","4.9",
            "5.3","5.8","5.9","5.9.ma12","5.10","5.11",
            "5.20","5.21","5.22","5.22.ma12",
            "apt_area","apt_budget","sales_apt_sqm",
            "mm_price","mm_budget",
            "apartments_count_1k","apartments_count_2k","apartments_count_3k",
            "apartments_count_4k","apartments_count_total",
            "apartments_area_1k","apartments_area_2k","apartments_area_3k",
            "apartments_area_4k","apartments_area_total",
            "apartments_share_1k","apartments_share_2k","apartments_share_3k","apartments_share_4k",
            "uc_absorption_active","uc_absorption_total",
            "uc_area_active","uc_area_total","uc_dev_activity",
            "uc_new_active","uc_new_total",
            "uc_new_vs_input_active","uc_new_vs_input_total",
            "uc_new_vs_sales_active","uc_new_vs_sales_total",
            "uc_sold_vs_ready","uc_stock_years_active","uc_stock_years_total",
        ],
        "periodicity": "monthly",
        "run_day": 20,
        "run_months": None,
    },
    {   # Rosstat ежемесячный: 2.1/2.2/2.3 + расчётные 2.6/2.7/2.8
        "codes": ["2.1","2.2","2.3","2.6","2.7","2.8"],
        "periodicity": "monthly",
        "run_day": 20,
        "run_months": None,
    },
    # ── Ежеквартальные ─────────────────────────────────────────────────────────
    {   # Квартальные Rosstat + Росреестр + доходы населения
        # Запускаются 1 фев / 1 май / 1 авг / 1 ноя
        "codes": ["1.2","1.3","4.4","4.4.1","4.4.2","4.4.3",
                  "4.5","4.5.1","4.5.2","4.5.3","4.5.4","5.1"],
        "periodicity": "quarterly",
        "run_day": 1,
        "run_months": [2, 5, 8, 11],
    },
    # ── Ежегодные ──────────────────────────────────────────────────────────────
    {   # Companion годовые: 1.2.y + 1.3.y — 1 февраля
        "codes": ["1.2.y","1.3.y"],
        "periodicity": "annual",
        "run_day": 1,
        "run_months": [2],
    },
    {   # Население + девелоперская активность — 15 марта
        "codes": ["1.1","3.7","5.3"],
        "periodicity": "annual",
        "run_day": 15,
        "run_months": [3],
    },
    {   # Жилищный фонд (Росстат годовой) — 5 июня
        "codes": [
            "2.9","2.10","2.11","2.12","2.13",
            "5.12.33","5.12.38","5.13.33","5.13.38",
            "5.14.33","5.14.38","5.15.33","5.15.38",
        ],
        "periodicity": "annual",
        "run_day": 5,
        "run_months": [6],
    },
    # ── Отключённые ────────────────────────────────────────────────────────────
    {
        "codes": ["2.13.ext"],
        "periodicity": "monthly",
        "run_day": None,
        "run_months": None,
        "disabled": True,
    },
]

# Индикаторы без обновления (Домклик и прочие legacy)
NO_UPDATE_CODES = {
    "3.14","3.16","5.4",
    "6.28","6.29","6.30","6.31","6.32","6.33","6.34","6.35",
}

# Плоский маппинг code → schedule entry
_CODE_SCHEDULE: dict[str, dict] = {}
for entry in SCHEDULE:
    for code in entry["codes"]:
        _CODE_SCHEDULE[code] = entry


# ── БД ─────────────────────────────────────────────────────────────────────────

def _connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def fetch_last_dates(conn) -> dict[str, date | None]:
    """Возвращает {code: MAX(period_date)} для всех индикаторов."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.code, MAX(dp.period_date)
            FROM indicators i
            LEFT JOIN data_points dp ON dp.indicator_id = i.id
            GROUP BY i.code
        """)
        return {row[0]: row[1] for row in cur.fetchall()}


# ── Ожидаемый период ───────────────────────────────────────────────────────────

def _prev_month_start(ref: date) -> date:
    """Первый день месяца, предшествующего ref."""
    if ref.month == 1:
        return date(ref.year - 1, 12, 1)
    return date(ref.year, ref.month - 1, 1)


def _months_back(ref: date, n: int) -> date:
    """Первый день месяца на n месяцев раньше ref."""
    total = ref.year * 12 + (ref.month - 1) - n
    y, m = divmod(total, 12)
    return date(y, m + 1, 1)


def _quarter_start(d: date) -> date:
    """Начало квартала, в котором находится дата d."""
    q_start_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, q_start_month, 1)


def _prev_quarter_start(ref: date) -> date:
    """Начало предыдущего квартала от ref."""
    qs = _quarter_start(ref)
    return _months_back(qs, 3)


def get_expected_period(sched: dict, today: date) -> date | None:
    """
    Вычисляет ожидаемый MAX(period_date) для индикатора по его расписанию.

    Возвращает None если невозможно определить (disabled или неизвестная периодичность).
    """
    if sched.get("disabled"):
        return None

    periodicity = sched["periodicity"]
    run_day = sched["run_day"]
    run_months = sched.get("run_months")  # None → ежемесячный

    if periodicity == "monthly":
        # lag_months — дополнительный лаг публикации источника (по умолчанию 0).
        # Например, ЦБ РФ публикует данные за месяц N в конце месяца N+1 (lag_months=1):
        # мартовские данные выходят 30 апреля, поэтому 1 мая ожидаем март, а не апрель.
        lag = sched.get("lag_months", 0)
        if today.day >= run_day:
            return _months_back(today, 1 + lag)
        else:
            return _months_back(today, 2 + lag)

    elif periodicity == "quarterly":
        # run_months — месяцы запуска [2,5,8,11] для quarterly_rosstat
        # Каждый запуск публикует данные за предыдущий квартал.
        assert run_months, "quarterly требует run_months"

        # Находим последний прошедший run_date (в этом или прошлом году)
        last_run_date = None
        for year in [today.year, today.year - 1]:
            for month in sorted(run_months, reverse=True):
                candidate = date(year, month, run_day)
                if candidate <= today:
                    if last_run_date is None or candidate > last_run_date:
                        last_run_date = candidate
                    break

        if last_run_date is None:
            return _prev_quarter_start(_prev_quarter_start(today))

        # Ожидаемый период = квартал, предшествующий кварталу run_date
        return _prev_quarter_start(last_run_date)

    elif periodicity == "annual":
        # run_months — месяц запуска (одноэлементный список, напр. [3])
        assert run_months and len(run_months) == 1
        run_month = run_months[0]
        run_date_this_year = date(today.year, run_month, run_day)

        if today >= run_date_this_year:
            # run_date уже прошёл → ожидаем данные за прошлый год
            return date(today.year - 1, 1, 1)
        else:
            # run_date ещё не наступил → ожидаем данные за позапрошлый год
            return date(today.year - 2, 1, 1)

    return None


def get_run_date_this_cycle(sched: dict, today: date) -> date | None:
    """
    Возвращает дату последнего или следующего запуска в текущем «цикле».
    Используется для определения статуса ⏳ vs ⚠️.
    """
    if sched.get("disabled"):
        return None

    periodicity = sched["periodicity"]
    run_day = sched["run_day"]
    run_months = sched.get("run_months")

    if periodicity == "monthly":
        return date(today.year, today.month, run_day)

    elif periodicity == "quarterly":
        assert run_months
        for month in sorted(run_months, reverse=True):
            candidate = date(today.year, month, run_day)
            if candidate <= today:
                return candidate
        # До первого запуска в этом году
        prev_year_last = date(today.year - 1, max(run_months), run_day)
        return prev_year_last

    elif periodicity == "annual":
        assert run_months and len(run_months) == 1
        run_date = date(today.year, run_months[0], run_day)
        if today >= run_date:
            return run_date
        return date(today.year - 1, run_months[0], run_day)

    return None


# ── Статус ─────────────────────────────────────────────────────────────────────

def compute_status(
    code: str,
    actual: date | None,
    today: date,
) -> tuple[str, str]:
    """
    Возвращает (статус_текст, hex_цвет).
    """
    if code in NO_UPDATE_CODES:
        return "❌ Нет обновления", CLR_DISABLED

    sched = _CODE_SCHEDULE.get(code)
    if sched is None:
        # Код не в расписании — неизвестен
        return "❓ Неизвестно", CLR_DISABLED

    if sched.get("disabled"):
        return "⛔ Отключён", CLR_DISABLED

    if actual is None:
        return "❌ Нет данных", CLR_DISABLED

    expected = get_expected_period(sched, today)
    if expected is None:
        return "❌ Нет данных", CLR_DISABLED

    if actual >= expected:
        return "✅ Актуально", CLR_OK

    # actual < expected — смотрим, прошёл ли run_date в этом цикле
    run_date = get_run_date_this_cycle(sched, today)
    if run_date is None or today < run_date:
        return "⏳ Ожидается", CLR_WAIT
    else:
        return "⚠️ Просрочено", CLR_OVERDUE


# ── Форматирование периода ──────────────────────────────────────────────────────

def format_period(d: date | None, periodicity: str) -> str:
    """Человекочитаемое обозначение периода."""
    if d is None:
        return "—"
    if periodicity == "Ежемесячно":
        return f"{MONTHS_RU[d.month - 1]} {d.year}"
    elif periodicity == "Ежеквартально":
        q = (d.month - 1) // 3 + 1
        return f"{q} кв. {d.year}"
    else:  # Ежегодно
        return str(d.year)


# ── Excel ───────────────────────────────────────────────────────────────────────

HEADER_ROW = 2   # строка заголовков (1-based)
DATA_START  = 3  # первая строка данных


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _find_or_create_col(ws, header_text: str, after_col: int) -> int:
    """
    Ищет столбец с заголовком header_text в строке HEADER_ROW.
    Если не найден — добавляет новый столбец после after_col.
    Возвращает 1-based индекс столбца.
    """
    max_col = ws.max_column
    for col in range(1, max_col + 1):
        if ws.cell(HEADER_ROW, col).value == header_text:
            return col
    # Не найден — добавляем
    new_col = after_col + 1
    ws.insert_cols(new_col)
    # Заголовок
    cell = ws.cell(HEADER_ROW, new_col)
    cell.value = header_text
    cell.font = Font(bold=True, color="FFFFFF", size=10)
    cell.fill = _fill(CLR_HEADER)
    cell.alignment = Alignment(horizontal="center", wrap_text=True)
    return new_col


def update_excel(last_dates: dict[str, date | None], today: date) -> None:
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active

    # Находим столбцы
    max_col = ws.max_column
    header_row = [ws.cell(HEADER_ROW, c).value for c in range(1, max_col + 1)]

    def col_idx(name: str) -> int | None:
        try:
            return header_row.index(name) + 1
        except ValueError:
            return None

    cod_col         = col_idx("Код")
    period_col_name = col_idx("Периодичность")
    last_pt_col     = col_idx("Последняя точка")
    cnt_col         = col_idx("Кол-во точек")

    # Целевые столбцы — «Актуальный период» и «Статус»
    # Размещаем их сразу после «Последняя точка»
    anchor = last_pt_col or max_col
    actual_period_col = _find_or_create_col(ws, "Актуальный период", anchor)
    status_col        = _find_or_create_col(ws, "Статус", actual_period_col)

    # Устанавливаем ширину новых столбцов
    from openpyxl.utils import get_column_letter
    ws.column_dimensions[get_column_letter(actual_period_col)].width = 18
    ws.column_dimensions[get_column_letter(status_col)].width = 20

    # Собираем координаты объединённых ячеек (openpyxl возвращает MergedCell
    # для всех ячеек диапазона кроме верхней левой — запись в них вызовет ошибку)
    from openpyxl.cell.cell import MergedCell

    updated = 0
    for row in range(DATA_START, ws.max_row + 1):
        code_cell = ws.cell(row, cod_col) if cod_col else None
        code = code_cell.value if code_cell and not isinstance(code_cell, MergedCell) else None
        if not code or str(code).startswith("🗺"):
            continue
        code = str(code).strip()

        periodicity = ws.cell(row, period_col_name).value if period_col_name else ""
        periodicity = str(periodicity).strip() if periodicity else ""

        actual_date = last_dates.get(code)

        # Форматируем «Актуальный период»
        period_str = format_period(actual_date, periodicity)

        # Статус
        status_text, clr = compute_status(code, actual_date, today)

        # Записываем «Актуальный период» (пропускаем объединённые ячейки)
        ap_cell = ws.cell(row, actual_period_col)
        if not isinstance(ap_cell, MergedCell):
            ap_cell.value = period_str
            ap_cell.fill = _fill(clr)
            ap_cell.alignment = Alignment(horizontal="center")
            ap_cell.font = Font(size=10)

        # Записываем «Статус»
        st_cell = ws.cell(row, status_col)
        if not isinstance(st_cell, MergedCell):
            st_cell.value = status_text
            st_cell.fill = _fill(clr)
            st_cell.alignment = Alignment(horizontal="left")
            st_cell.font = Font(size=10)

        updated += 1

    # Обновляем заголовок файла с датой обновления
    title_cell = ws.cell(1, 1)
    if title_cell.value:
        import re
        title_cell.value = re.sub(
            r"\d{2}\.\d{2}\.\d{4}",
            today.strftime("%d.%m.%Y"),
            str(title_cell.value),
        )

    wb.save(EXCEL_PATH)
    print(f"✅ Обновлено {updated} индикаторов в {EXCEL_PATH}")


# ── Точка входа ────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    print(f"update_indicator_status.py | {today.strftime('%d.%m.%Y')}")
    print(f"  Excel: {EXCEL_PATH}")

    conn = _connect()
    try:
        last_dates = fetch_last_dates(conn)
        print(f"  Загружено из БД: {len(last_dates)} индикаторов")
    finally:
        conn.close()

    update_excel(last_dates, today)

    # Вывод сводки статусов
    statuses: dict[str, int] = {}
    for code, actual_date in last_dates.items():
        text, _ = compute_status(code, actual_date, today)
        statuses[text] = statuses.get(text, 0) + 1
    print("\n  Сводка по статусам:")
    for status, count in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"    {status}: {count}")


if __name__ == "__main__":
    main()
