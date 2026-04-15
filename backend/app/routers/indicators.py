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
)
from app.services.export_service import export_indicator_xlsx

router = APIRouter(tags=["indicators"])


@router.get("/categories/{code}/indicators", response_model=List[IndicatorBrief])
def category_indicators(code: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.code == code).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return get_indicator_list_for_category(db, cat.id)


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
