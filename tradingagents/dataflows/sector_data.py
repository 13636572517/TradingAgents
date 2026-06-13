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
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Cross-process TTL cache (Redis when available, in-memory fallback) ─────────
#
# Whole-market snapshots and per-board member lists are expensive to compute
# (full TickFlow universe + financials + instruments fan-out). The screener
# runs inside the Celery worker, the detail page reads from the API server —
# two processes that would otherwise each maintain a cold in-memory cache and
# re-download the same data. Backing the cache with Redis means both processes
# share the same hot snapshot for the configured TTL.

def _cache_get(key: str, ttl: float):
    from .cache_store import shared_get_json
    return shared_get_json(f"sector_data:{key}", ttl)


def _cache_set(key: str, value: object, ttl_seconds: int = 600):
    from .cache_store import shared_set_json
    shared_set_json(f"sector_data:{key}", value, ttl_seconds=ttl_seconds)


# ── Ticker helpers ──────────────────────────────────────────────────────────────

def code_to_yf(code: str) -> str:
    """6-digit A-share code -> Yahoo Finance ticker. 600519 -> 600519.SS

    北交所 (Beijing) codes are 4xxxxx / 8xxxxx and the newer 920xxx range.
    """
    c = str(code).strip().zfill(6)
    if c.startswith("6"):
        return f"{c}.SS"
    if c.startswith(("4", "8", "92")):
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

# TickFlow exposes 申万 (Shenwan) industry classifications as universes under
# CN_Equity_SW{level}_* prefixes. Each level has many fragment pools that share
# the same name (e.g. "SW2基础化工" appears many times). We GROUP fragments by
# name into real boards and union their constituents.
_TF_BOARD_IDS: dict[str, list[str]] = {}   # name → [universe ids]


def _discover_boards(level: int = 1) -> list[dict]:
    """Discover 申万 industry boards from TickFlow at the given level (1/2/3).

    Merges same-name fragment universes. Returns list of {name, ids, symbol_count}.
    Also refreshes ``_TF_BOARD_IDS`` for constituent lookups.
    """
    from tradingagents.dataflows.tickflow_data import tf_universes
    prefix = f"CN_Equity_SW{level}_"
    tag = f"SW{level}"
    groups: dict[str, dict] = {}
    for u in tf_universes():
        uid = u.get("id") or ""
        if not uid.startswith(prefix):
            continue
        name = (u.get("name") or uid).strip()
        if name.upper().startswith(tag):
            name = name[len(tag):].strip()
        name = name or uid
        g = groups.setdefault(name, {"name": name, "ids": [], "symbol_count": 0})
        g["ids"].append(uid)
        g["symbol_count"] += u.get("symbol_count", 0) or 0
    # Merge into global cache (level-specific keys)
    for name, g in groups.items():
        _TF_BOARD_IDS[f"{tag}:{name}"] = g["ids"]
    return list(groups.values())


# ── Industry boards (TickFlow → AkShare-EM) ────────────────────────────────────

def get_industry_boards(level: int = 1, ttl: float = 600) -> list[dict]:
    """Return list of A-share industry boards at the given Shenwan level (1=一级, 2=二级).

    Each dict: {name, code, price, pct_change, total_mktcap, turnover, up, down}
    """
    cached = _cache_get(f"industry_boards_sw{level}", ttl)
    if cached is not None:
        return cached  # type: ignore
    boards = _first_nonempty(f"industry_boards_sw{level}", [
        ("tickflow", lambda: _boards_tickflow(level)),
        ("akshare_em", _boards_akshare_em),
    ]) or []
    if boards:
        _cache_set(f"industry_boards_sw{level}", boards, int(ttl))
    return boards


