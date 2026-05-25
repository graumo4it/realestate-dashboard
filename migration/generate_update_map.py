"""
generate_update_map.py
Генерирует Excel-файл с картой обновления всех индикаторов:
  - Лист 1: Все индикаторы (сводная таблица)
  - Лист 2: Парсеры (детали по каждому парсеру)
  - Лист 3: Расчётные скрипты (в составе scheduler)
  - Лист 4: Только ручной запуск
  - Лист 5: Без обновления (нет автоматики)

Запуск: python migration/generate_update_map.py
"""

import os
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side
)
from openpyxl.utils import get_column_letter

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Цвета ─────────────────────────────────────────────────────────────────────
GREEN   = "C6EFCE"  # ✅ работает автоматически
ORANGE  = "FCE4D6"  # 🔄 работает, но нужна ручная загрузка файлов
YELLOW  = "FFEB9C"  # ⚠️ парсер нужна переработка
BLUE    = "BDD7EE"  # 🔧 расчёт в scheduler
PURPLE  = "E2EFDA"  # 📝 ручной расчёт (не в scheduler)
RED     = "FFC7CE"  # ❌ нет обновления
GRAY    = "F2F2F2"  # заголовок
HEADER  = "4472C4"  # заголовок синий

# ── Статусы ───────────────────────────────────────────────────────────────────
STATUS_AUTO_PARSER_OK      = "✅ Авто-парсер (работает)"
STATUS_AUTO_PARSER_MANUAL  = "🔄 Авто-парсер (ручная загрузка файлов)"
STATUS_AUTO_PARSER_WARN    = "⚠️ Авто-парсер (нужна доработка)"
STATUS_AUTO_CALC           = "🔧 Авто-расчёт (в scheduler)"
STATUS_MANUAL_CALC         = "📝 Ручной расчёт"
STATUS_NO_UPDATE           = "❌ Нет автообновления"

# ── Данные по парсерам ────────────────────────────────────────────────────────

