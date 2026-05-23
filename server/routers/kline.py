# server/routers/kline.py
"""K线 OHLCV 数据端点。按市场依次尝试多个数据源，返回标准化 JSON。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kline", tags=["kline"])

_RANGE_DAYS = {"1M": 45, "3M": 130, "6M": 260, "1Y": 375, "2Y": 750}


def _date_range(range_str: str) -> tuple[str, str]:
    days = _RANGE_DAYS.get(range_str, 375)
    end = datetime.today()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ── Ticker helpers ─────────────────────────────────────────────────────────────

def _short_code(ticker: str) -> str:
    """600519.SS → 600519"""
    return ticker.upper().rsplit(".", 1)[0]


def _bs_code(ticker: str) -> str:
    """600519.SS → sh.600519,  000001.SZ → sz.000001"""
    t = ticker.upper()
    if t.endswith(".SS"):
        return "sh." + t[:-3]
    if t.endswith(".SZ"):
        return "sz." + t[:-3]
    return t


def _hk_code(ticker: str) -> str:
    """0700.HK → 00700 (5-digit for AkShare)"""
    return ticker.upper().replace(".HK", "").zfill(5)


def _jq_code(ticker: str) -> str:
    """600519.SS → 600519.XSHG,  000001.SZ → 000001.XSHE"""
    t = ticker.upper()
    if t.endswith(".SS"):
        return t[:-3] + ".XSHG"
    if t.endswith(".SZ"):
        return t[:-3] + ".XSHE"
    return t


def _is_etf(ticker: str) -> bool:
    t = ticker.upper()
    code = t.rsplit(".", 1)[0]
    if not code.isdigit() or len(code) != 6:
        return False
    p3 = code[:3]
    if t.endswith(".SZ") and p3 == "159":
        return True
    if t.endswith(".SS") and (code[:2] in ("51", "52") or p3 == "588"):
        return True
    return False


# ── Data normalizer ────────────────────────────────────────────────────────────

def _normalize(df: pd.DataFrame, col_map: dict) -> list[dict]:
    """Rename columns, drop NaN rows, return sorted list of dicts."""
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    needed = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(df.columns):
        return []
    df = df[list(needed)].dropna()
    df = df.sort_values("Date")
    result = []
    for _, row in df.iterrows():
        try:
            result.append({
                "date":   str(row["Date"])[:10],
                "open":   round(float(row["Open"]),  4),
                "high":   round(float(row["High"]),  4),
                "low":    round(float(row["Low"]),   4),
                "close":  round(float(row["Close"]), 4),
                "volume": int(float(row["Volume"])),
            })
        except (ValueError, TypeError):
            continue
    return result


# ── Source: AkShare A-share / ETF ─────────────────────────────────────────────

def _fetch_akshare_a(ticker: str, start: str, end: str) -> list[dict]:
    import akshare as ak
    s_date = start.replace("-", "")
    e_date = end.replace("-", "")
    if _is_etf(ticker):
        df = ak.fund_etf_hist_em(
            symbol=_short_code(ticker), period="daily", adjust="qfq"
        )
        col_map = {"日期": "Date", "开盘": "Open", "最高": "High",
                   "最低": "Low", "收盘": "Close", "成交量": "Volume"}
        rows = _normalize(df, col_map)
        return [r for r in rows if start <= r["date"] <= end]
    else:
        df = ak.stock_zh_a_hist(
            symbol=_short_code(ticker), period="daily",
            start_date=s_date, end_date=e_date, adjust="qfq",
        )
        col_map = {"日期": "Date", "开盘": "Open", "最高": "High",
                   "最低": "Low", "收盘": "Close", "成交量": "Volume"}
        return _normalize(df, col_map)


# ── Source: AkShare HK ────────────────────────────────────────────────────────

def _fetch_akshare_hk(ticker: str, start: str, end: str) -> list[dict]:
    import akshare as ak
    df = ak.stock_hk_hist(
        symbol=_hk_code(ticker), period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""),
        adjust="qfq",
    )
    col_map = {"日期": "Date", "开盘": "Open", "最高": "High",
               "最低": "Low", "收盘": "Close", "成交量": "Volume"}
    return _normalize(df, col_map)


# ── Source: AkShare US ────────────────────────────────────────────────────────

def _fetch_akshare_us(ticker: str, start: str, end: str) -> list[dict]:
    import akshare as ak
    df = ak.stock_us_hist(
        symbol=ticker.upper().replace(".US", ""), period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""), adjust="qfq",
    )
    col_map = {"日期": "Date", "Date": "Date",
               "开盘": "Open",  "Open": "Open",
               "最高": "High",  "High": "High",
               "最低": "Low",   "Low": "Low",
               "收盘": "Close", "Close": "Close",
               "成交量": "Volume", "Volume": "Volume"}
    return _normalize(df, col_map)


# ── Source: BaoStock ──────────────────────────────────────────────────────────

def _fetch_baostock(ticker: str, start: str, end: str) -> list[dict]:
    from tradingagents.dataflows.baostock_data import _bs_session
    with _bs_session() as bs:
        rs = bs.query_history_k_data_plus(
            _bs_code(ticker),
            "date,open,high,low,close,volume",
            start_date=start, end_date=end,
            frequency="d", adjustflag="2",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    if not rows:
        raise ValueError(f"BaoStock: no data for {ticker}")
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df = df.replace("", float("nan"))
    return _normalize(df, {})


# ── Source: JoinQuant ─────────────────────────────────────────────────────────

def _fetch_joinquant(ticker: str, start: str, end: str) -> list[dict]:
    from tradingagents.dataflows.jq_data import _JQ_LOCK, _ensure_auth
    import jqdatasdk as jq
    with _JQ_LOCK:
        _ensure_auth()
        df = jq.get_price(
            _jq_code(ticker), start_date=start, end_date=end,
            frequency="daily",
            fields=["open", "high", "low", "close", "volume"],
            fq="pre",
        )
    if df is None or df.empty:
        raise ValueError(f"JoinQuant: no data for {ticker}")
    df = df.reset_index().rename(columns={
        "index": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
    })
    return _normalize(df, {})


# ── Source: yfinance ──────────────────────────────────────────────────────────

def _fetch_yfinance(ticker: str, start: str, end: str) -> list[dict]:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"yfinance: no data for {ticker}")
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return _normalize(df, {"Date": "Date", "Open": "Open", "High": "High",
                            "Low": "Low", "Close": "Close", "Volume": "Volume"})


# ── Fallback orchestrator ──────────────────────────────────────────────────────

def _fetch_with_fallback(ticker: str, start: str, end: str) -> tuple[list[dict], Optional[str]]:
    t = ticker.upper()
    is_a = t.endswith(".SS") or t.endswith(".SZ")
    is_hk = t.endswith(".HK")

    if is_a:
        chain = [
            ("AkShare",    _fetch_akshare_a),
            ("BaoStock",   _fetch_baostock),
            ("JoinQuant",  _fetch_joinquant),
            ("yfinance",   _fetch_yfinance),
        ]
    elif is_hk:
        chain = [
            ("AkShare-HK", _fetch_akshare_hk),
            ("yfinance",   _fetch_yfinance),
        ]
    else:  # US / other
        chain = [
            ("yfinance",   _fetch_yfinance),
            ("AkShare-US", _fetch_akshare_us),
        ]

    last_err = "所有数据源均不可用"
    for source, fn in chain:
        try:
            rows = fn(ticker, start, end)
            if rows:
                logger.info("kline: %s fetched %d bars from %s", ticker, len(rows), source)
                return rows, None
        except Exception as e:
            logger.warning("kline: %s failed from %s: %s", ticker, source, e)
            last_err = f"{source}: {e}"

    return [], last_err


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/{ticker}")
def get_kline(ticker: str, time_range: str = "1Y"):
    """Return OHLCV bars for ticker. Tries multiple data sources with graceful fallback."""
    try:
        from tradingagents.dataflows.utils import safe_ticker_component
        ticker = safe_ticker_component(ticker)
    except ValueError as e:
        return JSONResponse(
            content={"ticker": ticker, "range": time_range, "data": [], "error": str(e)},
            headers={"Cache-Control": "no-store"},
        )
    if time_range not in _RANGE_DAYS:
        time_range = "1Y"
    start, end = _date_range(time_range)
    data, error = _fetch_with_fallback(ticker, start, end)
    cache_header = "no-store" if error else "public, max-age=3600"
    return JSONResponse(
        content={"ticker": ticker, "range": time_range, "data": data, "error": error},
        headers={"Cache-Control": cache_header},
    )