def _boards_tickflow(level: int = 1) -> list[dict]:
    """Discover industry boards from TickFlow universes."""
    sectors = _discover_boards(level)
    if not sectors:
        return []
    tag = f"SW{level}"
    boards: list[dict] = []
    for s in sectors:
        boards.append({
            "name": s["name"],
            "code": f"{tag}:{s['name']}",   # matches _TF_BOARD_IDS key
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
        _cache_set(key, codes, int(ttl))
    return codes


def _cons_tickflow(board_name: str) -> list[str]:
    """Get board constituents by unioning every TickFlow fragment universe of a board.

    ``board_name`` may be prefixed with ``SW1:`` or ``SW2:`` to indicate the level.
    If no prefix, defaults to SW1.
    """
    from tradingagents.dataflows.tickflow_data import tf_universe_symbols

    level = 1
    key = board_name
    if board_name.startswith("SW1:"):
        level = 1
        key = board_name[4:]
    elif board_name.startswith("SW2:"):
        level = 2
        key = board_name[4:]

    # Build the lookup key used in _TF_BOARD_IDS
    lookup_key = f"SW{level}:{key}"

    ids = _TF_BOARD_IDS.get(lookup_key)
    if ids is None:
        # Mapping not built yet — rebuild it.
        _discover_boards(level)
        ids = _TF_BOARD_IDS.get(lookup_key, [])
    if not ids:
        return []

    # Single quotes call for all fragment universes of this board
    symbols = tf_universe_symbols(ids)
    codes = []
    seen: set[str] = set()
    for sym in symbols:
        six = sym.split(".")[0]
        if six and six.isdigit():
            six = six.zfill(6)
            if six not in seen:
                seen.add(six)
                codes.append(six)
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

    Provider chain: TickFlow (Expert: quotes + instruments + financials) →
    AkShare(EM) → JoinQuant. TickFlow quotes carry only price/volume, so PE/PB/
    market-cap are computed here from share counts and per-share financials.
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
        _cache_set("market_spot", spot, int(ttl))
    return spot


def _spot_tickflow() -> dict:
    """Whole-market valuation snapshot assembled from three TickFlow batch feeds.

      - universe quotes  → price / amount / turnover / name / pct_change  (1 request)
      - instruments      → total & float shares → market cap              (~28 requests)
      - financials       → bps → PB, eps → PE (annualised), roe           (~56 requests)

    TickFlow quotes carry only price/volume, so the East-Money-equivalent valuation
    fields (pe / pb / total_mktcap) are derived here. Returns dict keyed by 6-digit code.
    """
    from tradingagents.dataflows.tickflow_data import (
        _post, tf_instruments, tf_financials_valuation)

    resp = _post("quotes", {"universes": ["CN_Equity_A"]})
    items = resp.get("data", []) or []
    if not items:
        return {}

    quotes: dict[str, tuple] = {}   # 6-digit -> (tf_symbol, item)
    tf_syms: list[str] = []
    for it in items:
        sym = it.get("symbol", "")
        six = sym.split(".")[0].zfill(6)
        if not six.isdigit():
            continue
        quotes[six] = (sym, it)
        tf_syms.append(sym)
    logger.info("_spot_tickflow: %d quotes; fetching shares + financials…", len(tf_syms))

    instr = tf_instruments(tf_syms)
    fin = tf_financials_valuation(tf_syms)
    logger.info("_spot_tickflow: enriched %d instruments, %d financials",
                len(instr), len(fin))

    out: dict[str, dict] = {}
    for six, (sym, it) in quotes.items():
        ext = it.get("ext") or {}
        price = _to_float(it.get("last_price"))
        im = instr.get(six) or {}
        fm = fin.get(six) or {}
        tshare = _to_float(im.get("total_shares"))
        fshare = _to_float(im.get("float_shares"))
        bps = _to_float(fm.get("bps"))
        eps_ttm = _to_float(fm.get("eps_ttm"))
        out[six] = {
            "code": six,
            "name": ext.get("name") or im.get("name") or "",
            "price": price,
            "pct_change": _pct(ext.get("change_pct")),
            "amount": _to_float(it.get("amount")),
            "pe": round(price / eps_ttm, 2) if (price and eps_ttm and eps_ttm > 0) else None,
            "pb": (price / bps) if (price and bps and bps > 0) else None,
            "total_mktcap": (price * tshare) if (price and tshare) else None,
            "float_mktcap": (price * fshare) if (price and fshare) else None,
            "turnover": _pct(ext.get("turnover_rate")),
            "roe": _to_float(fm.get("roe")),
            "net_profit_yoy": _to_float(fm.get("net_profit_yoy")),
            "debt_ratio": _to_float(fm.get("debt_ratio")),
            "gross_margin": _to_float(fm.get("gross_margin")),
            "ocf_to_revenue": _to_float(fm.get("ocf_to_revenue")),
            "eps_ttm": eps_ttm,
            "bps": bps,
        }
    return out


def _pct(v) -> Optional[float]:
    """TickFlow returns change_pct / turnover_rate as fractions (0.0096); the
    screener/snapshots use percent numbers (0.96), matching East Money/AkShare."""
    f = _to_float(v)
    return f * 100 if f is not None else None


# ── Per-board snapshot (drill-down for the screener detail page) ────────────────

def get_board_members_snapshot(board_name: str, level: int = 1,
                                ttl: float = 300) -> list[dict]:
    """Enriched list of every constituent stock for a single SW board.

    Scoped per-board (1 quotes call + 1-2 financials/instruments batches)
    rather than reusing get_market_spot, so the API server can render the
    detail page without paying for a whole-market refresh when its cache is
    cold. Cached for ``ttl`` seconds to keep repeated clicks cheap.

    Returns a list of {code, name, ticker, price, pct_change, amount, pe, pb,
    roe, total_mktcap} dicts. Empty list if the board can't be resolved.
    """
    cache_key = f"board_members:{level}:{board_name}"
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached  # type: ignore

    from tradingagents.dataflows.tickflow_data import (
        _post, tf_instruments, tf_financials_valuation)

    key = f"SW{level}:{board_name}"
    ids = _TF_BOARD_IDS.get(key)
    if ids is None:
        _discover_boards(level)
        ids = _TF_BOARD_IDS.get(key, [])
    if not ids:
        return []

    try:
        resp = _post("quotes", {"universes": ids})
    except Exception as e:
        logger.warning("get_board_members_snapshot: quotes failed for %s — %s",
                       key, e)
        return []
    items = resp.get("data", []) or []

    quotes: dict[str, tuple] = {}
    tf_syms: list[str] = []
    for it in items:
        sym = it.get("symbol", "")
        six = sym.split(".")[0].zfill(6)
        if not six.isdigit() or six in quotes:
            continue
        quotes[six] = (sym, it)
        tf_syms.append(sym)
    if not tf_syms:
        return []

    instr = tf_instruments(tf_syms)
    fin = tf_financials_valuation(tf_syms)

    members: list[dict] = []
    for six, (sym, it) in quotes.items():
        ext = it.get("ext") or {}
        price = _to_float(it.get("last_price"))
        im = instr.get(six) or {}
        fm = fin.get(six) or {}
        tshare = _to_float(im.get("total_shares"))
        bps = _to_float(fm.get("bps"))
        eps_ttm = _to_float(fm.get("eps_ttm"))
        members.append({
            "code": six,
            "ticker": code_to_yf(six),
            "name": ext.get("name") or im.get("name") or "",
            "price": price,
            "pct_change": _pct(ext.get("change_pct")),
            "amount": _to_float(it.get("amount")),
            "pe": round(price / eps_ttm, 2) if (price and eps_ttm and eps_ttm > 0) else None,
            "pb": round(price / bps, 4) if (price and bps and bps > 0) else None,
            "total_mktcap": (price * tshare) if (price and tshare) else None,
            "roe": _to_float(fm.get("roe")),
        })
    members.sort(key=lambda m: -(m.get("total_mktcap") or 0))
    _cache_set(cache_key, members, int(ttl))
    return members


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
    """Return {6-digit code -> ROE(%)}.

    Preferred source is the ROE already attached to the whole-market spot snapshot
    (TickFlow financials), which avoids a second data round-trip. Falls back to the
    AkShare earnings report. Best-effort: returns an empty dict on failure so the
    screener can degrade gracefully.
    """
    cached = _cache_get("roe_map", ttl)
    if cached is not None:
        return cached  # type: ignore

    # Prefer ROE carried by the spot snapshot (already fetched for valuation).
    spot = get_market_spot()
    roe_map = {c: v["roe"] for c, v in spot.items()
               if isinstance(v, dict) and v.get("roe") is not None}
    if roe_map:
        _cache_set("roe_map", roe_map, int(ttl))
        return roe_map

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

    _cache_set("roe_map", roe_map, int(ttl))
    return roe_map


# ── Optional factor: main-capital net inflow ─────────────────────────────────────

# Main-capital net-inflow is only sourced from East Money, which permanently
# rate-limits the production server IP. Flip this on if a working source exists;
# otherwise the screener simply drops the 15% inflow factor (graceful degradation)
# instead of wasting a slow, always-failing request on every run.
_MONEYFLOW_ENABLED = False


def get_moneyflow_map(ttl: float = 600) -> dict[str, float]:
    """Return {6-digit code -> 今日主力净流入(CNY)} for the whole market.

    Best-effort: returns empty dict when no working source is available.
    """
    if not _MONEYFLOW_ENABLED:
        return {}

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

    _cache_set("moneyflow_map", flow_map, int(ttl))
    return flow_map


def is_tradeable(name: str) -> bool:
    """Filter out ST / *ST / 退市 / 停牌-flagged names."""
    n = (name or "").upper()
    bad = ("ST", "*ST", "退", "PT")
    return not any(b in n for b in bad)
