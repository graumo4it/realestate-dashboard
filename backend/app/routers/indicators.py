from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Indicator
from app.schemas import IndicatorBrief, IndicatorFull, TimeSeriesOut, SearchResult
from app.services.data_service import (
    get_indicator_list_for_category,
    get_indicator_by_code,
    get_time_series,
    search_indicators,
    IndicatorSummary,
)
from app.services.export_service import export_indicator_xlsx

router = APIRouter(tags=["indicators"])


def _summary_to_brief(s: IndicatorSummary) -> IndicatorBrief:
    """Конвертирует внутренний IndicatorSummary в публичную схему IndicatorBrief.

    IndicatorBrief содержит два поля для YoY (yoy_change / yoy_change_pct) —
    оба заполняются одним значением из IndicatorSummary.
    """
    return IndicatorBrief(
        id=s.id,
        code=s.code,
        name=s.name,
        unit=s.unit,
        periodicity=s.periodicity,
        chart_type=s.chart_type,
        last_updated=s.last_updated,
        last_value=s.last_value,
        last_value_formatted=s.last_value_formatted,
        last_period_label=s.last_period_label,
        yoy_change=s.yoy_change_pct,
        yoy_change_pct=s.yoy_change_pct,
        mom_change_pct=s.mom_change_pct,
    )


@router.get("/categories/{code}/indicators", response_model=List[IndicatorBrief])
def category_indicators(code: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.code == code).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return [_summary_to_brief(s) for s in get_indicator_list_for_category(db, cat.id)]


@router.get("/indicators/{code}", response_model=IndicatorFull)
def indicator_detail(code: str, db: Session = Depends(get_db)):
    ind = get_indicator_by_code(db, code)
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return ind


@router.get("/indicators/{code}/data", response_model=TimeSeriesOut)
def indicator_data(
    code: str,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date:   Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    ind = get_indicator_by_code(db, code)
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    series = get_time_series(db, ind.id, from_date, to_date)
    return TimeSeriesOut(indicator=IndicatorFull.model_validate(ind), series=series)


@router.get("/indicators/{code}/data.xlsx")
def indicator_xlsx(code: str, db: Session = Depends(get_db)):
    ind = get_indicator_by_code(db, code)
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    buf = export_indicator_xlsx(db, ind)
    filename = f"indicator_{code.replace('.', '_')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/search", response_model=List[SearchResult])
def search(q: str = Query(..., min_length=2), db: Session = Depends(get_db)):
    return search_indicators(db, q)


@router.get("/multi/data")
def multi_indicator_data(
    codes: str = Query(..., description="Коды через запятую: 2.2,2.3"),
    from_date: Optional[date] = Query(None, alias="from"),
    to_date:   Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    code_list = [c.strip() for c in codes.split(",")]
    result = {}
    for code in code_list:
        ind = get_indicator_by_code(db, code)
        if ind:
            series = get_time_series(db, ind.id, from_date, to_date)
            result[code] = {
                "indicator": IndicatorFull.model_validate(ind),
                "series": series,
            }
    return result


@router.get("/multi/data.xlsx")
def multi_indicator_xlsx(
    codes: str = Query(..., description="Коды через запятую: 6.7,6.13,6.1"),
    labels: str = Query(None, description="Короткие метки через запятую (по порядку кодов)"),
    title: str = Query(None, description="Заголовок листа"),
    filename: str = Query(None, description="Имя файла без расширения"),
    db: Session = Depends(get_db),
):
    from app.services.export_service import export_multi_xlsx

    code_list  = [c.strip() for c in codes.split(",")]
    label_list = [l.strip() for l in labels.split(",")] if labels else []

    indicators = []
    series_map = {}

    for i, code in enumerate(code_list):
        ind = get_indicator_by_code(db, code)
        if not ind:
            continue
        # Если передана кастомная метка — подставляем в name для экспорта
        ind_meta = {
            "code":        ind.code,
            "name":        label_list[i] if i < len(label_list) else ind.name,
            "unit":        ind.unit or "",
            "periodicity": ind.periodicity or "monthly",
            "period_type": ind.period_type or "period",
            "source":      ind.source.name if ind.source else "—",
        }
        indicators.append(ind_meta)
        series_map[code] = get_time_series(db, ind.id)

    # Заголовок листа
    if title:
        sheet_title = title
    elif label_list:
        sheet_title = label_list[0].split("—")[0].strip() if label_list else "Данные"
    else:
        sheet_title = "Данные"

    buf = export_multi_xlsx(indicators, series_map, sheet_title=sheet_title)

    # Имя файла
    safe_filename = (filename or "_".join(code_list)).replace(".", "_") + ".xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )