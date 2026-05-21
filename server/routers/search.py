# server/routers/search.py
"""Stock + ETF search endpoint for ticker autocomplete.

Data sources (loaded once, cached in memory):
  - A-share stocks : ak.stock_info_a_code_name()   ~5 500 records
  - A-share ETFs   : ak.fund_etf_spot_em()          ~1 500 records
"""
import logging
from functools import lru_cache

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


def _suffix(code: str) -> str:
    """Return Yahoo Finance exchange suffix for a 6-digit A-share/ETF code."""
    c = code.strip()
    if c.startswith("6"):
        return ".SS"
    if c.startswith(("8", "4")):
        return ".BJ"
    return ".SZ"


@lru_cache(maxsize=1)
def _load_securities() -> list:
    """Load A-share stocks + ETFs from AkShare. Cached for process lifetime."""
    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed — search will return no results")
        return []

    items: list = []
    seen: set = set()

    def _add(code: str, name: str):
        code = str(code).strip().zfill(6)
        name = str(name).strip()
        if not code or not name or code in seen:
            return
        seen.add(code)
        suffix = _suffix(code)
        items.append({
            "ticker": f"{code}{suffix}",
            "name": name,
            "code": code,
            "market": "沪市" if suffix == ".SS" else ("深市" if suffix == ".SZ" else "北交所"),
        })

    # ── A-share stocks ────────────────────────────────────────────────────
    try:
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                _add(row["code"], row["name"])
            logger.info("Loaded %d A-share stocks", len(items))
    except Exception as e:
        logger.warning("Failed to load stock list: %s", e)

    # ── A-share ETFs ──────────────────────────────────────────────────────
    etf_before = len(items)
    try:
        df = ak.fund_etf_spot_em()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                _add(str(row.get("代码", "")), str(row.get("名称", "")))
            logger.info("Loaded %d ETFs (total %d)", len(items) - etf_before, len(items))
    except Exception as e:
        logger.warning("Failed to load ETF list: %s", e)

    return items


@router.get("")
def search_stocks(
    q: str = Query("", min_length=1, max_length=20),
    limit: int = Query(10, ge=1, le=30),
):
    """Search stocks + ETFs by code or name, return up to `limit` matches."""
    q = q.strip()
    if not q:
        return []

    securities = _load_securities()
    q_lower = q.lower()

    exact, starts_code, starts_name, contains_name = [], [], [], []

    for s in securities:
        code = s["code"]
        name_lower = s["name"].lower()
        ticker_lower = s["ticker"].lower()

        if code == q.zfill(6) or ticker_lower == q_lower:
            exact.append(s)
        elif code.startswith(q) or ticker_lower.startswith(q_lower):
            starts_code.append(s)
        elif name_lower.startswith(q_lower):
            starts_name.append(s)
        elif q_lower in name_lower:
            contains_name.append(s)

    seen_tickers, results = set(), []
    for group in (exact, starts_code, starts_name, contains_name):
        for s in group:
            if s["ticker"] not in seen_tickers:
                seen_tickers.add(s["ticker"])
                results.append(s)
            if len(results) >= limit:
                return results

    return results
