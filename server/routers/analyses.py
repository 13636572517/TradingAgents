# server/routers/analyses.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis, AppSettings
from server.schemas import AnalysisCreate, AnalysisOut, AnalysisListOut
from server.events import analysis_event_stream

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisOut, status_code=201)
def create_analysis(
    payload: AnalysisCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Snapshot current LLM settings so the task uses them even if settings change later
    settings = db.get(AppSettings, 1)
    llm_config = {
        "provider":   settings.provider   if settings else "openai",
        "api_key":    settings.api_key    if settings else None,
        "deep_model": settings.deep_model if settings else "gpt-4o",
        "quick_model":settings.quick_model if settings else "gpt-4o-mini",
        "backend_url":settings.backend_url if settings else None,
    } if settings else {}

    record = Analysis(
        ticker=payload.ticker.upper(),
        trade_date=payload.trade_date,
        analysts=payload.analysts,
        depth=payload.depth,
        status="pending",
        stage="pending",
        seen=True,
        llm_config=llm_config,
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


@router.get("/{analysis_id}/stream")
async def stream_analysis_progress(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return StreamingResponse(
        analysis_event_stream(analysis_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete(record)
    db.commit()
