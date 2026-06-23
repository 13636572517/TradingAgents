# server/routers/strategies.py
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis, AnalysisStrategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class StrategyOut(BaseModel):
    id: str
    analysis_id: str
    ticker: str
    ticker_name: Optional[str]
    trade_date: str
    direction: Optional[str]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    stop_loss_basis: Optional[str]
    target_price: Optional[float]
    target_price_basis: Optional[str]
    position_size: Optional[str]
    time_horizon: Optional[str]
    current_price: Optional[float]
    price_updated_at: Optional[datetime]
    status: str
    extraction_method: Optional[str]
    confidence: Optional[str]
    extraction_note: Optional[str]
    created_at: datetime
    closed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class StrategyPatch(BaseModel):
    status: Optional[str] = None   # "closed" to manually close


# ── Helpers ────────────────────────────────────────────────────────────────────

_EXPIRY_DAYS = 7


def _auto_expire(db: Session, row: AnalysisStrategy) -> None:
    """Mark strategy as expired if trade_date is older than EXPIRY_DAYS and still active."""
    if row.status != "active":
        return
    try:
        td = datetime.strptime(row.trade_date, "%Y-%m-%d")
        if datetime.utcnow() - td > timedelta(days=_EXPIRY_DAYS):
            row.status = "expired"
            db.commit()
    except Exception:
        pass


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=List[StrategyOut])
def list_strategies(db: Session = Depends(get_db)):
    """Return one strategy per ticker (the latest by trade_date then created_at),
    auto-expiring stale ones."""
    rows = db.query(AnalysisStrategy).order_by(
        AnalysisStrategy.trade_date.desc(),
        AnalysisStrategy.created_at.desc(),
    ).all()
    for row in rows:
        _auto_expire(db, row)
    # Deduplicate: keep only the first (= most recent) record per ticker
    seen: set[str] = set()
    unique = []
    for row in rows:
        if row.ticker not in seen:
            seen.add(row.ticker)
            unique.append(row)
    return unique


@router.post("/refresh", response_model=List[StrategyOut])
def refresh_prices(db: Session = Depends(get_db)):
    """Update current_price for all active strategies (synchronous, may be slow)."""
    from server.strategy_extractor import get_stock_current_price

    rows = db.query(AnalysisStrategy).filter(
        AnalysisStrategy.status.in_(["active", "expired"])
    ).all()

    updated = []
    for row in rows:
        try:
            price = get_stock_current_price(row.ticker)
            if price:
                row.current_price = price
                row.price_updated_at = datetime.utcnow()
        except Exception as e:
            logger.warning("refresh_prices: %s → %s", row.ticker, e)
        _auto_expire(db, row)
        updated.append(row)

    db.commit()
    return updated


@router.post("/backfill", response_model=dict)
def backfill(db: Session = Depends(get_db)):
    """
    One-time: extract strategy from every completed analysis that has no strategy yet.
    Returns counts of created / skipped / failed.
    """
    from server.strategy_extractor import build_strategy_from_analysis
    import uuid

    existing_ids = {s.analysis_id for s in db.query(AnalysisStrategy.analysis_id).all()}

    from server.models import AppSettings
    settings = db.get(AppSettings, 1)

    analyses = db.query(Analysis).filter(
        Analysis.status == "complete",
        Analysis.decision.isnot(None),
    ).all()

    created = skipped = failed = 0
    for rec in analyses:
        if rec.id in existing_ids:
            skipped += 1
            continue
        try:
            data = build_strategy_from_analysis(rec, settings=settings)
            if not data:
                skipped += 1
                continue
            strat = AnalysisStrategy(id=str(uuid.uuid4()), **data)
            db.add(strat)
            db.commit()
            created += 1
        except Exception as e:
            logger.error("backfill: analysis %s → %s", rec.id, e)
            db.rollback()
            failed += 1

    return {"created": created, "skipped": skipped, "failed": failed}


@router.post("/re-extract-all", response_model=dict)
def re_extract_all(db: Session = Depends(get_db)):
    """
    AI re-extract fields for ALL existing strategy records (regardless of existing data).
    Useful after upgrading from regex-only to AI extraction.
    Returns counts of updated / skipped / failed.
    """
    from server.strategy_extractor import build_strategy_from_analysis
    from server.models import AppSettings

    settings = db.get(AppSettings, 1)
    rows = db.query(AnalysisStrategy).all()

    updated = skipped = failed = 0
    for row in rows:
        record = db.get(Analysis, row.analysis_id)
        if not record:
            skipped += 1
            continue
        try:
            data = build_strategy_from_analysis(record, settings=settings)
            if not data:
                skipped += 1
                continue
            for k, v in data.items():
                if k not in ("analysis_id", "status"):
                    setattr(row, k, v)
            db.commit()
            updated += 1
        except Exception as e:
            logger.error("re_extract_all: strategy %s → %s", row.id, e)
            db.rollback()
            failed += 1

    return {"updated": updated, "skipped": skipped, "failed": failed}


@router.post("/{strategy_id}/re-extract", response_model=StrategyOut)
def re_extract(
    strategy_id: str,
    db: Session = Depends(get_db),
):
    """Re-run AI extraction for a single strategy record."""
    from server.strategy_extractor import build_strategy_from_analysis
    from server.models import AppSettings

    row = db.get(AnalysisStrategy, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    record = db.get(Analysis, row.analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")

    settings = db.get(AppSettings, 1)
    try:
        data = build_strategy_from_analysis(record, settings=settings)
        if not data:
            raise HTTPException(status_code=422, detail="No decision text found in analysis")
        for k, v in data.items():
            if k not in ("analysis_id", "status"):
                setattr(row, k, v)
        db.commit()
        db.refresh(row)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return row


@router.patch("/{strategy_id}", response_model=StrategyOut)
def patch_strategy(
    strategy_id: str,
    payload: StrategyPatch,
    db: Session = Depends(get_db),
):
    row = db.get(AnalysisStrategy, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if payload.status:
        row.status = payload.status
        if payload.status == "closed":
            row.closed_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row
