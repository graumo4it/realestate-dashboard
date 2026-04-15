from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List

from app.database import get_db
from app.schemas import LastUpdateItem

router = APIRouter(tags=["meta"])


@router.get("/meta/last-update", response_model=List[LastUpdateItem])
def last_update(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT s.code, s.name,
               uj.finished_at AS last_updated,
               uj.rows_upserted
        FROM sources s
        LEFT JOIN LATERAL (
            SELECT finished_at, rows_upserted
            FROM update_jobs
            WHERE source_id = s.id AND status = 'success'
            ORDER BY finished_at DESC
            LIMIT 1
        ) uj ON true
        ORDER BY s.id
    """)).fetchall()
    return [
        LastUpdateItem(
            source_code=r[0],
            source_name=r[1],
            last_updated=r[2],
            rows_upserted=r[3],
        )
        for r in rows
    ]