PARSERS = {
    "domrf_web": {
        "name": "domrf_web.py",
        "file": "parsers/domrf_web.py",
        "source": "ЕИСЖС / наш.дом.рф",
        "url": "https://наш.дом.рф (stockvariablesexsales.xlsx)",
        "schedule": "20-е число, 10:00 UTC (job: day20)",
        "status": STATUS_AUTO_PARSER_OK,
        "notes": "Готов, тестировался. Геоблокирован — только с RU IP.",
        "codes": ["3.1","3.2","3.3","3.4","3.17","3.18","3.19"],
    },
    "rosreestr": {
        "name": "fetch_rosreestr_ddu.py",
        "file": "migration/fetch_rosreestr_ddu.py",
        "source": "Росреестр (rosreestr.gov.ru)",
        "url": "rosreestr.gov.ru (открытые данные, XLS-файлы)",
        "schedule": "10-е число, 08:00 UTC (job: day10)",
        "status": STATUS_AUTO_PARSER_OK,
        "notes": "Готов, тестировался. Скачивает кумулятивные XLS, считает квартальные значения.",
        "codes": ["5.1"],
    },
    "cbr": {
        "name": "cbr.py",
        "file": "parsers/cbr.py",
        "source": "Банк России (cbr.ru)",
        "url": "cbr.ru (02_02_Mortgage.xlsx, 02_03_Scpa_mortgage.xlsx, 02_41_Mortgage_ihc.xlsx)",
        "schedule": "10-е число, 08:00 UTC (job: day10)",
        "status": STATUS_AUTO_PARSER_OK,
        "notes": "Работает. Протестирован в мае 2026: 45 строк ипотека + 328 строк субсидии.",
        "codes": [
            # direct from CBR files
            "6.1","6.2","6.3","6.4","6.7","6.8","6.9","6.10",
            "6.19","6.20","6.22","6.23",
            "6.70","6.71","6.72","6.73","6.76","6.77","6.78","6.79",
            "6.82","6.83","6.84","6.85",
            # calculated inside cbr.py
            "6.5","6.6","6.11","6.12","6.13","6.14","6.15","6.16",
            "6.17","6.18","6.21","6.24","6.25","6.26","6.27",
            "6.74","6.75","6.80","6.81","6.86","6.87",
            # subsidies from ДОМ.РФ API
            "6.36","6.37","6.38","6.39","6.40","6.41","6.42","6.43","6.44","6.45",
        ],
    },
    "subsidy": {
        "name": "SubsidyOnlyParser (cbr.py)",
        "file": "parsers/cbr.py",
        "source": "ДОМ.РФ API (01_02_01 — субсидии)",
        "url": "наш.дом.рф (API субсидий)",
        "schedule": "5-е число, 08:00 UTC (job: subsidy_first)",
        "status": STATUS_AUTO_PARSER_OK,
        "notes": "Работает. Входит в cbr.py (SubsidyOnlyParser). Протестирован в мае 2026.",
        "codes": ["6.36","6.37","6.38","6.39","6.40","6.41","6.42","6.43","6.44","6.45"],
    },
    "rosstat": {
        "name": "rosstat.py + fetch_fedstat.py",
        "file": "parsers/rosstat.py + migration/fetch_fedstat.py",
        "source": "fedstat.ru (ЕМИСС / Росстат)",
        "url": "fedstat.ru (EMISS API)",
        "schedule": "10-е число, 08:00 UTC (job: day10)",
        "status": STATUS_AUTO_PARSER_OK,
        "notes": "Работает локально. Протестирован в мае 2026: 17 строк. ⚠️ fedstat блокирует облачные IP — только локальный запуск. 1.2 перенесён на fetch_income_rosstat.py.",
        "codes": [
            "1.3",
            "2.1","2.2","2.3",
            "2.9","2.11","2.12","2.13","2.13.ext",
            "4.4","4.4.1","4.4.2","4.4.3",
            "4.5","4.5.1","4.5.2","4.5.3","4.5.4",
        ],
    },
    "rosstat_income": {
        "name": "fetch_income_rosstat.py",
        "file": "migration/fetch_income_rosstat.py",
        "source": "rosstat.gov.ru / folder/13397",
        "url": "https://rosstat.gov.ru/storage/mediabank/urov_10kv_Nkv-YYYY.xlsx",
        "schedule": "10-е число, 08:00 UTC (job: day10, после rosstat.py)",
        "status": STATUS_AUTO_PARSER_OK,
        "notes": "Скачивает актуальный urov_10kv_*kv-*.xlsx напрямую с Росстата. "
                 "Квартальные строки → 1.2. Строка «Год» → 1.2.y (официальное годовое среднее). "
                 "SSL-сертификат Росстата — verify=False.",
        "codes": ["1.2", "1.2.y"],
    },
    "domrf": {
        "name": "domrf.py (оркестратор)",
        "file": "parsers/domrf.py",
        "source": "Локальные Excel-файлы ДОМ.РФ (migration/domrf_data/)",
        "url": "Файлы добавляются вручную в migration/domrf_data/",
        "schedule": "20-е число, 10:00 UTC (job: day20)",
        "status": STATUS_AUTO_PARSER_MANUAL,
        "notes": "Оркестрация работает. Протестирован в мае 2026: 1118 строк. Требует ручной загрузки Excel-файлов ДОМ.РФ в domrf_data/ перед запуском.",
        "codes": [
            # migrate_apartments.py
            "apartments_count_1k","apartments_count_2k","apartments_count_3k",
            "apartments_count_4k","apartments_count_total",
            "apartments_area_1k","apartments_area_2k","apartments_area_3k",
            "apartments_area_4k","apartments_area_total",
            "apartments_share_1k","apartments_share_2k","apartments_share_3k","apartments_share_4k",
            # migrate_matrix_projects.py
            "3.6",
            # migrate_sales_matrix.py
            "5.8","4.1","apt_budget","apt_area","sales_apt_sqm",
            "mm_count","mm_price","mm_budget","mm_area","4.8","4.9",
            # migrate_sales_matrix.py (5.20/5.21 — переименованы из mm_count/mm_area)
            "5.20","5.21",
            # migrate_under_construction_domrf.py
            "uc_absorption_active","uc_absorption_total",
            "uc_area_active","uc_area_total",
            "uc_dev_activity",
            "uc_new_active","uc_new_total",
            "uc_new_vs_input_active","uc_new_vs_input_total",
            "uc_new_vs_sales_active","uc_new_vs_sales_total",
            "uc_sold_vs_ready","uc_stock_years_active","uc_stock_years_total",
        ],
    },
}

