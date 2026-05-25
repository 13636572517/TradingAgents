# server/routers/stats.py
"""Aggregate usage statistics across all analyses."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def get_stats(db: Session = Depends(get_db)):
    """Return aggregate token/cost stats across all completed analyses."""
    rows = (
        db.query(Analysis)
        .filter(Analysis.status == "complete", Analysis.usage.isnot(None))
        .all()
    )

    total_analyses = db.query(Analysis).count()
    completed = len(rows)

    agg = {
        "total_analyses": total_analyses,
        "completed_analyses": completed,
        "quick": {"calls": 0, "tokens_in": 0, "tokens_out": 0, "tool_calls": 0, "cost_cny": 0.0},
        "deep":  {"calls": 0, "tokens_in": 0, "tokens_out": 0, "tool_calls": 0, "cost_cny": 0.0},
        "total_tokens": 0,
        "total_cost_cny": 0.0,
        "by_date": {},   # YYYY-MM-DD → {tokens, analyses, cost_cny}
    }

    for row in rows:
        u = row.usage or {}
        for role in ("quick", "deep"):
            slot = u.get(role, {})
            agg[role]["calls"]      += slot.get("calls", 0)
            agg[role]["tokens_in"]  += slot.get("tokens_in", 0)
            agg[role]["tokens_out"] += slot.get("tokens_out", 0)
            agg[role]["tool_calls"] += slot.get("tool_calls", 0)
            agg[role]["cost_cny"]   += slot.get("cost_cny", 0.0)

        # Calculate total tokens and cost for this analysis
        tokens = (
            u.get("quick", {}).get("tokens_in", 0)  + u.get("quick", {}).get("tokens_out", 0) +
            u.get("deep",  {}).get("tokens_in", 0)  + u.get("deep",  {}).get("tokens_out", 0)
        )
        cost = u.get("total_cost_cny", 0.0)
        agg["total_tokens"] += tokens
        agg["total_cost_cny"] += cost

        # Daily breakdown
        date_key = row.created_at.strftime("%Y-%m-%d") if row.created_at else "unknown"
        day = agg["by_date"].setdefault(date_key, {"tokens": 0, "analyses": 0, "cost_cny": 0.0})
        day["tokens"]     += tokens
        day["analyses"]   += 1
        day["cost_cny"]   += cost

    agg["total_cost_cny"] = round(agg["total_cost_cny"], 4)
    agg["quick"]["cost_cny"] = round(agg["quick"]["cost_cny"], 4)
    agg["deep"]["cost_cny"]  = round(agg["deep"]["cost_cny"], 4)

    return agg
