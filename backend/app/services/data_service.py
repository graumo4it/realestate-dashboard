from datetime import date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import Indicator, Category
from app.schemas import IndicatorBrief, IndicatorFull, DataPointOut, SearchResult


def _fmt(value: Optional[Decimal], unit: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = float(value)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f} млн {unit or ''}".strip()
    if abs(v) >= 1_000:
        return f"{v:,.0f} {unit or ''}".strip()
    return f"{v:,.2f} {unit or ''}".strip()


def get_indicator_list_for_category(db: Session, category_id: int) -> List[IndicatorBrief]:
    rows = db.execute(text("""
        WITH last_point AS (
            SELECT DISTINCT ON (indicator_id)
                indicator_id,
                value,
                period_label,
                period_date
            FROM data_points
            ORDER BY indicator_id, period_date DESC
        ),
        dynamics AS (
            SELECT DISTINCT ON (indicator_id)
                indicator_id,
                yoy_change_pct
            FROM data_points_with_dynamics
            ORDER BY indicator_id, period_date DESC
        )
        SELECT
            i.id, i.code, i.name, i.unit, i.periodicity, i.chart_type, i.last_updated,
            lp.value          AS last_value,
            lp.period_label   AS last_period_label,
            lp.period_date    AS last_period_date,
            d.yoy_change_pct
        FROM indicators i
        LEFT JOIN last_point lp ON lp.indicator_id = i.id
        LEFT JOIN dynamics   d  ON d.indicator_id  = i.id
        WHERE i.category_id = :cat_id AND i.is_public = true
        ORDER BY i.sort_order, i.code
    """), {"cat_id": category_id}).fetchall()

    result = []
    for r in rows:
        last_value = r[7]
        yoy = r[10]
        result.append(IndicatorBrief(
            id=r[0], code=r[1], name=r[2], unit=r[3],
            periodicity=r[4], chart_type=r[5],
            last_updated=r[6],
            last_value=last_value,
            last_value_formatted=_fmt(last_value, r[3]),
            last_period_label=r[8],
            yoy_change=yoy,
            yoy_change_pct=yoy,
        ))
    return result


def get_indicator_by_code(db: Session, code: str) -> Optional[Indicator]:
    return (
        db.query(Indicator)
        .filter(Indicator.code == code, Indicator.is_public == True)
        .first()
    )


def get_time_series(
    db: Session,
    indicator_id: int,
    from_date: Optional[date] = None,
    to_date:   Optional[date] = None,
) -> List[DataPointOut]:
    filters = ["d.indicator_id = :ind_id"]
    params: dict = {"ind_id": indicator_id}
    if from_date:
        filters.append("d.period_date >= :from_date")
        params["from_date"] = from_date
    if to_date:
        filters.append("d.period_date <= :to_date")
        params["to_date"] = to_date

    where = " AND ".join(filters)
    rows = db.execute(text(f"""
        SELECT
            d.period_date,
            d.value,
            d.yoy_change_pct,
            d.value_prev_year,
            d.period_label,
            dp.is_preliminary
        FROM data_points_with_dynamics d
        JOIN data_points dp ON dp.indicator_id = d.indicator_id
                           AND dp.period_date   = d.period_date
        WHERE {where}
        ORDER BY d.period_date
    """), params).fetchall()

    return [
        DataPointOut(
            date=r[0],
            value=r[1],
            yoy_change_pct=r[2],
            prev_year_value=r[3],
            label=r[4],
            is_preliminary=bool(r[5]),
        )
        for r in rows
    ]


def search_indicators(db: Session, query: str) -> List[SearchResult]:
    rows = db.execute(text("""
        SELECT i.id, i.code, i.name, i.unit, c.name AS category_name
        FROM indicators i
        LEFT JOIN categories c ON c.id = i.category_id
        WHERE i.is_public = true
          AND (
              i.name ILIKE :q
              OR i.code ILIKE :q
              OR i.description ILIKE :q
          )
        ORDER BY i.sort_order, i.code
        LIMIT 50
    """), {"q": f"%{query}%"}).fetchall()

    return [
        SearchResult(id=r[0], code=r[1], name=r[2], unit=r[3], category_name=r[4])
        for r in rows
    ]
