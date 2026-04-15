from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:               int
    code:             str
    name:             str
    sort_order:       int
    indicators_count: int = 0


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code:        str
    name:        str
    update_freq: Optional[str] = None


class IndicatorBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:                   int
    code:                 str
    name:                 str
    unit:                 Optional[str]
    periodicity:          Optional[str]
    chart_type:           Optional[str]
    last_value:           Optional[Decimal]
    last_value_formatted: Optional[str]
    last_period_label:    Optional[str]
    last_updated:         Optional[datetime]
    yoy_change:           Optional[Decimal]
    yoy_change_pct:       Optional[Decimal]


class IndicatorFull(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id:          int
    code:        str
    name:        str
    unit:        Optional[str]
    periodicity: Optional[str]
    period_type: Optional[str]
    geo_level:   Optional[str]
    description: Optional[str]
    source_url:  Optional[str]
    chart_type:  Optional[str]
    last_updated: Optional[datetime]
    category:    Optional[CategoryOut]
    source:      Optional[SourceOut]


class DataPointOut(BaseModel):
    date:              date
    value:             Optional[Decimal]
    yoy_change_pct:    Optional[Decimal]
    prev_year_value:   Optional[Decimal]
    label:             Optional[str]
    is_preliminary:    bool = False


class TimeSeriesOut(BaseModel):
    indicator: IndicatorFull
    series:    List[DataPointOut]


class SearchResult(BaseModel):
    id:   int
    code: str
    name: str
    unit: Optional[str]
    category_name: Optional[str]


class LastUpdateItem(BaseModel):
    source_code:  str
    source_name:  str
    last_updated: Optional[datetime]
    rows_upserted: Optional[int]
