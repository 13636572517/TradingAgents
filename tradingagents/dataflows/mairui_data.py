"""MaiRui (麦蕊智数) data provider for A-share markets.

REST API — licence key required (mairui.club).
Configure via environment variable: MAIRUI_LICENCE

Strengths: stable, real-time + recent historical data, no rate limiting on paid plans.
Use as primary source for recent data; JoinQuant / BaoStock handle longer history.

Ticker format (Yahoo Finance style → MaiRui format):
  600519.SS → 600519.SH  (Shanghai: .SS → .SH)
  000001.SZ → 000001.SZ  (Shenzhen: unchanged)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Annotated

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.mairuiapi.com"
_TIMEOUT = 15


def _licence() -> str:
    """Read licence dynamically so changes to .env take effect without restart."""
    return os.getenv("MAIRUI_LICENCE", "")


class MaiRuiError(Exception):
    """Raised when MaiRui API fails — triggers vendor fallback."""
    pass


# ── Ticker conversion ──────────────────────────────────────────────────────────

def _to_mr_code(ticker: str) -> str:
    """Convert Yahoo Finance ticker to MaiRui format.

    600519.SS → 600519.SH   (Shanghai: .SS → .SH)
    000001.SZ → 000001.SZ   (Shenzhen: unchanged)
    """
    t = ticker.upper().strip()
    if t.endswith(".SS"):
        return t[:-3] + ".SH"
    return t   # .SZ stays as-is


def _get(path: str, params: dict = None) -> list | dict:
    """Make a GET request to MaiRui API. Raises MaiRuiError on failure."""
    lic = _licence()
    if not lic:
        raise MaiRuiError(
            "MAIRUI_LICENCE not set in .env. "
            "Get a licence at mairui.club and add MAIRUI_LICENCE=xxx to .env"
        )
    url = f"{_BASE}/{path.lstrip('/')}/{lic}"
    try:
        session = requests.Session()
        session.trust_env = False   # bypass system proxy
        r = session.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise MaiRuiError(f"MaiRui API error: {data['error']} (url={url})")
        return data
    except MaiRuiError:
        raise
    except Exception as e:
        raise MaiRuiError(f"MaiRui request failed: {e}") from e


# ── Price / OHLCV ──────────────────────────────────────────────────────────────

def get_mr_stock_data(
    symbol: Annotated[str, "ticker in Yahoo Finance format e.g. 600519.SS"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get A-share daily OHLCV from MaiRui (前复权)."""
    try:
        import pandas as pd
        mr_code = _to_mr_code(symbol)
        st = start_date.replace("-", "")
        et = end_date.replace("-", "")

        data = _get(
            f"hsstock/history/{mr_code}/d/f",
            params={"st": st, "et": et},
        )
        if not data or not isinstance(data, list):
            return f"No data for {symbol} between {start_date} and {end_date}"

        rows = []
        for item in data:
            rows.append({
                "Date":             item.get("t", "")[:10],
                "Open":             item.get("o"),
                "High":             item.get("h"),
                "Low":              item.get("l"),
                "Close":            item.get("c"),
                "Volume":           item.get("v"),
                "Turnover(CNY)":    item.get("a"),
                "PrevClose":        item.get("pc"),
            })

        df = pd.DataFrame(rows)
        header = (
            f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            f"# Source: MaiRui (麦蕊智数) | Currency: CNY | Adjusted: 前复权\n"
            f"# Records: {len(df)} | Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.to_csv(index=False)

    except MaiRuiError:
        raise
    except Exception as e:
        logger.warning("MaiRui get_mr_stock_data failed for %s: %s", symbol, e)
        raise MaiRuiError(f"MaiRui price data failed for {symbol}: {e}") from e


# ── Technical indicators (stockstats on MaiRui OHLCV) ─────────────────────────

def get_mr_indicators(
    symbol: Annotated[str, "ticker in Yahoo Finance format"],
    indicator: Annotated[str, "technical indicator e.g. rsi, close_50_sma, macd"],
    curr_date: Annotated[str, "current trading date YYYY-MM-DD"],
    look_back_days: Annotated[int, "calendar days to look back"] = 60,
) -> str:
    """Compute technical indicators via MaiRui OHLCV + stockstats."""
    try:
        import pandas as pd
        from stockstats import wrap
        from dateutil.relativedelta import relativedelta as rdelta

        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - rdelta(years=1)
        mr_code = _to_mr_code(symbol)

        data = _get(
            f"hsstock/history/{mr_code}/d/f",
            params={
                "st": start_dt.strftime("%Y%m%d"),
                "et": curr_dt.strftime("%Y%m%d"),
            },
        )
        if not data or not isinstance(data, list):
            raise MaiRuiError(f"No OHLCV data for {symbol}")

        rows = [{
            "date": pd.to_datetime(item["t"][:10]),
            "open":   float(item["o"] or 0),
            "high":   float(item["h"] or 0),
            "low":    float(item["l"] or 0),
            "close":  float(item["c"] or 0),
            "volume": float(item["v"] or 0),
        } for item in data]

        df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
        df["Date"] = df["date"].dt.strftime("%Y-%m-%d")

        stock = wrap(df)
        stock[indicator]

        result_dict = {
            row["Date"]: ("N/A" if pd.isna(row.get(indicator)) else str(round(float(row[indicator]), 4)))
            for _, row in stock.iterrows()
        }

        before = curr_dt - rdelta(days=look_back_days)
        lines, d = [], curr_dt
        while d >= before:
            ds = d.strftime("%Y-%m-%d")
            lines.append(f"{ds}: {result_dict.get(ds, 'N/A: Not a trading day')}")
            d -= rdelta(days=1)

        return (
            f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
        )

    except MaiRuiError:
        raise
    except Exception as e:
        logger.warning("MaiRui indicator %s failed for %s: %s", indicator, symbol, e)
        raise MaiRuiError(f"MaiRui indicator {indicator} failed for {symbol}: {e}") from e


# ── Fundamentals (snapshot via real-time quote) ────────────────────────────────

def get_mr_fundamentals(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Get current valuation snapshot from MaiRui real-time quote."""
    try:
        mr_code = _to_mr_code(ticker)
        # Real-time quote includes PE/PB/market cap
        data = _get(f"hsstock/latest/{mr_code}/d/f", params={"lt": 1})

        if not data or not isinstance(data, list):
            raise MaiRuiError(f"No quote data for {ticker}")

        item = data[-1]
        lines = [
            f"# Market Snapshot for {ticker.upper()} (MaiRui)",
            f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"Latest Close:  {item.get('c', 'N/A')} CNY",
            f"Previous Close:{item.get('pc', 'N/A')} CNY",
            f"Volume:        {item.get('v', 'N/A')}",
            f"Turnover:      {item.get('a', 'N/A')} CNY",
        ]
        return "\n".join(lines)

    except MaiRuiError:
        raise
    except Exception as e:
        raise MaiRuiError(f"MaiRui fundamentals failed for {ticker}: {e}") from e


# ── Connection test ────────────────────────────────────────────────────────────

def test_mr_connection() -> dict:
    """Test MaiRui connectivity with a simple known-good ticker."""
    try:
        data = _get("hsstock/latest/000001.SZ/d/f", params={"lt": 1})
        if isinstance(data, list) and data and "c" in data[0]:
            return {
                "connected": True,
                "licence": _LICENCE[:8] + "...",
                "sample_close": data[-1].get("c"),
            }
        return {"connected": False, "error": str(data)[:100]}
    except Exception as e:
        return {"connected": False, "error": str(e)[:200]}


# ── Alias for Settings panel ───────────────────────────────────────────────────

def test_mairui_connection() -> dict:
    return test_mr_connection()
