# server/routers/pricing.py
"""Endpoints for managing per-model LLM pricing.

POST /api/pricing/import-md   — parse and store pricing from Markdown text
GET  /api/pricing             — list all stored model pricing
POST /api/pricing/recalculate — recalculate costs for all existing analyses
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis, ModelPricing
from server.pricing_utils import parse_cn_pricing_md, recalc_usage_cost

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PricingTier(BaseModel):
    max_k: Optional[int]      # upper bound in K tokens; None = unlimited
    input_price: float        # CNY per million input tokens
    output_price: float       # CNY per million output tokens


class ModelPricingOut(BaseModel):
    model_id: str
    region: str
    tiers: List[PricingTier]
    updated_at: Optional[str]


class ImportMdPayload(BaseModel):
    markdown: str             # raw Markdown text from Alibaba Cloud pricing page
    region: str = "cn"        # region tag to store (default: China mainland)


class ImportResult(BaseModel):
    imported: int             # models newly imported or updated
    skipped: int              # models with no valid tiers parsed
    models: List[str]         # list of imported model IDs


class RecalcResult(BaseModel):
    updated: int              # analyses whose cost was updated
    skipped: int              # analyses skipped (no usage or no pricing match)
    total_cost_delta: float   # sum of cost differences (new - old)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/import-md", response_model=ImportResult)
def import_pricing_md(payload: ImportMdPayload, db: Session = Depends(get_db)):
    """Parse Alibaba Cloud Bailian pricing Markdown and store per-model tiers."""
    if not payload.markdown.strip():
        raise HTTPException(status_code=400, detail="Markdown text is empty")

    parsed = parse_cn_pricing_md(payload.markdown)
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail='未能解析到任何价格数据。请从阿里云百炼价格页面复制包含模型ID和"元"单价的表格内容。',
        )

    imported_ids: list[str] = []
    skipped = 0

    for model_id, tiers in parsed.items():
        if not tiers:
            skipped += 1
            continue
        row = db.query(ModelPricing).filter(ModelPricing.model_id == model_id).first()
        if row:
            row.tiers = tiers
            row.region = payload.region
            row.updated_at = datetime.utcnow()
        else:
            row = ModelPricing(
                model_id=model_id,
                region=payload.region,
                tiers=tiers,
                updated_at=datetime.utcnow(),
            )
            db.add(row)
        imported_ids.append(model_id)

    db.commit()
    logger.info("Pricing import: %d models stored, %d skipped", len(imported_ids), skipped)
    return ImportResult(imported=len(imported_ids), skipped=skipped, models=sorted(imported_ids))


@router.get("", response_model=List[ModelPricingOut])
def list_pricing(db: Session = Depends(get_db)):
    """Return all stored model pricing records."""
    rows = db.query(ModelPricing).order_by(ModelPricing.model_id).all()
    return [
        ModelPricingOut(
            model_id=r.model_id,
            region=r.region or "cn",
            tiers=[PricingTier(**t) for t in (r.tiers or [])],
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in rows
    ]


@router.delete("/{model_id}")
def delete_pricing(model_id: str, db: Session = Depends(get_db)):
    """Delete pricing for a specific model."""
    row = db.query(ModelPricing).filter(ModelPricing.model_id == model_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    db.delete(row)
    db.commit()
    return {"deleted": model_id}


@router.post("/recalculate", response_model=RecalcResult)
def recalculate_all_costs(db: Session = Depends(get_db)):
    """Recalculate cost_cny for all analyses using current model pricing table.

    Only analyses with usage data are processed. If no pricing is found for a
    model, its existing cost_cny is left unchanged.
    """
    analyses = db.query(Analysis).filter(Analysis.usage.isnot(None)).all()
    updated = 0
    skipped = 0
    total_delta = 0.0

    for analysis in analyses:
        usage = analysis.usage
        if not usage or not isinstance(usage, dict):
            skipped += 1
            continue

        old_total = usage.get("total_cost_cny", 0.0) or 0.0
        new_usage = recalc_usage_cost(usage, db)
        new_total = new_usage.get("total_cost_cny", 0.0)

        # Only write back if something actually changed
        any_pricing_found = any(
            new_usage.get(s, {}).get("cost_cny", 0) != usage.get(s, {}).get("cost_cny", 0)
            for s in ("quick", "deep")
        )
        if any_pricing_found:
            analysis.usage = new_usage
            total_delta += new_total - old_total
            updated += 1
        else:
            skipped += 1

    db.commit()
    logger.info(
        "Cost recalculate: %d updated, %d skipped, delta=%.4f CNY",
        updated, skipped, total_delta,
    )
    return RecalcResult(
        updated=updated,
        skipped=skipped,
        total_cost_delta=round(total_delta, 4),
    )
