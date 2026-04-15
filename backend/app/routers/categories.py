from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.database import get_db
from app.models import Category, Indicator
from app.schemas import CategoryOut

router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=List[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    rows = (
        db.query(Category, func.count(Indicator.id).label("cnt"))
        .outerjoin(Indicator, Indicator.category_id == Category.id)
        .filter(Indicator.is_public == True)
        .group_by(Category.id)
        .order_by(Category.sort_order)
        .all()
    )
    result = []
    for cat, cnt in rows:
        out = CategoryOut.model_validate(cat)
        out.indicators_count = cnt
        result.append(out)
    return result
