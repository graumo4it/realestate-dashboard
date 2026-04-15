"""
FastAPI Backend — Статистика рынка жилой недвижимости России
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import categories, indicators, meta

app = FastAPI(
    title="Рынок недвижимости России — API",
    description="REST API для дашборда статистики рынка жилой недвижимости",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories.router, prefix="/api")
app.include_router(indicators.router, prefix="/api")
app.include_router(meta.router,       prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
