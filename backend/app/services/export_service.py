import io
from collections import defaultdict
from datetime import date as date_type
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.models import Indicator
from app.services.data_service import get_time_series


HEADER_FILL  = PatternFill("solid", fgColor="1A2B4A")
HEADER_FONT  = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
BODY_FONT    = Font(name="Calibri", size=10)
BOLD_FONT    = Font(name="Calibri", size=10, bold=True)
THIN_BORDER  = Border(bottom=Side(style="thin", color="E5E7EB"))
FMT_NUM1     = '#,##0.0'      # Числа с 1 знаком
FMT_PCT1     = '0.0"%"'       # Проценты с 1 знаком


def _set_header(ws, row, col, value):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill = HEADER_FILL
    cell.font = HEADER_FONT
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    return cell


def _set_num(ws, row, col, value, fmt=FMT_NUM1):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = BODY_FONT
    cell.border = THIN_BORDER
    cell.alignment = Alignment(horizontal="right")
    if value is not None:
        cell.number_format = fmt
    return cell


def _set_str(ws, row, col, value, bold=False):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = BOLD_FONT if bold else BODY_FONT
    cell.border = THIN_BORDER
    return cell


MONTHS_RU_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


def export_indicator_xlsx(db: Session, ind: Indicator) -> io.BytesIO:
    series = get_time_series(db, ind.id)
    wb = Workbook()
    ws = wb.active
    ws.title = ind.code[:31]

    ws["A1"] = ind.name
    ws["A1"].font = Font(bold=True, size=13, name="Calibri")
    ws["A2"] = f"Единица измерения: {ind.unit or '—'}"
    ws["A3"] = f"Источник: {ind.source.name if ind.source else '—'}"
    ws["A4"] = f"Периодичность: {ind.periodicity or '—'}"

    headers = ["Дата", "Период", f"Значение ({ind.unit or ''})", "Изм. г/г, %"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    for row_i, dp in enumerate(series, 7):
        ws.cell(row=row_i, column=1, value=dp.date).font = BODY_FONT
        ws.cell(row=row_i, column=2, value=dp.label).font = BODY_FONT
        c3 = ws.cell(row=row_i, column=3, value=float(dp.value) if dp.value else None)
        c3.font = BODY_FONT
        c3.number_format = FMT_NUM1
        c4 = ws.cell(row=row_i, column=4, value=float(dp.yoy_change_pct) if dp.yoy_change_pct else None)
        c4.font = BODY_FONT
        c4.number_format = FMT_PCT1
        for col in range(1, 5):
            ws.cell(row=row_i, column=col).border = THIN_BORDER

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_multi_xlsx(indicators, series_map: dict) -> io.BytesIO:
    wb = Workbook()

    # ── Лист 1: Месячные данные ─────────────────────────────────────────────
    ws = wb.active
    ws.title = "Месячные данные"

    ws["A1"] = "Объём ввода жилья, тыс. кв. м"
    ws["A1"].font = Font(bold=True, size=13, name="Calibri")
    ws["A2"] = "Источник: Росстат"
    ws["A2"].font = BODY_FONT

    headers = [
        "Период",
        "Всего", "ИЖС", "МЖС",
        "Всего г/г %", "ИЖС г/г %", "МЖС г/г %",
        "Всего м/м %", "ИЖС м/м %", "МЖС м/м %",
    ]
    for col, h in enumerate(headers, 1):
        _set_header(ws, 4, col, h)

    s22 = series_map.get("2.2", [])
    s23 = series_map.get("2.3", [])
    map22 = {str(p.date): p for p in s22}
    map23 = {str(p.date): p for p in s23}
    all_dates = sorted(set(list(map22.keys()) + list(map23.keys())))

    prev_total = None
    for row_i, d in enumerate(all_dates, 5):
        p22 = map22.get(d)
        p23 = map23.get(d)
        v22 = float(p22.value) if p22 and p22.value else None
        v23 = float(p23.value) if p23 and p23.value else None
        total = (v22 or 0) + (v23 or 0) if (v22 is not None or v23 is not None) else None

        # МоМ для всего
        mom_total = None
        if total is not None and prev_total is not None and prev_total != 0:
            mom_total = round((total - prev_total) / abs(prev_total) * 100, 1)
        prev_total = total

        # ГоГ для всего
        prev22 = float(p22.prev_year_value) if p22 and p22.prev_year_value else None
        prev23 = float(p23.prev_year_value) if p23 and p23.prev_year_value else None
        yoy_total = None
        if total is not None and (prev22 is not None or prev23 is not None):
            pt = (prev22 or 0) + (prev23 or 0)
            if pt != 0:
                yoy_total = round((total - pt) / abs(pt) * 100, 1)

        label = (p22.label if p22 and p22.label else None) or (p23.label if p23 and p23.label else d)

        _set_str(ws, row_i, 1, label)
        _set_num(ws, row_i, 2, round(total, 1) if total is not None else None)
        _set_num(ws, row_i, 3, round(v22, 1) if v22 is not None else None)
        _set_num(ws, row_i, 4, round(v23, 1) if v23 is not None else None)
        _set_num(ws, row_i, 5, yoy_total, FMT_PCT1)
        _set_num(ws, row_i, 6, round(float(p22.yoy_change_pct), 1) if p22 and p22.yoy_change_pct else None, FMT_PCT1)
        _set_num(ws, row_i, 7, round(float(p23.yoy_change_pct), 1) if p23 and p23.yoy_change_pct else None, FMT_PCT1)
        _set_num(ws, row_i, 8, mom_total, FMT_PCT1)
        _set_num(ws, row_i, 9, round(float(p22.mom_change_pct), 1) if p22 and p22.mom_change_pct else None, FMT_PCT1)
        _set_num(ws, row_i, 10, round(float(p23.mom_change_pct), 1) if p23 and p23.mom_change_pct else None, FMT_PCT1)

    # Ширина столбцов
    ws.column_dimensions["A"].width = 18
    for i in range(2, 11):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.row_dimensions[4].height = 30

    # ── Лист 2: Годовые данные ──────────────────────────────────────────────
    ws2 = wb.create_sheet("Годовые данные")
    ws2["A1"] = "Годовой ввод жилья, тыс. кв. м"
    ws2["A1"].font = Font(bold=True, size=13, name="Calibri")
    ws2["A2"] = "Источник: Росстат"
    ws2["A2"].font = BODY_FONT

    for col, h in enumerate(["Год", "Всего", "ИЖС", "МЖС", "Всего г/г %", "ИЖС г/г %", "МЖС г/г %"], 1):
        _set_header(ws2, 4, col, h)

    # Группируем по годам
    year_data = defaultdict(lambda: {"v22": 0.0, "v23": 0.0, "months": [], "dates": []})
    for d in all_dates:
        year = int(d[:4])
        month = int(d[5:7])
        p22 = map22.get(d)
        p23 = map23.get(d)
        if p22 and p22.value: year_data[year]["v22"] += float(p22.value)
        if p23 and p23.value: year_data[year]["v23"] += float(p23.value)
        year_data[year]["months"].append(month)
        year_data[year]["dates"].append(d)

    current_year = date_type.today().year
    sorted_years = sorted(year_data.keys())

    # Словарь годовых итогов для расчёта ГоГ
    year_totals = {y: year_data[y]["v22"] + year_data[y]["v23"] for y in sorted_years}
    year_v22 = {y: year_data[y]["v22"] for y in sorted_years}
    year_v23 = {y: year_data[y]["v23"] for y in sorted_years}

    for row_i, year in enumerate(sorted_years, 5):
        yd = year_data[year]
        total_y = round(yd["v22"] + yd["v23"], 1)
        v22_y = round(yd["v22"], 1)
        v23_y = round(yd["v23"], 1)
        months = sorted(yd["months"])
        is_partial = year == current_year and len(months) < 12

        if is_partial:
            m_from = MONTHS_RU_SHORT[months[0] - 1]
            m_to = MONTHS_RU_SHORT[months[-1] - 1]
            label = f"{m_from}–{m_to} {year}"
        else:
            label = str(year)

        # ГоГ для года — для неполного года сравниваем только те же месяцы прошлого года
        prev_year = year - 1
        yoy_total_y = None
        yoy_v22_y = None
        yoy_v23_y = None

        if is_partial:
            # Считаем сумму тех же месяцев за прошлый год
            prev_months_dates = [f"{prev_year}-{str(m).zfill(2)}-01" for m in months]
            prev_v22 = sum(float(map22[d].value) for d in prev_months_dates if d in map22 and map22[d].value)
            prev_v23 = sum(float(map23[d].value) for d in prev_months_dates if d in map23 and map23[d].value)
            prev_total_partial = prev_v22 + prev_v23
            if prev_total_partial != 0:
                yoy_total_y = round((year_totals[year] - prev_total_partial) / abs(prev_total_partial) * 100, 1)
            if prev_v22 != 0:
                yoy_v22_y = round((year_v22[year] - prev_v22) / abs(prev_v22) * 100, 1)
            if prev_v23 != 0:
                yoy_v23_y = round((year_v23[year] - prev_v23) / abs(prev_v23) * 100, 1)
        else:
            if prev_year in year_totals and year_totals[prev_year] != 0:
                yoy_total_y = round((year_totals[year] - year_totals[prev_year]) / abs(year_totals[prev_year]) * 100, 1)
            if prev_year in year_v22 and year_v22[prev_year] != 0:
                yoy_v22_y = round((year_v22[year] - year_v22[prev_year]) / abs(year_v22[prev_year]) * 100, 1)
            if prev_year in year_v23 and year_v23[prev_year] != 0:
                yoy_v23_y = round((year_v23[year] - year_v23[prev_year]) / abs(year_v23[prev_year]) * 100, 1)

        _set_str(ws2, row_i, 1, label, bold=is_partial)
        _set_num(ws2, row_i, 2, total_y)
        _set_num(ws2, row_i, 3, v22_y)
        _set_num(ws2, row_i, 4, v23_y)
        _set_num(ws2, row_i, 5, yoy_total_y, FMT_PCT1)
        _set_num(ws2, row_i, 6, yoy_v22_y, FMT_PCT1)
        _set_num(ws2, row_i, 7, yoy_v23_y, FMT_PCT1)

    ws2.column_dimensions["A"].width = 20
    for i in range(2, 8):
        ws2.column_dimensions[get_column_letter(i)].width = 14
    ws2.row_dimensions[4].height = 30

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf