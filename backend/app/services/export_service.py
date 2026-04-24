import io
from collections import defaultdict
from datetime import date as date_type
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.models import Indicator
from app.services.data_service import get_time_series


HEADER_FILL = PatternFill("solid", fgColor="1A2B4A")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
BODY_FONT   = Font(name="Calibri", size=10)
BOLD_FONT   = Font(name="Calibri", size=10, bold=True)
THIN_BORDER = Border(bottom=Side(style="thin", color="E5E7EB"))
FMT_NUM1    = '#,##0.0'
FMT_NUM0    = '#,##0'
FMT_PCT1    = '0.0"%"'
FMT_PP1     = '+0.00;-0.00;0.00'  # п.п. — показывает знак
FMT_NUM2    = '#,##0.00'           # 2 знака после запятой (ставки)
FMT_PP2     = '+0.00" п.п.";-0.00" п.п.";0.00" п.п."'  # п.п. со знаком

MONTHS_RU_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
                    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']


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


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── Одиночный индикатор ────────────────────────────────────────────────────

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
        _set_header(ws, 6, col, h)

    for row_i, dp in enumerate(series, 7):
        ws.cell(row=row_i, column=1, value=dp.date).font = BODY_FONT
        ws.cell(row=row_i, column=2, value=dp.label).font = BODY_FONT
        c3 = ws.cell(row=row_i, column=3, value=_to_float(dp.value))
        c3.font = BODY_FONT
        c3.number_format = FMT_NUM1
        c4 = ws.cell(row=row_i, column=4, value=_to_float(dp.yoy_change_pct))
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


# ── Мульти-индикатор (универсальный) ──────────────────────────────────────

