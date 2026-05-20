# server/routers/analyses.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis
from server.schemas import AnalysisCreate, AnalysisOut, AnalysisListOut

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisOut, status_code=201)
def create_analysis(
    payload: AnalysisCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    record = Analysis(
        ticker=payload.ticker.upper(),
        trade_date=payload.trade_date,
        analysts=payload.analysts,
        depth=payload.depth,
        status="pending",
        stage="pending",
        seen=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Dispatch Celery task after committing so the ID exists in DB
    from server.tasks import run_analysis
    run_analysis.delay(record.id)

    return record


@router.get("", response_model=AnalysisListOut)
def list_analyses(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    total = db.query(Analysis).count()
    items = (
        db.query(Analysis)
        .order_by(Analysis.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return AnalysisListOut(items=items, total=total)


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return record


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete(record)
    db.commit()