# ── Расчётные скрипты (в scheduler) ───────────────────────────────────────────

CALC_SCHEDULED = [
    {
        "script": "migrate_population_1990_2010.py --all-years",
        "schedule": "10-е, в составе day10 (последний шаг после rosstat.py)",
        "codes": ["1.1"],
        "formula": "Захардкожен словарь POPULATION_DATA: 1990–2025",
        "inputs": "Нет внешних источников — данные из Росстата захардкожены в скрипте",
        "trigger": "run_day10 → финальный шаг; обновляется при добавлении новых значений в скрипт",
    },
    {
        "script": "calc_housing_per_capita.py",
        "schedule": "10-е, в составе day10 (после rosstat.py)",
        "codes": ["2.6", "2.7", "2.8"],
        "formula": "2.6=2.1/1.1; 2.7=2.2/1.1; 2.8=(2.1−2.2)/1.1",
        "inputs": "2.1 (ввод всего, тыс. кв. м), 2.2 (ввод ИЖС), 1.1 (население, тыс. чел.)",
        "trigger": "rosstat.py → 2.1/2.2 обновились; 1.1 актуален (migrate_population ранее)",
    },
    {
        "script": "calc_avg_apt_area.py",
        "schedule": "20-е, в составе day20 (после domrf_web.py)",
        "codes": ["3.5"],
        "formula": "3.5 = 3.3 / 3.4",
        "inputs": "3.3 (жилая площадь), 3.4 (кол-во квартир)",
        "trigger": "domrf_web.py → 3.3/3.4 обновились",
    },
    {
        "script": "calc_sales_pace.py",
        "schedule": "20-е, в составе day20 (через domrf.py)",
        "codes": ["5.9", "5.9.ma12"],
        "formula": "5.9 = YTD-среднее 5.8; 5.9.ma12 = скользящее 12 мес.",
        "inputs": "5.8 (кол-во сделок ДДУ квартиры)",
        "trigger": "domrf.py → 5.8 обновился",
    },
    {
        "script": "calc_sales_pace_mm.py",
        "schedule": "20-е, в составе day20 (через domrf.py)",
        "codes": ["5.22", "5.22.ma12"],
        "formula": "5.22 = YTD-среднее 5.20; 5.22.ma12 = скользящее 12 мес.",
        "inputs": "5.20 (кол-во сделок машиноместа)",
        "trigger": "domrf.py → 5.20 обновился (через migrate_sales_matrix.py)",
    },
    {
        "script": "calc_developer_activity.py",
        "schedule": "20-е, в составе day20 (через domrf.py)",
        "codes": ["3.7"],
        "formula": "3.7 = 3.3[янв] × 1000 / 1.1",
        "inputs": "3.3 (жилая площадь МЖД), 1.1 (население)",
        "trigger": "domrf.py → 3.3 обновился",
    },
    {
        "script": "calc_demand_activity.py",
        "schedule": "20-е, в составе day20 (через domrf.py)",
        "codes": ["5.3"],
        "formula": "5.3 = SUM(5.1 за 4 кв. года) / 1.1",
        "inputs": "5.1 (ДДУ квартальные), 1.1 (население)",
        "trigger": "domrf.py; 5.1 обновляется 10-го (fetch_rosreestr_ddu.py ✅)",
    },
    {
        "script": "calc_affordability.py",
        "schedule": "20-е, в составе day20 (после domrf_web.py)",
        "codes": ["5.10"],
        "formula": "5.10 = 1.3 / цена_кв.м (из матрицы продаж)",
        "inputs": "1.3 (зарплата), матрица продаж DomRF (apt_budget/apt_area)",
        "trigger": "domrf_web.py → apt_budget/apt_area + 1.3 (rosstat 10-е) актуальны",
    },
    {
        "script": "calc_affordability_fcp.py",
        "schedule": "20-е, в составе day20 (после domrf_web.py)",
        "codes": ["5.11"],
        "formula": "5.11 = (цена_кв.м × площадь_2к) / (1.3 × 2 × 12 × 0.3)",
        "inputs": "1.3 (зарплата), apartments_area_2k, матрица продаж",
        "trigger": "domrf_web.py → apartments_area_2k обновился",
    },
    {
        "script": "calc_annual_companion.py",
        "schedule": "10-е, в составе day10 (после rosstat.py + fetch_income_rosstat.py)",
        "codes": ["1.3.y"],
        "formula": "1.3.y[Y] = (Q1 + Q2 + Q3 + Q4) / 4 из данных 1.3",
        "inputs": "1.3 (квартальная зарплата, обновляется rosstat.py)",
        "trigger": "rosstat.py → 1.3 обновился; только полные годы (все 4 квартала)",
    },
    {
        "script": "calc_housing_provision.py",
        "schedule": "10-е, в составе day10 (после migrate_population)",
        "codes": ["2.10"],
        "formula": "2.10 = жилфонд[N] × 1 000 000 / (население[N+1] × 1 000)",
        "inputs": "2.9 (жилфонд млн кв.м, конец года N), 1.1 (население тыс.чел, нач. N+1)",
        "trigger": "rosstat.py → 2.9 обновился; migrate_population → 1.1 актуален",
    },
    {
        "script": "calc_housing_need.py",
        "schedule": "10-е, в составе day10 (после calc_housing_provision)",
        "codes": ["5.12.33","5.12.38","5.13.33","5.13.38","5.14.33","5.14.38","5.15.33","5.15.38"],
        "formula": "5.12.T=(T−2.10)×1.1; 5.13.T=5.12.T/ввод; 5.14/5.15 — с долей благоустройства",
        "inputs": "2.10 (обеспеченность), 1.1 (население), 2.1 (ввод жилья), 2.13 (благоустройство %)",
        "trigger": "calc_housing_provision → 2.10 обновился",
    },
]

