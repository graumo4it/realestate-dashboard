from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean,
    Numeric, Date, DateTime, ForeignKey, func
)
from sqlalchemy.orm import relationship

from app.database import Base


class Source(Base):
    __tablename__ = "sources"
    id          = Column(Integer, primary_key=True)
    code        = Column(String(50), unique=True, nullable=False)
    name        = Column(Text, nullable=False)
    base_url    = Column(Text)
    update_freq = Column(String(50))
    notes       = Column(Text)
    indicators  = relationship("Indicator", back_populates="source")


class Category(Base):
    __tablename__ = "categories"
    id          = Column(Integer, primary_key=True)
    code        = Column(String(50), unique=True, nullable=False)
    name        = Column(Text, nullable=False)
    sort_order  = Column(Integer, default=0)
    indicators  = relationship("Indicator", back_populates="category")


class Indicator(Base):
    __tablename__ = "indicators"
    id           = Column(Integer, primary_key=True)
    code         = Column(String(100), unique=True, nullable=False)
    category_id  = Column(Integer, ForeignKey("categories.id"))
    source_id    = Column(Integer, ForeignKey("sources.id"))
    name         = Column(Text, nullable=False)
    unit         = Column(Text)
    periodicity  = Column(String(20))
    period_type  = Column(String(20))
    geo_level    = Column(String(20), default="russia")
    description  = Column(Text)
    source_url   = Column(Text)
    last_updated = Column(DateTime(timezone=True))
    is_public    = Column(Boolean, default=True)
    chart_type   = Column(String(20), default="line")
    sort_order   = Column(Integer, default=0)

    category    = relationship("Category", back_populates="indicators")
    source      = relationship("Source",   back_populates="indicators")
    data_points = relationship("DataPoint", back_populates="indicator", cascade="all, delete-orphan")


class DataPoint(Base):
    __tablename__ = "data_points"
    id             = Column(BigInteger, primary_key=True)
    indicator_id   = Column(Integer, ForeignKey("indicators.id", ondelete="CASCADE"))
    period_date    = Column(Date, nullable=False)
    period_label   = Column(String(50))
    value          = Column(Numeric(20, 4))
    is_preliminary = Column(Boolean, default=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    indicator = relationship("Indicator", back_populates="data_points")


class UpdateJob(Base):
    __tablename__ = "update_jobs"
    id            = Column(Integer, primary_key=True)
    source_id     = Column(Integer, ForeignKey("sources.id"))
    started_at    = Column(DateTime(timezone=True), server_default=func.now())
    finished_at   = Column(DateTime(timezone=True))
    status        = Column(String(20))
    rows_upserted = Column(Integer)
    error_message = Column(Text)
