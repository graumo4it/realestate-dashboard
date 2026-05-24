from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import Indicator, Category
from app.schemas import IndicatorBrief, IndicatorFull, DataPointOut, SearchResult


# ---------------------------------------------------------------------------
# Внутренние типы
# ---------------------------------------------------------------------------

@dataclass
class IndicatorSummary:
    """Внутренний тип: результат get_indicator_list_for_category.

    Не зависит от порядка колонок SQL — заполняется по именам через .mappings().
    Роутер маппит IndicatorSummary → IndicatorBrief.
    """
    id:                   int
    code:                 str
    name:                 str
    unit:                 Optional[str]
    periodicity:          Optional[str]
    chart_type:           Optional[str]
    last_updated:         Optional[datetime]
    last_value:           Optional[Decimal]
    last_value_formatted: Optional[str]
    last_period_label:    Optional[str]
    last_period_date:     Optional[date]
    yoy_change_pct:       Optional[Decimal]
    mom_change_pct:       Optional[Decimal]


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _fmt(value: Optional[Decimal], unit: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = float(value)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f} млн {unit or ''}".strip()
    if abs(v) >= 1_000:
        return f"{v:,.0f} {unit or ''}".strip()
    return f"{v:,.2f} {unit or ''}".strip()


def _change_expr(value_col: str, prev_col: str, unit_col: str) -> str:
    """SQL-фрагмент для расчёта изменения (YoY или MoM).

    Для показателей в процентах (unit='%') — абсолютная разность в п.п.
    Для остальных — относительная разность в %.
    NULL если предыдущее значение отсутствует или равно нулю.

    Используется в get_indicator_list_for_category и get_time_series.
    """
    return f"""CASE
            WHEN {unit_col} = '%'
                THEN {value_col} - {prev_col}
            WHEN {prev_col} IS NOT NULL AND {prev_col} != 0
                THEN ({value_col} - {prev_col}) / ABS({prev_col}) * 100
            ELSE NULL
        END"""


# ---------------------------------------------------------------------------
# Публичные функции сервиса
# ---------------------------------------------------------------------------

def get_indicator_list_for_category(db: Session, category_id: int) -> List[IndicatorSummary]:
    yoy = _change_expr("d.value", "d.value_prev_year", "i.unit")
    mom = _change_expr("d.value", "d.value_prev_period", "i.unit")

    rows = db.execute(text(f"""
        WITH last_point AS (
            SELECT DISTINCT ON (indicator_id)
                indicator_id,
                value,
                period_label,
                period_date
            FROM data_points
            ORDER BY indicator_id, period_date DESC
        ),
        last_dynamics AS (
            SELECT DISTINCT ON (indicator_id)
                indicator_id,
                value,
                value_prev_year,
                value_prev_period
            FROM data_points_with_dynamics
            ORDER BY indicator_id, period_date DESC
        )
        SELECT
            i.id,
            i.code,
            i.name,
            i.unit,
            i.periodicity,
            i.chart_type,
            i.last_updated,
            lp.value          AS last_value,
            lp.period_label   AS last_period_label,
            lp.period_date    AS last_period_date,
            ({yoy})           AS yoy_change_pct,
            ({mom})           AS mom_change_pct
        FROM indicators i
        LEFT JOIN last_point    lp ON lp.indicator_id = i.id
        LEFT JOIN last_dynamics d  ON d.indicator_id  = i.id
        WHERE i.category_id = :cat_id AND i.is_public = true
        ORDER BY i.sort_order, i.code
    """), {"cat_id": category_id}).mappings().fetchall()

    return [
        IndicatorSummary(
            id=r["id"],
            code=r["code"],
            name=r["name"],
            unit=r["unit"],
            periodicity=r["periodicity"],
            chart_type=r["chart_type"],
            last_updated=r["last_updated"],
            last_value=r["last_value"],
            last_value_formatted=_fmt(r["last_value"], r["unit"]),
            last_period_label=r["last_period_label"],
            last_period_date=r["last_period_date"],
            yoy_change_pct=r["yoy_change_pct"],
            mom_change_pct=r["mom_change_pct"],
        )
        for r in rows
    ]


def get_indicator_by_code(db: Session, code: str) -> Optional[Indicator]:
    """Возвращает индикатор по коду без фильтра is_public.

    Скрытые индикаторы (is_public=false) не показываются на страницах разделов
    (фильтруются в get_indicator_list_for_category), но остаются доступны для
    комбо-страниц через /api/multi/data и прямых запросов /api/indicators/{code}.
    """
    return (
        db.query(Indicator)
        .filter(Indicator.code == code)
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
    yoy = _change_expr("d.value", "d.value_prev_year", "i.unit")
    mom = _change_expr("d.value", "d.value_prev_period", "i.unit")

    rows = db.execute(text(f"""
        SELECT
            d.period_date,
            d.value,
            ({yoy})           AS yoy_change_pct,
            d.value_prev_year,
            d.period_label,
            dp.is_preliminary,
            ({mom})           AS mom_change_pct
        FROM data_points_with_dynamics d
        JOIN data_points dp ON dp.indicator_id = d.indicator_id
                           AND dp.period_date   = d.period_date
        JOIN indicators i ON i.id = d.indicator_id
        WHERE {where}
        ORDER BY d.period_date
    """), params).mappings().fetchall()

    return [
        DataPointOut(
            date=r["period_date"],
            value=r["value"],
            yoy_change_pct=r["yoy_change_pct"],
            prev_year_value=r["value_prev_year"],
            label=r["period_label"],
            is_preliminary=bool(r["is_preliminary"]),
            mom_change_pct=r["mom_change_pct"],
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
    """), {"q": f"%{query}%"}).mappings().fetchall()

    return [
        SearchResult(
            id=r["id"],
            code=r["code"],
            name=r["name"],
            unit=r["unit"],
            category_name=r["category_name"],
        )
        for r in rows
    ]