# ── Только ручной запуск ───────────────────────────────────────────────────────

CALC_MANUAL = []  # все показатели обновляются автоматически

# ── Без обновления ─────────────────────────────────────────────────────────────

NO_UPDATE = [
    {"code": "3.14", "reason": "Квартирография возводимого жилья (площадь) — 3 точки до 2022. Нет парсера."},
    {"code": "3.16", "reason": "Квартирография возводимого жилья (структура) — 3 точки до 2022. Нет парсера."},
    {"code": "5.4",  "reason": "Активность спроса на вторичном рынке (Росреестр) — excel_to_db.py. Нет парсера rosreestr.py"},
    {"code": "6.28", "reason": "Домклик — одобрено заявок. Нет парсера domclick.py (данные до апр 2024)"},
    {"code": "6.29", "reason": "Домклик — доля онлайн-заявок. Нет парсера domclick.py"},
    {"code": "6.30", "reason": "Домклик — доля заявок первичка. Нет парсера domclick.py"},
    {"code": "6.31", "reason": "Домклик — доля заявок вторичка. Нет парсера domclick.py"},
    {"code": "6.32", "reason": "Домклик — ипотечных сделок. Нет парсера domclick.py"},
    {"code": "6.33", "reason": "Домклик — доля первичка. Нет парсера domclick.py"},
    {"code": "6.34", "reason": "Домклик — доля вторичка. Нет парсера domclick.py"},
    {"code": "6.35", "reason": "ЦБ РФ — доля ипотеки в кредитах населению. Нет парсера (14 точек до нояб 2022)"},
]


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "realestate"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def fetch_indicators(conn):
    """Возвращает dict code → row"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.code, i.name, s.name as source_name,
                   i.periodicity, i.is_public, i.period_type, i.unit,
                   MAX(dp.period_date) as last_date,
                   COUNT(dp.id) as point_count
            FROM indicators i
            LEFT JOIN sources s ON i.source_id = s.id
            LEFT JOIN data_points dp ON dp.indicator_id = i.id
            GROUP BY i.code, i.name, s.name, i.periodicity, i.is_public, i.period_type, i.unit
            ORDER BY i.code
        """)
        cols = [d[0] for d in cur.description]
        return {row[0]: dict(zip(cols, row)) for row in cur.fetchall()}


# ── Excel helpers ─────────────────────────────────────────────────────────────

def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def bold_font(size=10, white=False):
    color = "FFFFFF" if white else "000000"
    return Font(bold=True, size=size, color=color)

