"""Sector / whole-market data provider for the A-share stock screener.

The screener needs three bulk feeds:
  1. Industry board list      — sector/industry universes from TickFlow
  2. Board constituents       — symbols inside each universe from TickFlow
  3. Whole-market spot snapshot — real-time quotes from TickFlow (1 request via universes)

TickFlow is a RESTful authenticated API (no IP rate-limit), making it stable
for server-side batch jobs.  The provider chain falls back to akshare and
then JoinQuant when TickFlow is unavailable.

  - Industry board list   : TickFlow  /v1/universes  → akshare
  - Board constituents    : TickFlow  /v1/universes/{id}  →  akshare
  - Whole-market spot      : TickFlow  POST /v1/quotes with ``universes=["CN_Equity_A"]``
  - ROE map (optional)    : ak.stock_yjbb_em(date)    best-effort, AkShare
  - Money-flow (optional) : ak.stock_individual_fund_flow_rank  best-effort

Ticker format: results expose Yahoo-Finance style tickers
(600519.SS / 000001.SZ / 430047.BJ) to stay consistent with the project.
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


# ── Provider-chain chooser ──────────────────────────────────────────────────────

def _first_nonempty(label: str, providers: list[tuple]):
    """Try each ``(name, fn)`` provider in order; return the first truthy result.

    Mirrors the project's vendor-fallback philosophy (see dataflows/interface.py
    ``route_to_vendor``): a provider that raises or returns empty is logged and the
    next one is tried. Returns None when every provider is exhausted.
    """
    for name, fn in providers:
        try:
            res = fn()
        except Exception as e:
            logger.warning("%s: provider '%s' failed (%s) — falling back", label, name, e)
            continue
        if res:
            logger.info("%s: served by '%s' (%d items)", label, name, len(res))
            return res
        logger.info("%s: provider '%s' empty — falling back", label, name)
    logger.warning("%s: all providers exhausted", label)
    return None


# ── TickFlow board discovery helpers ────────────────────────────────────────────

# Known TickFlow universe IDs that map to A-share industry boards.
# These are discovered dynamically from /v1/universes but we maintain a
# fallback list in case TickFlow returns no sector universes.
_SECTOR_UNIVERSE_PREFIXES = ("CN_Sector", "CN_Industry")


def _discover_sector_universes() -> list[dict]:
    """Discover industry/sector universes from TickFlow.

    Returns list of {id, name, symbol_count}.
    """
    from tradingagents.dataflows.tickflow_data import tf_universes
    all_universes = tf_universes()
    sectors = []
    for u in all_universes:
        cat = (u.get("category") or "").lower()
        uid = u.get("id") or ""
        name = u.get("name") or ""
        # Match sector/industry universes
        if any(prefix in uid for prefix in _SECTOR_UNIVERSE_PREFIXES):
            sectors.append({
                "id": uid,
                "name": name or uid,
                "symbol_count": u.get("symbol_count", 0),
            })
        elif "sector" in cat or "industry" in cat:
            sectors.append({
                "id": uid,
                "name": name or uid,
                "symbol_count": u.get("symbol_count", 0),
            })
    return sectors


# ── Industry boards (TickFlow → AkShare-EM) ────────────────────────────────────

def get_industry_boards(ttl: float = 600) -> list[dict]:
    """Return list of A-share industry boards.

    Each dict: {name, code, price, pct_change, total_mktcap, turnover, up, down}

    Provider chain mirrors interface.py routing:
      tickflow → akshare  (mairui/baostock/joinquant/futu don't support board lists)
    """
    cached = _cache_get("industry_boards", ttl)
    if cached is not None:
        return cached  # type: ignore
    boards = _first_nonempty("industry_boards", [
        ("tickflow", _boards_tickflow),
        ("akshare_em", _boards_akshare_em),
    ]) or []
    if boards:
        _cache_set("industry_boards", boards)
    return boards


def _boards_tickflow() -> list[dict]:
    """Discover industry boards from TickFlow universes.

    Returns board list with name/code. Price data is enriched from batch quotes.
    """
    sectors = _discover_sector_universes()
    if not sectors:
        return []

    boards: list[dict] = []
    for s in sectors:
        boards.append({
            "name": s["name"],
            "code": s["id"],
            "price": None,
            "pct_change": None,
            "total_mktcap": None,
            "turnover": None,
            "up": None,
            "down": None,
        })
    return boards


def _boards_akshare_em() -> list[dict]:
    import akshare as ak
    df = ak.stock_board_industry_name_em()
    if df is None or df.empty:
        return []
    boards: list[dict] = []
    for _, row in df.iterrows():
        name = str(row.get("板块名称", "")).strip()
        if not name:
            continue
        boards.append({
            "name": name,
            "code": str(row.get("板块代码", "")).strip(),
            "price": _to_float(row.get("最新价")),
            "pct_change": _to_float(row.get("涨跌幅")),
            "total_mktcap": _to_float(row.get("总市值")),
            "turnover": _to_float(row.get("换手率")),
            "up": _to_float(row.get("上涨家数")),
            "down": _to_float(row.get("下跌家数")),
        })
    return boards


def _board_code_for(board_name: str) -> Optional[str]:
    for b in get_industry_boards():
        if b["name"] == board_name:
            return b.get("code") or None
    return None


# ── Board constituents (TickFlow → AkShare-EM) ─────────────────────────────────

def get_board_constituents(board_name: str, ttl: float = 3600) -> list[str]:
    """Return list of 6-digit constituent codes for an industry board."""
    key = f"board_cons::{board_name}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached  # type: ignore
    codes = _first_nonempty(f"constituents[{board_name}]", [
        ("tickflow", lambda: _cons_tickflow(board_name)),
        ("akshare_em", lambda: _cons_akshare_em(board_name)),
    ]) or []
    if codes:
        _cache_set(key, codes)
    return codes


def _cons_tickflow(board_name: str) -> list[str]:
    """Get board constituents from TickFlow universe detail.

    The board_name is expected to match a TickFlow universe ID.
    """
    from tradingagents.dataflows.tickflow_data import tf_universe_detail
    detail = tf_universe_detail(board_name)
    if not detail:
        return []
    symbols = detail.get("symbols", [])
    # Convert TickFlow symbols (600000.SH) to 6-digit codes (600000)
    codes = []
    for sym in symbols:
        six = sym.split(".")[0]
        if six and six.isdigit():
            codes.append(six.zfill(6))
    return codes


def _cons_akshare_em(board_name: str) -> list[str]:
    import akshare as ak
    df = ak.stock_board_industry_cons_em(symbol=board_name)
    if df is None or df.empty:
        return []
    return [str(c).strip().zfill(6) for c in df.get("代码", []) if str(c).strip()]


# ── Whole-market spot snapshot (TickFlow universe → AkShare-EM → JoinQuant) ────


def get_market_spot(ttl: float = 600):
    """Return whole-market spot snapshot as a dict keyed by 6-digit code.

    value: {code, name, price, pct_change, amount, pe, pb, total_mktcap, float_mktcap, turnover}
    `amount` = 成交额 (CNY, liquidity proxy); `pe` = 市盈率-动态; `pb` = 市净率.

    Provider chain: TickFlow (universe-based, 1 request) → AkShare(EM) → JoinQuant.
    TickFlow's ``POST /v1/quotes`` with ``universes`` param fetches the entire
    CN_Equity_A pool in a single API call — no pagination needed.
    """
    cached = _cache_get("market_spot", ttl)
    if cached is not None:
        return cached  # type: ignore
    spot = _first_nonempty("market_spot", [
        ("tickflow", _spot_tickflow),
        ("akshare_em", _spot_akshare_em),
        ("joinquant", _spot_jq),
    ]) or {}
    if spot:
        _cache_set("market_spot", spot)
    return spot


def _spot_tickflow() -> dict:
    """Whole-market snapshot via TickFlow universe-based quotes.

    Uses ``POST /v1/quotes`` with ``universes=["CN_Equity_A"]`` to fetch
    all ~5,500 A-shares in a **single request** (no pagination, no rate-limit).
    Returns dict keyed by 6-digit code.
    """
    from tradingagents.dataflows.tickflow_data import tf_universe_quotes

    logger.info("_spot_tickflow: fetching CN_Equity_A universe via single request…")
    out = tf_universe_quotes(["CN_Equity_A"])
    if out:
        logger.info("_spot_tickflow: %d symbols fetched", len(out))
    else:
        logger.warning("_spot_tickflow: returned empty — universe may not exist or API issue")
    return out


def _spot_akshare_em() -> dict:
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
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
    return out


def _spot_jq() -> dict:
    """Whole-market snapshot via JoinQuant — independent of TickFlow/East Money.

    Three queries (within the free 500/day quota): all-securities (names),
    valuation table (PE/PB/market-cap, one shot), and latest close+amount.
    """
    from tradingagents.dataflows.jq_data import _ensure_auth, _JQ_LOCK
    import jqdatasdk as jq
    from jqdatasdk import query, valuation

    with _JQ_LOCK:
        _ensure_auth()
        secs = jq.get_all_securities(types=["stock"])
        name_map = {str(idx).split(".")[0]: row["display_name"]
                    for idx, row in secs.iterrows()}
        vdf = jq.get_fundamentals(query(valuation), date=None)
        pdf = jq.get_price(list(secs.index), count=1, fields=["close", "money"],
                           panel=False, fill_paused=False)

    pa: dict[str, tuple] = {}
    if pdf is not None and not pdf.empty:
        for _, r in pdf.iterrows():
            c6 = str(r.get("code", "")).split(".")[0].zfill(6)
            pa[c6] = (_to_float(r.get("close")), _to_float(r.get("money")))

    if vdf is None or vdf.empty:
        return {}
    out: dict[str, dict] = {}
    for _, r in vdf.iterrows():
        c6 = str(r.get("code", "")).split(".")[0].zfill(6)
        if not c6.isdigit():
            continue
        price, amount = pa.get(c6, (None, None))
        mc = _to_float(r.get("market_cap"))               # JoinQuant: 亿元
        fmc = _to_float(r.get("circulating_market_cap"))  # JoinQuant: 亿元
        out[c6] = {
            "code": c6,
            "name": name_map.get(c6, ""),
            "price": price,
            "pct_change": None,
            "amount": amount,
            "pe": _to_float(r.get("pe_ratio")),
            "pb": _to_float(r.get("pb_ratio")),
            "total_mktcap": mc * 1e8 if mc is not None else None,
            "float_mktcap": fmc * 1e8 if fmc is not None else None,
            "turnover": _to_float(r.get("turnover_ratio")),
        }
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
