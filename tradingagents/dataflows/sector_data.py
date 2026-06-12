"""Sector / whole-market data provider for the A-share stock screener.

The three *required* feeds (industry board list, board constituents, whole-market
spot snapshot) talk to East Money's `clist` API **directly** rather than through
AkShare. On some hosts (e.g. the production Aliyun box) East Money rate-limits the
server IP and abruptly closes connections (`RemoteDisconnected`); AkShare's helper
aborts the whole fetch on the first such error, and its full-market snapshot needs
~59 paginated requests, so it fails reliably there. Our own client adds per-request
retry/back-off plus partial tolerance (a few dropped pages don't sink the run).

  - Industry board list   : clist  fs="m:90 t:2 f:!50"        (17.push2)
  - Board constituents    : clist  fs="b:{board_code} f:!50"  (29.push2)
  - Whole-market spot      : clist  fs="m:0 t:6,..."           (82.push2, paginated)
  - ROE map (optional)    : ak.stock_yjbb_em(date)            best-effort, AkShare
  - Money-flow (optional) : ak.stock_individual_fund_flow_rank best-effort, AkShare

Ticker format: results expose Yahoo-Finance style tickers (600519.SS / 000001.SZ / 430047.BJ)
to stay consistent with the rest of the project.
"""
from __future__ import annotations

import logging
import math
import random
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── East Money direct HTTP client (retry + back-off, tolerant of flaky hosts) ─────

_EM_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_SESSION = None
_SESSION_LOCK = threading.Lock()


def _session():
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            import requests
            s = requests.Session()
            s.headers.update({"User-Agent": _EM_UA, "Referer": "https://quote.eastmoney.com/"})
            _SESSION = s
        return _SESSION


def _em_get(url: str, params: dict, *, tries: int = 4, timeout: int = 15):
    """GET an East Money endpoint with retry + exponential back-off.

    Returns the parsed JSON dict, or None if every attempt failed.
    """
    last = None
    for attempt in range(tries):
        try:
            r = _session().get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # network reset / rate-limit / bad JSON
            last = e
            if attempt < tries - 1:
                time.sleep(min(8.0, 0.6 * (2 ** attempt)) + random.uniform(0.2, 0.8))
    logger.warning("eastmoney GET failed after %d tries (%s): %s", tries, url, last)
    return None


def _em_diff(payload) -> list[dict]:
    """Extract the `data.diff` rows from an East Money clist payload (safe)."""
    if not payload:
        return []
    data = payload.get("data")
    if not data:
        return []
    diff = data.get("diff")
    return diff if isinstance(diff, list) else []


def _em_clist_paged(url: str, base_params: dict, *, page_sleep=(0.15, 0.4),
                    max_pages: int = 200) -> tuple[list[dict], int]:
    """Page through an East Money clist endpoint.

    Returns ``(rows, total)`` where ``total`` is the server-reported row count
    (0 if unknown). Tolerant of partial failure: pages that never succeed are
    skipped rather than aborting the whole fetch — callers can compare
    ``len(rows)`` against ``total`` to decide whether the result is complete
    enough or whether to fall back to another provider.
    """
    params = {"pn": "1", "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
              **base_params}
    first = _em_get(url, {**params, "pn": "1"})
    rows = _em_diff(first)
    if not rows:
        return [], 0
    total = (first.get("data") or {}).get("total") or 0
    per = len(rows) or 100
    pages = min(max_pages, math.ceil(total / per)) if total else 1
    for pn in range(2, pages + 1):
        time.sleep(random.uniform(*page_sleep))
        rows.extend(_em_diff(_em_get(url, {**params, "pn": str(pn)})))
    return rows, total


def _em_num(v) -> Optional[float]:
    """East Money uses the string '-' for missing numeric cells."""
    if v in (None, "-", ""):
        return None
    return _to_float(v)

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


# ── Industry boards (East Money direct → AkShare-EM) ────────────────────────────

def get_industry_boards(ttl: float = 600) -> list[dict]:
    """Return list of A-share industry boards (东方财富 行业板块).

    Each dict: {name, code, price, pct_change, total_mktcap, turnover, up, down}
    """
    cached = _cache_get("industry_boards", ttl)
    if cached is not None:
        return cached  # type: ignore
    boards = _first_nonempty("industry_boards", [
        ("eastmoney_direct", _boards_em_direct),
        ("akshare_em", _boards_akshare_em),
    ]) or []
    if boards:
        _cache_set("industry_boards", boards)
    return boards