def thin_border():
    s = Side(style="thin")
    return Border(left=s, right=s, top=s, bottom=s)

def write_header(ws, row, cols, bg=HEADER):
    for col_idx, text in enumerate(cols, 1):
        c = ws.cell(row=row, column=col_idx, value=text)
        c.font = bold_font(white=True)
        c.fill = fill(bg)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = thin_border()

def write_cell(ws, row, col, value, bg=None, bold=False, wrap=True, align="left"):
    c = ws.cell(row=row, column=col, value=value)
    c.font = Font(bold=bold, size=10)
    c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    if bg:
        c.fill = fill(bg)
    c.border = thin_border()
    return c

def set_col_widths(ws, widths):
    for col_idx, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w


# ── Лист 1: Сводная таблица ───────────────────────────────────────────────────

def build_summary(wb, indicators):
    ws = wb.create_sheet("📋 Все индикаторы")
    ws.freeze_panes = "A3"

    # Build status map
    # code → (status, parser_name, schedule, source_url)
    status_map = {}

    for pid, pdata in PARSERS.items():
        for code in pdata["codes"]:
            if pid == "subsidy":
                continue  # subsumed in cbr
            existing = status_map.get(code)
            if existing is None:
                status_map[code] = {
                    "status": pdata["status"],
                    "parser": pdata["name"],
                    "schedule": pdata["schedule"],
                    "source": pdata["source"],
                    "color": _parser_color(pdata["status"]),
                }

    for entry in CALC_SCHEDULED:
        for code in entry["codes"]:
            status_map[code] = {
                "status": STATUS_AUTO_CALC,
                "parser": entry["script"],
                "schedule": entry["schedule"],
                "source": entry["inputs"],
                "color": BLUE,
            }

    for entry in CALC_MANUAL:
        for code in entry["codes"]:
            status_map[code] = {
                "status": STATUS_MANUAL_CALC,
                "parser": entry["script"],
                "schedule": "Ручной запуск",
                "source": entry["inputs"],
                "color": PURPLE,
            }

    for entry in NO_UPDATE:
        code = entry["code"]
        status_map[code] = {
            "status": STATUS_NO_UPDATE,
            "parser": "—",
            "schedule": "—",
            "source": entry["reason"],
            "color": RED,
        }

    # Title
    ws.merge_cells("A1:J1")
    c = ws["A1"]
    c.value = f"🗺️ Карта обновления индикаторов | Realestate Dashboard | {datetime.now().strftime('%d.%m.%Y')}"
    c.font = bold_font(12)
    c.fill = fill("2F5496")
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.alignment = Alignment(horizontal="center", vertical="center")

    cols = [
        "Код", "Название", "Источник", "Периодичность",
        "Статус обновления", "Парсер / Скрипт",
        "Расписание", "Последняя точка", "Кол-во точек", "Примечания"
    ]
    write_header(ws, 2, cols)

    row = 3
    for code, ind in sorted(indicators.items(), key=lambda x: _sort_key(x[0])):
        sm = status_map.get(code, {
            "status": STATUS_NO_UPDATE,
            "parser": "—",
            "schedule": "—",
            "source": "Нет информации",
            "color": RED,
        })
        bg = sm["color"]
        last_date = ind.get("last_date")
        last_str = last_date.strftime("%d.%m.%Y") if last_date else "—"
        periodicity_ru = {
            "monthly": "Ежемесячно",
            "quarterly": "Ежеквартально",
            "annual": "Ежегодно",
        }.get(ind.get("periodicity", ""), ind.get("periodicity", ""))

        write_cell(ws, row, 1,  code,                       bg, bold=True,  align="center")
        write_cell(ws, row, 2,  ind.get("name",""),         bg)
        write_cell(ws, row, 3,  ind.get("source_name",""),  bg, align="center")
        write_cell(ws, row, 4,  periodicity_ru,             bg, align="center")
        write_cell(ws, row, 5,  sm["status"],               bg)
        write_cell(ws, row, 6,  sm["parser"],               bg)
        write_cell(ws, row, 7,  sm["schedule"],             bg)
        write_cell(ws, row, 8,  last_str,                   bg, align="center")
        write_cell(ws, row, 9,  ind.get("point_count", 0), bg, align="center")
        write_cell(ws, row, 10, sm["source"],               bg)
        row += 1

    set_col_widths(ws, [10, 55, 15, 14, 28, 30, 28, 14, 12, 55])
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 30

    # Legend
    row += 2
    ws.merge_cells(f"A{row}:J{row}")
    ws[f"A{row}"].value = "ЛЕГЕНДА:"
    ws[f"A{row}"].font = bold_font(10)
    row += 1
    legend = [
        (GREEN,  "✅ Авто-парсер (работает) — запускается по расписанию, данные скачиваются автоматически"),
        (ORANGE, "🔄 Авто-парсер (ручная загрузка) — оркестрация работает, но Excel-файлы ДОМ.РФ нужно загрузить вручную в domrf_data/ перед запуском"),
        (YELLOW, "⚠️ Авто-парсер (нужна доработка) — парсер ещё не доработан"),
        (BLUE,   "🔧 Авто-расчёт (в scheduler) — calc_*.py / migration-скрипт запускается автоматически в составе job"),
        (PURPLE, "📝 Ручной расчёт — запускается вручную 1 раз в год"),
        (RED,    "❌ Нет автообновления — данные загружены однажды, нет парсера"),
    ]
    for hex_c, text in legend:
        ws.merge_cells(f"A{row}:J{row}")
        c = ws[f"A{row}"]
        c.value = text
        c.fill = fill(hex_c)
        c.border = thin_border()
        c.font = Font(size=10)
        row += 1


