# server/routers/analyses.py
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.database import get_db
from server.models import Analysis, AnalysisShare, AppSettings, User
from server.schemas import AnalysisCreate, AnalysisOut, AnalysisListOut
from server.events import analysis_event_stream

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _visible_filter(current_user: User):
    """SQLAlchemy filter: analyses visible to this user.
    Legacy rows (owner_id IS NULL) are visible to everyone for backward compat.
    Owned rows are visible to owner + users they've been shared with.
    """
    shared_ids = (
        AnalysisShare.__table__.c.analysis_id
    )
    return or_(
        Analysis.owner_id == None,          # noqa: E711 — legacy rows
        Analysis.owner_id == current_user.id,
        Analysis.id.in_(
            AnalysisShare.__table__.select()
            .with_only_columns(shared_ids)
            .where(AnalysisShare.__table__.c.shared_with_user_id == current_user.id)
            .scalar_subquery()
        ),
    )


def _get_accessible(analysis_id: str, current_user: User, db: Session) -> Analysis:
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if record.owner_id is not None and record.owner_id != current_user.id:
        share = db.query(AnalysisShare).filter(
            AnalysisShare.analysis_id == analysis_id,
            AnalysisShare.shared_with_user_id == current_user.id,
        ).first()
        if not share:
            raise HTTPException(status_code=403, detail="无权访问该报告")
    return record


def _get_owned(analysis_id: str, current_user: User, db: Session) -> Analysis:
    """Like _get_accessible but requires ownership for mutations."""
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if record.owner_id is not None and record.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该报告")
    return record


# ── Create ─────────────────────────────────────────────────────────────────────

@router.post("", response_model=AnalysisOut, status_code=201)
def create_analysis(
    payload: AnalysisCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = db.get(AppSettings, 1)
    llm_config = {
        "provider":    settings.provider    if settings else "openai",
        "api_key":     settings.api_key     if settings else None,
        "deep_model":  settings.deep_model  if settings else "gpt-4o",
        "quick_model": settings.quick_model if settings else "gpt-4o-mini",
        "backend_url": settings.backend_url if settings else None,
    } if settings else {}

    _ANALYST_ALIAS = {"sentiment": "social"}
    normalized_analysts = [_ANALYST_ALIAS.get(a, a) for a in payload.analysts]

    # Look up stock name for display purposes
    ticker_name = None
    try:
        from tradingagents.dataflows.stock_name_lookup import get_stock_name
        ticker_name = get_stock_name(payload.ticker)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("Stock name lookup failed for %s: %s", payload.ticker, e)

    record = Analysis(
        ticker=payload.ticker.upper(),
        ticker_name=ticker_name,
        trade_date=payload.trade_date,
        analysts=normalized_analysts,
        depth=payload.depth,
        status="pending",
        stage="pending",
        seen=True,
        llm_config=llm_config,
        owner_id=current_user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    from server.tasks import run_analysis
    task = run_analysis.delay(record.id)
    record.celery_task_id = task.id
    db.commit()

    return record


# ── Re-run ─────────────────────────────────────────────────────────────────────

_VALID_RERUN_STAGES = {
    "market", "social", "news", "fundamentals",
    "investment_plan", "trader_investment_plan", "final_trade_decision",
}


@router.post("/{analysis_id}/rerun/{stage}", response_model=AnalysisOut)
def rerun_stage_endpoint(
    analysis_id: str,
    stage: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if stage not in _VALID_RERUN_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage '{stage}'")
    record = _get_owned(analysis_id, current_user, db)
    if record.status in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Analysis is already running")

    record.status = "pending"
    record.stage = "pending"
    record.stage_detail = "等待重新分析…"
    record.error = None
    db.commit()
    db.refresh(record)

    from server.tasks import rerun_stage
    task = rerun_stage.delay(record.id, stage)
    record.celery_task_id = task.id
    db.commit()
    db.refresh(record)
    return record


# ── Stop ───────────────────────────────────────────────────────────────────────

@router.post("/{analysis_id}/stop", status_code=204)
def stop_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = _get_owned(analysis_id, current_user, db)
    if record.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="Analysis is not running")

    if record.celery_task_id:
        from server.celery_app import celery_app
        celery_app.control.revoke(record.celery_task_id, terminate=True, signal="SIGTERM")

    record.status = "stopped"
    record.stage_detail = "用户手动停止"
    record.error = "Manually stopped by user"
    record.seen = True
    db.commit()


# ── List / Get ─────────────────────────────────────────────────────────────────

@router.get("", response_model=AnalysisListOut)
def list_analyses(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    flt = _visible_filter(current_user)
    total = db.query(Analysis).filter(flt).count()
    items = (
        db.query(Analysis)
        .filter(flt)
        .order_by(Analysis.created_at.desc())
        .offset(skip).limit(limit).all()
    )
    return AnalysisListOut(items=items, total=total)


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_accessible(analysis_id, current_user, db)


@router.get("/{analysis_id}/stream")
async def stream_analysis_progress(
    analysis_id: str,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    """SSE stream — auth via ?token= query param (EventSource can't set headers)."""
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return StreamingResponse(
        analysis_event_stream(analysis_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = _get_owned(analysis_id, current_user, db)
    ticker_info = f"{record.ticker} ({record.ticker_name})" if record.ticker_name else record.ticker
    db.delete(record)
    db.flush()   # ensure the DELETE SQL is sent to MySQL before commit
    db.commit()
    logger = logging.getLogger(__name__)
    logger.info("deleted analysis %s [%s] by user %s", analysis_id, ticker_info, current_user.username)


# ── Sharing ────────────────────────────────────────────────────────────────────

class ShareUserOut(BaseModel):
    id: int
    username: str
    model_config = {"from_attributes": True}


class ShareRequest(BaseModel):
    user_ids: List[int]


@router.get("/{analysis_id}/shares", response_model=List[ShareUserOut])
def get_shares(
    analysis_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_accessible(analysis_id, current_user, db)
    rows = db.query(AnalysisShare).filter(AnalysisShare.analysis_id == analysis_id).all()
    user_ids = [r.shared_with_user_id for r in rows]
    if not user_ids:
        return []
    return db.query(User).filter(User.id.in_(user_ids)).all()


@router.post("/{analysis_id}/shares", status_code=204)
def add_shares(
    analysis_id: str,
    payload: ShareRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned(analysis_id, current_user, db)
    existing = {
        r.shared_with_user_id
        for r in db.query(AnalysisShare)
        .filter(AnalysisShare.analysis_id == analysis_id).all()
    }
    for uid in payload.user_ids:
        if uid != current_user.id and uid not in existing:
            db.add(AnalysisShare(analysis_id=analysis_id, shared_with_user_id=uid))
    db.commit()


@router.delete("/{analysis_id}/shares/{user_id}", status_code=204)
def remove_share(
    analysis_id: str,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned(analysis_id, current_user, db)
    db.query(AnalysisShare).filter(
        AnalysisShare.analysis_id == analysis_id,
        AnalysisShare.shared_with_user_id == user_id,
    ).delete()
    db.commit()
