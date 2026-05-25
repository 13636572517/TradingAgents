# server/routers/stats.py
"""Aggregate usage statistics across all analyses."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def get_stats(db: Session = Depends(get_db)):
    """Return aggregate token stats across all completed analyses."""
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
        "quick": {"calls": 0, "tokens_in": 0, "tokens_out": 0, "tool_calls": 0},
        "deep":  {"calls": 0, "tokens_in": 0, "tokens_out": 0, "tool_calls": 0},
        "total_tokens": 0,
        "by_date": {},   # YYYY-MM-DD → {tokens, analyses}
    }

    for row in rows:
        u = row.usage or {}
        for role in ("quick", "deep"):
            slot = u.get(role, {})
            agg[role]["calls"]      += slot.get("calls", 0)
            agg[role]["tokens_in"]  += slot.get("tokens_in", 0)
            agg[role]["tokens_out"] += slot.get("tokens_out", 0)
            agg[role]["tool_calls"] += slot.get("tool_calls", 0)

        # Calculate total tokens for this analysis
        tokens = (
            u.get("quick", {}).get("tokens_in", 0)  + u.get("quick", {}).get("tokens_out", 0) +
            u.get("deep",  {}).get("tokens_in", 0)  + u.get("deep",  {}).get("tokens_out", 0)
        )
        agg["total_tokens"] += tokens

        # Daily breakdown
        date_key = row.created_at.strftime("%Y-%m-%d") if row.created_at else "unknown"
        day = agg["by_date"].setdefault(date_key, {"tokens": 0, "analyses": 0})
        day["tokens"]     += tokens
        day["analyses"]   += 1

    return agg