def export_multi_xlsx(indicators: list, series_map: dict, sheet_title: str = None) -> io.BytesIO:
    """
    Универсальный экспорт для любого набора индикаторов.

    indicators  — список объектов Indicator (или dict с полями code, name, unit)
    series_map  — {code: [DataPoint, ...]}

    Генерирует два листа:
      • «Данные» — все периоды по всем кодам в столбцах
      • «Годовые» — агрегат по годам (только для period_type='period' и числовых значений)
    """
    wb = Workbook()

    # Словарь метаданных по коду
    meta = {}
    for ind in indicators:
        if isinstance(ind, dict):
            meta[ind["code"]] = ind
        else:
            meta[ind.code] = {
                "code": ind.code,
                "name": ind.name,
                "unit": ind.unit or "",
                "periodicity": getattr(ind, "periodicity", "monthly"),
                "period_type": getattr(ind, "period_type", "period"),
                "source": ind.source.name if hasattr(ind, "source") and ind.source else "—",
            }

    codes = list(series_map.keys())
    if not codes:
        wb.save(buf := io.BytesIO())
        buf.seek(0)
        return buf

    # ── Определяем все даты (union) ────────────────────────────────────────
    maps = {code: {str(p.date): p for p in series_map[code]} for code in codes}
    all_dates = sorted(set(d for m in maps.values() for d in m.keys()))

    # ── Лист 1: Данные ─────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Данные"

    # Заголовок
    if sheet_title:
        ws_title = sheet_title
    else:
        ws_title = f"Данные: {', '.join(meta.get(c, {}).get('name', c)[:40] for c in codes[:3])}"
        if len(codes) > 3:
            ws_title += f" и ещё {len(codes) - 3}"
    ws["A1"] = ws_title
    ws["A1"].font = Font(bold=True, size=12, name="Calibri")
    sources = list(dict.fromkeys(meta.get(c, {}).get("source", "—") for c in codes))
    ws["A2"] = f"Источник: {', '.join(sources)}"
    ws["A2"].font = BODY_FONT

    # Строка заголовков: Период | [Значение, г/г, м/м] × N кодов
    header_row = 4
    _set_header(ws, header_row, 1, "Период")
    col = 2
    col_map = {}  # code -> (val_col, yoy_col, mom_col)
    for code in codes:
        m = meta.get(code, {})
        unit = m.get("unit", "")
        name = m.get("name", code)
        short = name[:30]
        is_pct_unit = unit.strip() in ('%', 'процент', 'п.п.')
        delta_label = 'г/г, п.п.' if is_pct_unit else 'г/г, %'
        mom_label   = 'м/м, п.п.' if is_pct_unit else 'м/м, %'
        _set_header(ws, header_row, col,     f"{short}\n({unit})")
        _set_header(ws, header_row, col + 1, f"{short}\n{delta_label}")
        _set_header(ws, header_row, col + 2, f"{short}\n{mom_label}")
        col_map[code] = (col, col + 1, col + 2)
        col += 3

    ws.row_dimensions[header_row].height = 40

    # Данные
    for row_i, d in enumerate(all_dates, header_row + 1):
        # Метка периода — берём из первого доступного кода
        label = d
        for code in codes:
            p = maps[code].get(d)
            if p and p.label:
                label = p.label
                break
        _set_str(ws, row_i, 1, label)

        for code in codes:
            vc, yc, mc = col_map[code]
            p = maps[code].get(d)
            val  = _to_float(p.value)           if p else None
            yoy  = _to_float(p.yoy_change_pct)  if p else None
            mom  = _to_float(p.mom_change_pct)  if p else None
            m_unit = meta.get(code, {}).get("unit", "").strip()
            is_pct = m_unit in ('%', 'процент', 'п.п.')
            val_fmt = '0.00"%"' if is_pct else FMT_NUM1
            dlt_fmt = FMT_PP2  if is_pct else FMT_PCT1
            _set_num(ws, row_i, vc, round(val, 2) if val is not None else None, val_fmt)
            _set_num(ws, row_i, yc, round(yoy, 2) if yoy is not None else None, dlt_fmt)
            _set_num(ws, row_i, mc, round(mom, 2) if mom is not None else None, dlt_fmt)

    # Ширина столбцов
    ws.column_dimensions["A"].width = 18
    for code in codes:
        for c in col_map[code]:
            ws.column_dimensions[get_column_letter(c)].width = 16

    # ── Лист 2: Годовые ────────────────────────────────────────────────────
    # Строим только если есть месячные данные (period_type='period', periodicity='monthly')
    monthly_codes = [
        c for c in codes
        if meta.get(c, {}).get("periodicity", "monthly") in ("monthly", "quarterly")
        and meta.get(c, {}).get("period_type", "period") == "period"
    ]

    if monthly_codes and all_dates:
        ws2 = wb.create_sheet("Годовые")
        ws2["A1"] = "Годовые данные (накопленный итог)"
        ws2["A1"].font = Font(bold=True, size=12, name="Calibri")
        ws2["A2"] = f"Источник: {', '.join(sources)}"
        ws2["A2"].font = BODY_FONT

        header_row2 = 4
        _set_header(ws2, header_row2, 1, "Год")
        col2 = 2
        col_map2 = {}
        for code in monthly_codes:
            m = meta.get(code, {})
            unit = m.get("unit", "")
            name = m.get("name", code)[:30]
            _set_header(ws2, header_row2, col2,     f"{name}\n({unit})")
            _set_header(ws2, header_row2, col2 + 1, f"{name}\nг/г, %")
            col_map2[code] = (col2, col2 + 1)
            col2 += 2

        ws2.row_dimensions[header_row2].height = 40

        # Группируем по годам
        year_vals = defaultdict(lambda: defaultdict(list))
        year_months = defaultdict(set)
        for d in all_dates:
            year = int(d[:4])
            month = int(d[5:7])
            year_months[year].add(month)
            for code in monthly_codes:
                p = maps[code].get(d)
                if p and p.value is not None:
                    year_vals[year][code].append(_to_float(p.value))

        current_year = date_type.today().year
        sorted_years = sorted(year_vals.keys())
        year_sums = {y: {c: sum(v) for c, v in year_vals[y].items()} for y in sorted_years}

        for row_i, year in enumerate(sorted_years, header_row2 + 1):
            months = sorted(year_months[year])
            is_partial = year == current_year and len(months) < 12
            if is_partial:
                label = f"{MONTHS_RU_SHORT[months[0]-1]}–{MONTHS_RU_SHORT[months[-1]-1]} {year}"
            else:
                label = str(year)

            _set_str(ws2, row_i, 1, label, bold=is_partial)

            for code in monthly_codes:
                vc2, yc2 = col_map2[code]
                val_y = year_sums[year].get(code)
                val_y_r = round(val_y, 1) if val_y is not None else None

                # ГоГ — для неполного года берём те же месяцы прошлого года
                prev_year = year - 1
                yoy_y = None
                if prev_year in year_sums:
                    if is_partial:
                        prev_months_dates = [f"{prev_year}-{str(m).zfill(2)}-01" for m in months]
                        prev_val = sum(
                            _to_float(maps[code][d].value) or 0
                            for d in prev_months_dates
                            if d in maps.get(code, {}) and maps[code][d].value is not None
                        )
                    else:
                        prev_val = year_sums[prev_year].get(code, 0)
                    if prev_val and val_y is not None:
                        yoy_y = round((val_y - prev_val) / abs(prev_val) * 100, 1)

                _set_num(ws2, row_i, vc2, val_y_r, FMT_NUM1)
                _set_num(ws2, row_i, yc2, yoy_y, FMT_PCT1)

        ws2.column_dimensions["A"].width = 20
        for code in monthly_codes:
            for c in col_map2[code]:
                ws2.column_dimensions[get_column_letter(c)].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
