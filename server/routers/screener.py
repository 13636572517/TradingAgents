# server/routers/screener.py
"""Stock-screener API: run the sector-valuation → leader-selection pipeline,
inspect results, and trigger deep analysis on candidates (single or batch)."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.database import get_db
from server.models import Analysis, ScreeningRun, ScreeningCandidate, User
from server.schemas import (
    ScreeningRunCreate, ScreeningRunOut, ScreeningRunDetailOut, ScreeningCandidateOut,
    AnalysisOut,
)

router = APIRouter(prefix="/api/screener", tags=["screener"])


# ── Run management ────────────────────────────────────────────────────────────────

@router.post("/run", response_model=ScreeningRunOut, status_code=201)
def create_run(
    payload: ScreeningRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a screening run and dispatch it to Celery. Returns immediately
    with status='running'; poll GET /runs/{id} for results."""
    from server.tasks import run_screening_task

    run = ScreeningRun(
        id=str(uuid.uuid4()),
        run_date=__import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        status="running",
        trigger="manual",
        params=payload.params,
        owner_id=current_user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    run_screening_task.delay(
        run.id,
        auto_analyze=payload.auto_analyze,
        auto_analyze_top=payload.auto_analyze_top,
        depth=payload.depth,
    )
    return run


@router.get("/runs", response_model=List[ScreeningRunOut])
def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(ScreeningRun)
        .order_by(ScreeningRun.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )


@router.get("/runs/latest", response_model=ScreeningRunDetailOut)
def latest_run(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = (
        db.query(ScreeningRun)
        .order_by(ScreeningRun.created_at.desc())
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="暂无筛选记录")
    return _run_detail(db, run)


@router.get("/runs/{run_id}", response_model=ScreeningRunDetailOut)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.get(ScreeningRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="筛选记录不存在")
    return _run_detail(db, run)


def _run_detail(db: Session, run: ScreeningRun) -> ScreeningRunDetailOut:
    candidates = (
        db.query(ScreeningCandidate)
        .filter(ScreeningCandidate.run_id == run.id)
        .order_by(ScreeningCandidate.score.desc())
        .all()
    )
    detail = ScreeningRunDetailOut.model_validate(run)
    detail.candidates = [ScreeningCandidateOut.model_validate(c) for c in candidates]
    return detail


# ── Trigger analysis on candidates ──────────────────────────────────────────────────

@router.post("/candidates/{candidate_id}/analyze", response_model=AnalysisOut, status_code=201)
def analyze_candidate(
    candidate_id: str,
    depth: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Launch a deep analysis for a single candidate and link it back."""
    from server.tasks import launch_analysis

    cand = db.get(ScreeningCandidate, candidate_id)
    if not cand:
        raise HTTPException(status_code=404, detail="候选股不存在")

    # Reuse an existing in-flight/complete analysis if already linked
    if cand.analysis_id:
        existing = db.get(Analysis, cand.analysis_id)
        if existing:
            return existing

    analysis = launch_analysis(db, cand.ticker, owner_id=current_user.id, depth=depth)
    cand.analysis_id = analysis.id
    db.commit()
    return analysis


@router.post("/runs/{run_id}/analyze-all", response_model=List[AnalysisOut], status_code=201)
def analyze_all(
    run_id: str,
    depth: int = 1,
    board_name: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch-launch deep analyses for all candidates of a run (optionally one board).
    Deduplicates by ticker and skips candidates already linked to an analysis."""
    from server.tasks import launch_analysis

    run = db.get(ScreeningRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="筛选记录不存在")

    q = db.query(ScreeningCandidate).filter(ScreeningCandidate.run_id == run_id)
    if board_name:
        q = q.filter(ScreeningCandidate.board_name == board_name)
    candidates = q.order_by(ScreeningCandidate.score.desc()).all()

    launched: List[Analysis] = []
    seen_tickers: set[str] = set()
    for cand in candidates:
        if cand.ticker in seen_tickers:
            continue
        seen_tickers.add(cand.ticker)
        if cand.analysis_id:
            existing = db.get(Analysis, cand.analysis_id)
            if existing:
                launched.append(existing)
                continue
        analysis = launch_analysis(db, cand.ticker, owner_id=current_user.id, depth=depth)
        cand.analysis_id = analysis.id
        db.commit()
        launched.append(analysis)

    return launched
