# server/routers/search.py
"""Stock + ETF search endpoint for ticker autocomplete.

Data sources (loaded once, cached in memory):
  - A-share stocks : ak.stock_info_a_code_name()   ~5 500 records
  - A-share ETFs   : ak.fund_etf_spot_em()          ~1 500 records
  - HK stocks      : ak.stock_hk_spot_em()          ~3 000 records
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
    """Load A-share stocks + ETFs + HK stocks from AkShare. Cached for process lifetime."""
    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed — search will return no results")
        return []

    items: list = []
    seen: set = set()

    def _add(code: str, name: str, suffix: str = None, market: str = None):
        code = str(code).strip()
        name = str(name).strip()
        if not code or not name or code in seen:
            return
        seen.add(code)
        if suffix is None:
            suffix = _suffix(code) if len(code) == 6 and code.isdigit() else ""
        if market is None:
            market = "沪市" if suffix == ".SS" else ("深市" if suffix == ".SZ" else "北交所" if suffix == ".BJ" else "港股")
        items.append({
            "ticker": f"{code}{suffix}",
            "name": name,
            "code": code,
            "market": market,
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

    # ── HK stocks ─────────────────────────────────────────────────────────
    hk_before = len(items)
    try:
        # Load HK stocks from Futu OpenD (more reliable than akshare on servers)
        from tradingagents.dataflows.futu_data import get_futu_stock_list
        hk_stocks = get_futu_stock_list(market="HK")
        if hk_stocks:
            for code, name in hk_stocks:
                code = str(code).strip()
                name = str(name).strip()
                if code and len(code) >= 4:
                    # Keep 4-5 digit code (e.g., 02513)
                    code = code[:5].zfill(4)
                    _add(code, name, suffix=".HK", market="港股")
            logger.info("Loaded %d HK stocks from Futu (total %d)", len(items) - hk_before, len(items))
        else:
            logger.warning("Futu returned empty HK stock list")
    except ImportError:
        logger.debug("Futu not available for HK stock list")
    except Exception as e:
        logger.warning("Failed to load HK stock list from Futu: %s", e)

    return items


@router.get("")
def search_stocks(
    q: str = Query("", min_length=1, max_length=20),
    limit: int = Query(10, ge=1, le=30),
):
    """Search stocks + ETFs by code or name, return up to `limit` matches.
    
    Data sources:
      - A-share stocks + ETFs: AkShare
      - HK stocks: Futu OpenD (loaded once, cached)
    """
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