def _parser_color(status):
    return {
        STATUS_AUTO_PARSER_OK:     GREEN,
        STATUS_AUTO_PARSER_MANUAL: ORANGE,
        STATUS_AUTO_PARSER_WARN:   YELLOW,
    }.get(status, YELLOW)


def _sort_key(code):
    """Ключ сортировки: числовые коды по компонентам, текстовые — в конец."""
    import re
    parts = re.split(r'[\.\-]', code)
    result = []
    for p in parts:
        try:
            result.append((0, float(p)))
        except ValueError:
            result.append((1, p))
    return result


# ── Лист 2: Парсеры ───────────────────────────────────────────────────────────

def build_parsers(wb, indicators):
    ws = wb.create_sheet("⚙️ Парсеры")
    ws.freeze_panes = "A3"

    ws.merge_cells("A1:H1")
    c = ws["A1"]
    c.value = "⚙️ Автоматические парсеры — детали"
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = fill("2F5496")
    c.alignment = Alignment(horizontal="center", vertical="center")

    header_cols = ["Парсер", "Статус", "Источник данных", "URL / Файл",
                   "Расписание", "Код", "Название", "Последняя точка"]
    write_header(ws, 2, header_cols)

    row = 3
    for pid, pdata in PARSERS.items():
        if pid == "subsidy":
            continue  # overlap with cbr
        color = _parser_color(pdata["status"])
        for i, code in enumerate(pdata["codes"]):
            ind = indicators.get(code, {})
            last_date = ind.get("last_date")
            last_str = last_date.strftime("%d.%m.%Y") if last_date else "—"
            write_cell(ws, row, 1, pdata["name"] if i == 0 else "", color, bold=(i == 0))
            write_cell(ws, row, 2, pdata["status"] if i == 0 else "", color)
            write_cell(ws, row, 3, pdata["source"] if i == 0 else "", color)
            write_cell(ws, row, 4, pdata["url"] if i == 0 else "", color)
            write_cell(ws, row, 5, pdata["schedule"] if i == 0 else "", color, align="center")
            write_cell(ws, row, 6, code, color, bold=True, align="center")
            write_cell(ws, row, 7, ind.get("name",""), color)
            write_cell(ws, row, 8, last_str, color, align="center")
            row += 1
        # blank separator
        row += 1

    set_col_widths(ws, [30, 28, 25, 50, 22, 12, 55, 14])


# ── Лист 3: Расчётные скрипты в scheduler ────────────────────────────────────

