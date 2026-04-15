import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from sqlalchemy.orm import Session

from app.models import Indicator
from app.services.data_service import get_time_series


HEADER_FILL  = PatternFill("solid", fgColor="1A2B4A")
HEADER_FONT  = Font(bold=True, color="FFFFFF", name="Calibri")
BODY_FONT    = Font(name="Calibri")
THIN_BORDER  = Border(
    bottom=Side(style="thin", color="E5E7EB"),
)


def export_indicator_xlsx(db: Session, ind: Indicator) -> io.BytesIO:
    series = get_time_series(db, ind.id)

    wb = Workbook()
    ws = wb.active
    ws.title = ind.code[:31]

    # Метаданные
    ws["A1"] = ind.name
    ws["A1"].font = Font(bold=True, size=13, name="Calibri")
    ws["A2"] = f"Единица измерения: {ind.unit or '—'}"
    ws["A3"] = f"Источник: {ind.source.name if ind.source else '—'}"
    ws["A4"] = f"Периодичность: {ind.periodicity or '—'}"

    # Заголовки таблицы
    headers = ["Дата", "Период", f"Значение ({ind.unit or ''})", "Изм. г/г, %"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    # Данные
    for row_i, dp in enumerate(series, 7):
        ws.cell(row=row_i, column=1, value=dp.date).font    = BODY_FONT
        ws.cell(row=row_i, column=2, value=dp.label).font   = BODY_FONT
        ws.cell(row=row_i, column=3, value=float(dp.value) if dp.value else None).font = BODY_FONT
        ws.cell(row=row_i, column=4, value=float(dp.yoy_change_pct) if dp.yoy_change_pct else None).font = BODY_FONT
        for col in range(1, 5):
            ws.cell(row=row_i, column=col).border = THIN_BORDER

    # Ширина столбцов
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