def _boards_em_direct() -> list[dict]:
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    rows, _ = _em_clist_paged(url, {
        "fid": "f3", "fs": "m:90 t:2 f:!50", "fields": "f12,f14,f2,f3,f8,f20",
    })
    boards: list[dict] = []
    for it in rows:
        name = str(it.get("f14", "")).strip()
        if not name:
            continue
        boards.append({
            "name": name,
            "code": str(it.get("f12", "")).strip(),
            "price": _em_num(it.get("f2")),
            "pct_change": _em_num(it.get("f3")),
            "total_mktcap": _em_num(it.get("f20")),
            "turnover": _em_num(it.get("f8")),
            "up": None, "down": None,
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


# ── Board constituents (East Money direct → AkShare-EM) ─────────────────────────

def get_board_constituents(board_name: str, ttl: float = 3600) -> list[str]:
    """Return list of 6-digit constituent codes for an industry board."""
    key = f"board_cons::{board_name}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached  # type: ignore
    codes = _first_nonempty(f"constituents[{board_name}]", [
        ("eastmoney_direct", lambda: _cons_em_direct(board_name)),
        ("akshare_em", lambda: _cons_akshare_em(board_name)),
    ]) or []
    if codes:
        _cache_set(key, codes)
    return codes


def _cons_em_direct(board_name: str) -> list[str]:
    code = _board_code_for(board_name)
    if not code:
        return []
    url = "https://29.push2.eastmoney.com/api/qt/clist/get"
    rows, _ = _em_clist_paged(url, {"fid": "f3", "fs": f"b:{code} f:!50", "fields": "f12"})
    return [str(it.get("f12", "")).strip().zfill(6)
            for it in rows if str(it.get("f12", "")).strip()]


def _cons_akshare_em(board_name: str) -> list[str]:
    import akshare as ak
    df = ak.stock_board_industry_cons_em(symbol=board_name)
    if df is None or df.empty:
        return []
    return [str(c).strip().zfill(6) for c in df.get("代码", []) if str(c).strip()]


# ── Whole-market spot snapshot (East Money → AkShare-EM → JoinQuant) ────────────

def get_market_spot(ttl: float = 600):
    """Return whole-market spot snapshot as a dict keyed by 6-digit code.

    value: {code, name, price, pct_change, amount, pe, pb, total_mktcap, float_mktcap, turnover}
    `amount` = 成交额 (CNY, liquidity proxy); `pe` = 市盈率-动态; `pb` = 市净率.

    Provider chain: East Money direct → AkShare(EM) → JoinQuant valuation. The
    JoinQuant leg is the genuinely *independent* fallback (no East Money), used when
    East Money rate-limits the server IP and the snapshot can't be completed.
    """
    cached = _cache_get("market_spot", ttl)
    if cached is not None:
        return cached  # type: ignore
    spot = _first_nonempty("market_spot", [
        ("eastmoney_direct", _spot_em_direct),
        ("akshare_em", _spot_akshare_em),
        ("joinquant", _spot_jq),
    ]) or {}
    if spot:
        _cache_set("market_spot", spot)
    return spot


def _spot_em_direct() -> dict:
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    rows, total = _em_clist_paged(url, {
        "fid": "f3",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f12,f14,f2,f3,f6,f8,f9,f23,f20,f21",
    })
    # Reject an obviously-incomplete snapshot so the chain falls through to a
    # non-East-Money provider rather than caching a half-empty market.
    if total and len(rows) < total * 0.9:
        logger.warning("market_spot: East Money returned %d/%d rows — treating as "
                       "incomplete, falling back", len(rows), total)
        return {}
    out: dict[str, dict] = {}
    for it in rows:
        code = str(it.get("f12", "")).strip().zfill(6)
        if not code or not code.isdigit():
            continue
        out[code] = {
            "code": code,
            "name": str(it.get("f14", "")).strip(),
            "price": _em_num(it.get("f2")),
            "pct_change": _em_num(it.get("f3")),
            "amount": _em_num(it.get("f6")),
            "pe": _em_num(it.get("f9")),
            "pb": _em_num(it.get("f23")),
            "total_mktcap": _em_num(it.get("f20")),
            "float_mktcap": _em_num(it.get("f21")),
            "turnover": _em_num(it.get("f8")),
        }
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
    """Whole-market snapshot via JoinQuant — independent of East Money.

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