def build_calc_scheduled(wb, indicators):
    ws = wb.create_sheet("🔧 Авто-расчёт (scheduler)")
    ws.freeze_panes = "A3"

    ws.merge_cells("A1:H1")
    c = ws["A1"]
    c.value = "🔧 Расчётные скрипты, запускаемые автоматически в scheduler"
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = fill("2F5496")
    c.alignment = Alignment(horizontal="center", vertical="center")

    header_cols = ["Скрипт", "Расписание", "Код", "Название", "Формула расчёта",
                   "Входные данные", "Последняя точка", "Кол-во точек"]
    write_header(ws, 2, header_cols)

    row = 3
    for entry in CALC_SCHEDULED:
        for i, code in enumerate(entry["codes"]):
            ind = indicators.get(code, {})
            last_date = ind.get("last_date")
            last_str = last_date.strftime("%d.%m.%Y") if last_date else "—"
            write_cell(ws, row, 1, entry["script"] if i == 0 else "", BLUE, bold=(i == 0))
            write_cell(ws, row, 2, entry["schedule"] if i == 0 else "", BLUE)
            write_cell(ws, row, 3, code, BLUE, bold=True, align="center")
            write_cell(ws, row, 4, ind.get("name", ""), BLUE)
            write_cell(ws, row, 5, entry["formula"] if i == 0 else "", BLUE)
            write_cell(ws, row, 6, entry["inputs"] if i == 0 else "", BLUE)
            write_cell(ws, row, 7, last_str, BLUE, align="center")
            write_cell(ws, row, 8, ind.get("point_count", 0), BLUE, align="center")
            row += 1
        row += 1

    set_col_widths(ws, [28, 28, 12, 55, 45, 50, 14, 12])


# ── Лист 4: Только ручной расчёт ─────────────────────────────────────────────

def build_calc_manual(wb, indicators):
    ws = wb.create_sheet("📝 Ручной расчёт")
    ws.freeze_panes = "A3"

    ws.merge_cells("A1:H1")
    c = ws["A1"]
    c.value = "📝 Расчётные скрипты — только ручной запуск (не в scheduler)"
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = fill("2F5496")
    c.alignment = Alignment(horizontal="center", vertical="center")

    header_cols = ["Скрипт", "Код", "Название", "Формула расчёта",
                   "Входные данные", "Примечания", "Последняя точка", "Кол-во точек"]
    write_header(ws, 2, header_cols)

    row = 3
    for entry in CALC_MANUAL:
        for i, code in enumerate(entry["codes"]):
            ind = indicators.get(code, {})
            last_date = ind.get("last_date")
            last_str = last_date.strftime("%d.%m.%Y") if last_date else "—"
            write_cell(ws, row, 1, entry["script"] if i == 0 else "", PURPLE, bold=(i == 0))
            write_cell(ws, row, 2, code, PURPLE, bold=True, align="center")
            write_cell(ws, row, 3, ind.get("name", ""), PURPLE)
            write_cell(ws, row, 4, entry["formula"] if i == 0 else "", PURPLE)
            write_cell(ws, row, 5, entry["inputs"] if i == 0 else "", PURPLE)
            write_cell(ws, row, 6, entry["notes"] if i == 0 else "", PURPLE)
            write_cell(ws, row, 7, last_str, PURPLE, align="center")
            write_cell(ws, row, 8, ind.get("point_count", 0), PURPLE, align="center")
            row += 1
        row += 1

    set_col_widths(ws, [28, 12, 55, 55, 55, 45, 14, 12])


# ── Лист 5: Без обновления ────────────────────────────────────────────────────

def build_no_update(wb, indicators):
    ws = wb.create_sheet("❌ Нет обновления")
    ws.freeze_panes = "A3"

    ws.merge_cells("A1:G1")
    c = ws["A1"]
    c.value = "❌ Индикаторы без автоматического обновления"
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = fill("2F5496")
    c.alignment = Alignment(horizontal="center", vertical="center")

    header_cols = ["Код", "Название", "Источник", "Периодичность",
                   "Последняя точка", "Кол-во точек", "Причина / Что нужно сделать"]
    write_header(ws, 2, header_cols)

    row = 3
    for entry in NO_UPDATE:
        code = entry["code"]
        ind = indicators.get(code, {})
        last_date = ind.get("last_date")
        last_str = last_date.strftime("%d.%m.%Y") if last_date else "—"
        periodicity_ru = {
            "monthly": "Ежемесячно",
            "quarterly": "Ежеквартально",
            "annual": "Ежегодно",
        }.get(ind.get("periodicity", ""), ind.get("periodicity", ""))
        write_cell(ws, row, 1, code,                       RED, bold=True, align="center")
        write_cell(ws, row, 2, ind.get("name",""),         RED)
        write_cell(ws, row, 3, ind.get("source_name",""),  RED, align="center")
        write_cell(ws, row, 4, periodicity_ru,             RED, align="center")
        write_cell(ws, row, 5, last_str,                   RED, align="center")
        write_cell(ws, row, 6, ind.get("point_count", 0), RED, align="center")
        write_cell(ws, row, 7, entry["reason"],            RED)
        row += 1

    set_col_widths(ws, [10, 55, 15, 14, 14, 12, 70])


