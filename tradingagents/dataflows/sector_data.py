"""AkShare-based sector / whole-market data provider for the A-share stock screener.

Provides cached, single-call snapshots used by the screening engine:
  - Industry board list           : ak.stock_board_industry_name_em()
  - Board constituents            : ak.stock_board_industry_cons_em(symbol=board)
  - Whole-market spot snapshot    : ak.stock_zh_a_spot_em()   (PE/PB/market-cap/turnover for ALL stocks)
  - ROE map (optional factor)     : ak.stock_yjbb_em(date)    (latest earnings report)
  - Money-flow map (optional)     : ak.stock_individual_fund_flow_rank(indicator="今日")

Ticker format: results expose Yahoo-Finance style tickers (600519.SS / 000001.SZ / 430047.BJ)
to stay consistent with the rest of the project.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Simple thread-safe TTL cache ────────────────────────────────────────────────

_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: str, ttl: float):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is None:
            return None
        ts, value = item
        if time.time() - ts > ttl:
            return None
        return value


def _cache_set(key: str, value: object):
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)


# ── Ticker helpers ──────────────────────────────────────────────────────────────

def code_to_yf(code: str) -> str:
    """6-digit A-share code -> Yahoo Finance ticker. 600519 -> 600519.SS"""
    c = str(code).strip().zfill(6)
    if c.startswith("6"):
        return f"{c}.SS"
    if c.startswith(("8", "4")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _to_float(v) -> Optional[float]:
    try:
        import pandas as pd
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── Industry boards ──────────────────────────────────────────────────────────────

def get_industry_boards(ttl: float = 600) -> list[dict]:
    """Return list of A-share industry boards (东方财富 行业板块).

    Each dict: {name, code, price, pct_change, total_mktcap, turnover, up, down}
    """
    cached = _cache_get("industry_boards", ttl)
    if cached is not None:
        return cached  # type: ignore

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed — sector screening unavailable")
        return []

    try:
        df = ak.stock_board_industry_name_em()
    except Exception as e:
        logger.warning("get_industry_boards failed: %s", e)
        return []

    if df is None or df.empty:
        return []

    boards: list[dict] = []
    for _, row in df.iterrows():
        boards.append({
            "name": str(row.get("板块名称", "")).strip(),
            "code": str(row.get("板块代码", "")).strip(),
            "price": _to_float(row.get("最新价")),
            "pct_change": _to_float(row.get("涨跌幅")),
            "total_mktcap": _to_float(row.get("总市值")),
            "turnover": _to_float(row.get("换手率")),
            "up": _to_float(row.get("上涨家数")),
            "down": _to_float(row.get("下跌家数")),
        })
    boards = [b for b in boards if b["name"]]
    _cache_set("industry_boards", boards)
    return boards


def get_board_constituents(board_name: str, ttl: float = 3600) -> list[str]:
    """Return list of 6-digit constituent codes for an industry board."""
    key = f"board_cons::{board_name}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached  # type: ignore

    try:
        import akshare as ak
    except ImportError:
        return []

    try:
        df = ak.stock_board_industry_cons_em(symbol=board_name)
    except Exception as e:
        logger.warning("get_board_constituents(%s) failed: %s", board_name, e)
        return []

    if df is None or df.empty:
        return []

    codes = [str(c).strip().zfill(6) for c in df.get("代码", []) if str(c).strip()]
    _cache_set(key, codes)
    return codes


# ── Whole-market spot snapshot ───────────────────────────────────────────────────

def get_market_spot(ttl: float = 600):
    """Return whole-market spot snapshot as a dict keyed by 6-digit code.

    value: {code, name, price, pct_change, amount, pe, pb, total_mktcap, float_mktcap, turnover}
    `amount` = 成交额 (CNY, liquidity proxy); `pe` = 市盈率-动态; `pb` = 市净率.
    """
    cached = _cache_get("market_spot", ttl)
    if cached is not None:
        return cached  # type: ignore

    try:
        import akshare as ak
    except ImportError:
        return {}

    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as e:
        logger.warning("get_market_spot failed: %s", e)
        return {}

    if df is None or df.empty:
        return {}

    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).strip().zfill(6)
        if not code or not code.isdigit():
            continue
        out[code] = {
            "code": code,
            "name": str(row.get("名称", "")).strip(),
            "price": _to_float(row.get("最新价")),
            "pct_change": _to_float(row.get("涨跌幅")),
            "amount": _to_float(row.get("成交额")),
            "pe": _to_float(row.get("市盈率-动态")),
            "pb": _to_float(row.get("市净率")),
            "total_mktcap": _to_float(row.get("总市值")),
            "float_mktcap": _to_float(row.get("流通市值")),
            "turnover": _to_float(row.get("换手率")),
        }
    _cache_set("market_spot", out)
    return out


# ── Optional factor: ROE (from latest earnings report) ───────────────────────────

def get_roe_map(ttl: float = 86400) -> dict[str, float]:
    """Return {6-digit code -> ROE(%)} from the most recent quarterly earnings report.

    Tries the last few quarter-ends until AkShare returns data. Best-effort: returns
    an empty dict on failure so the screener can degrade gracefully.
    """
    cached = _cache_get("roe_map", ttl)
    if cached is not None:
        return cached  # type: ignore

    try:
        import akshare as ak
    except ImportError:
        return {}

    today = datetime.now()
    # Candidate quarter-end report dates, most recent first
    candidates = []
    for year in (today.year, today.year - 1):
        for md in ("1231", "0930", "0630", "0331"):
            candidates.append(f"{year}{md}")
    candidates = [d for d in candidates if d <= today.strftime("%Y%m%d")]

    roe_map: dict[str, float] = {}
    for date_str in candidates:
        try:
            df = ak.stock_yjbb_em(date=date_str)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        roe_col = next((c for c in df.columns if "净资产收益率" in str(c)), None)
        code_col = next((c for c in df.columns if str(c) == "股票代码"), None)
        if not roe_col or not code_col:
            continue
        for _, row in df.iterrows():
            code = str(row.get(code_col, "")).strip().zfill(6)
            roe = _to_float(row.get(roe_col))
            if code and roe is not None:
                roe_map[code] = roe
        if roe_map:
            break

    _cache_set("roe_map", roe_map)
    return roe_map


# ── Optional factor: main-capital net inflow ─────────────────────────────────────

def get_moneyflow_map(ttl: float = 600) -> dict[str, float]:
    """Return {6-digit code -> 今日主力净流入(CNY)} for the whole market.

    Best-effort: returns empty dict on failure.
    """
    cached = _cache_get("moneyflow_map", ttl)
    if cached is not None:
        return cached  # type: ignore

    try:
        import akshare as ak
    except ImportError:
        return {}

    try:
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
    except Exception as e:
        logger.warning("get_moneyflow_map failed: %s", e)
        return {}

    if df is None or df.empty:
        return {}

    code_col = next((c for c in df.columns if str(c) == "代码"), None)
    flow_col = next((c for c in df.columns if "主力净流入-净额" in str(c)), None)
    if not code_col or not flow_col:
        return {}

    flow_map: dict[str, float] = {}
    for _, row in df.iterrows():
        code = str(row.get(code_col, "")).strip().zfill(6)
        flow = _to_float(row.get(flow_col))
        if code and flow is not None:
            flow_map[code] = flow

    _cache_set("moneyflow_map", flow_map)
    return flow_map


def is_tradeable(name: str) -> bool:
    """Filter out ST / *ST / 退市 / 停牌-flagged names."""
    n = (name or "").upper()
    bad = ("ST", "*ST", "退", "PT")
    return not any(b in n for b in bad)