# ── Лист 6: Статистика ────────────────────────────────────────────────────────

def build_stats(wb, indicators):
    ws = wb.create_sheet("📊 Статистика")

    def hdr(text, row, col):
        c = ws.cell(row=row, column=col, value=text)
        c.font = bold_font(white=True)
        c.fill = fill(HEADER)
        c.alignment = Alignment(horizontal="center")
        c.border = thin_border()

    def val(text, row, col, color=None):
        c = ws.cell(row=row, column=col, value=text)
        c.alignment = Alignment(horizontal="center")
        if color:
            c.fill = fill(color)
        c.border = thin_border()

    ws.merge_cells("A1:C1")
    c = ws["A1"]
    c.value = "📊 Статистика покрытия индикаторов"
    c.font = Font(bold=True, size=12, color="FFFFFF")
    c.fill = fill("2F5496")
    c.alignment = Alignment(horizontal="center")

    hdr("Категория", 2, 1)
    hdr("Кол-во индикаторов", 2, 2)
    hdr("% от общего", 2, 3)

    total = len(indicators)
    # Count by status
    ok_codes = set()
    manual_codes = set()
    warn_codes = set()
    for pid, pdata in PARSERS.items():
        if pid == "subsidy":
            continue
        if pdata["status"] == STATUS_AUTO_PARSER_OK:
            ok_codes.update(pdata["codes"])
        elif pdata["status"] == STATUS_AUTO_PARSER_MANUAL:
            manual_codes.update(pdata["codes"])
        else:
            warn_codes.update(pdata["codes"])
    calc_s_codes = set()
    for e in CALC_SCHEDULED:
        calc_s_codes.update(e["codes"])
    calc_m_codes = set()
    for e in CALC_MANUAL:
        calc_m_codes.update(e["codes"])
    no_upd_codes = set(e["code"] for e in NO_UPDATE)

    rows_data = [
        (STATUS_AUTO_PARSER_OK,     GREEN,  ok_codes),
        (STATUS_AUTO_PARSER_MANUAL, ORANGE, manual_codes),
        (STATUS_AUTO_PARSER_WARN,   YELLOW, warn_codes),
        (STATUS_AUTO_CALC,          BLUE,   calc_s_codes),
        (STATUS_MANUAL_CALC,        PURPLE, calc_m_codes),
        (STATUS_NO_UPDATE,          RED,    no_upd_codes),
    ]
    r = 3
    for status, color, codes in rows_data:
        cnt = len(codes)
        pct = f"{cnt/total*100:.1f}%"
        val(status, r, 1, color)
        val(cnt, r, 2, color)
        val(pct, r, 3, color)
        r += 1

    val("ИТОГО", r, 1)
    val(total, r, 2)
    val("100%", r, 3)

    set_col_widths(ws, [35, 22, 12])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    out_path = Path(__file__).parent.parent / "indicator_update_map.xlsx"

    print("Подключение к БД...")
    conn = connect()
    indicators = fetch_indicators(conn)
    conn.close()
    print(f"  Загружено {len(indicators)} индикаторов")

    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    print("Строю листы Excel...")
    build_summary(wb, indicators)
    build_parsers(wb, indicators)
    build_calc_scheduled(wb, indicators)
    build_calc_manual(wb, indicators)
    build_no_update(wb, indicators)
    build_stats(wb, indicators)

    wb.save(str(out_path))
    print(f"✅ Файл сохранён: {out_path}")
    return str(out_path)


if __name__ == "__main__":
    main()
