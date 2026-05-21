"""JoinQuant (聚宽) data provider for A-share markets.

Requires JoinQuant API access (register at joinquant.com, then apply at
joinquant.com/default/index/sdk).

Configure via environment variables:
  JQ_USERNAME — registered mobile number
  JQ_PASSWORD — account password

Ticker format (Yahoo Finance style, same as rest of project):
  A-share Shanghai: 600519.SS → converted to 600519.XSHG
  A-share Shenzhen: 000001.SZ → converted to 000001.XSHE

Free tier: 500 queries/day. Sufficient for investment research use.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Annotated, Optional

logger = logging.getLogger(__name__)

_JQ_USERNAME = os.getenv("JQ_USERNAME", "")
_JQ_PASSWORD = os.getenv("JQ_PASSWORD", "")


class JQError(Exception):
    """Raised when JoinQuant API fails — triggers vendor fallback."""
    pass


# ── Auth & connection ──────────────────────────────────────────────────────────

_authenticated = False


def _ensure_auth():
    """Authenticate once per process. Raises JQError if credentials missing."""
    global _authenticated
    if _authenticated:
        return
    if not _JQ_USERNAME or not _JQ_PASSWORD:
        raise JQError(
            "JQ_USERNAME and JQ_PASSWORD must be set in .env to use JoinQuant data. "
            "Register at joinquant.com and apply for API access."
        )
    try:
        import jqdatasdk as jq
        jq.auth(_JQ_USERNAME, _JQ_PASSWORD)
        _authenticated = True
        logger.info("JoinQuant authenticated successfully")
    except Exception as e:
        raise JQError(f"JoinQuant auth failed: {e}") from e


# ── Ticker conversion ──────────────────────────────────────────────────────────

def _to_jq_code(ticker: str) -> str:
    """Convert Yahoo Finance ticker to JoinQuant exchange code.

    600519.SS → 600519.XSHG
    000001.SZ → 000001.XSHE
    """
    t = ticker.upper().strip()
    if t.endswith(".SS"):
        return t.replace(".SS", ".XSHG")
    if t.endswith(".SZ"):
        return t.replace(".SZ", ".XSHE")
    # Already in JQ format or unknown
    return t


# ── Price / OHLCV ──────────────────────────────────────────────────────────────

def get_jq_stock_data(
    symbol: Annotated[str, "ticker in Yahoo Finance format, e.g. 600519.SS"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get A-share daily OHLCV data from JoinQuant (前复权, qfq)."""
    _ensure_auth()
    try:
        import jqdatasdk as jq
        jq_code = _to_jq_code(symbol)
        df = jq.get_price(
            jq_code,
            start_date=start_date,
            end_date=end_date,
            frequency="daily",
            fields=["open", "high", "low", "close", "volume", "money"],
            fq="pre",          # 前复权
            skip_paused=True,
        )
        if df is None or df.empty:
            return f"No OHLCV data for {symbol} between {start_date} and {end_date}"

        df = df.reset_index().rename(columns={
            "index": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
            "money": "Turnover(CNY)",
        })

        header = (
            f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            f"# Source: JoinQuant (聚宽) | Currency: CNY | Adjusted: 前复权 (qfq)\n"
            f"# Records: {len(df)} | Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.to_csv(index=False)
    except JQError:
        raise
    except Exception as e:
        logger.warning("JoinQuant get_jq_stock_data failed for %s: %s", symbol, e)
        raise JQError(f"JoinQuant price data failed for {symbol}: {e}") from e


# ── Technical indicators ───────────────────────────────────────────────────────

def get_jq_indicators(
    symbol: Annotated[str, "ticker in Yahoo Finance format"],
    indicator: Annotated[str, "technical indicator name, e.g. close_50_sma, rsi, macd"],
    curr_date: Annotated[str, "current trading date YYYY-MM-DD"],
    look_back_days: Annotated[int, "calendar days to look back"] = 60,
) -> str:
    """Compute technical indicators via JoinQuant OHLCV + stockstats."""
    _ensure_auth()
    try:
        import jqdatasdk as jq
        import pandas as pd
        from stockstats import wrap
        from dateutil.relativedelta import relativedelta as rdelta

        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - rdelta(years=1)  # need enough history for slow indicators
        jq_code = _to_jq_code(symbol)

        df = jq.get_price(
            jq_code,
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=curr_date,
            frequency="daily",
            fields=["open", "high", "low", "close", "volume"],
            fq="pre",
            skip_paused=True,
        )
        if df is None or df.empty:
            raise JQError(f"No OHLCV for {symbol}")

        df = df.reset_index().rename(columns={"index": "date"})
        df["Date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

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
    except JQError:
        raise
    except Exception as e:
        logger.warning("JoinQuant get_jq_indicators failed for %s %s: %s", symbol, indicator, e)
        raise JQError(f"JoinQuant indicator {indicator} failed for {symbol}: {e}") from e


# ── Fundamentals ───────────────────────────────────────────────────────────────

def get_jq_fundamentals(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Get A-share key financial indicators from JoinQuant."""
    _ensure_auth()
    try:
        import jqdatasdk as jq
        from jqdatasdk import query, valuation, income, balance, cash_flow, indicator

        jq_code = _to_jq_code(ticker)
        date = curr_date or datetime.now().strftime("%Y-%m-%d")

        # Valuation metrics
        q = query(valuation).filter(valuation.code == jq_code)
        df = jq.get_fundamentals(q, date=date)
        if df is None or df.empty:
            return f"No fundamentals data for {ticker}"

        row = df.iloc[0]
        lines = [
            f"# Fundamentals for {ticker.upper()} (JoinQuant)",
            f"# Date: {date}\n",
            f"PE Ratio (TTM):  {row.get('pe_ratio', 'N/A')}",
            f"PB Ratio:        {row.get('pb_ratio', 'N/A')}",
            f"PS Ratio (TTM):  {row.get('ps_ratio', 'N/A')}",
            f"PCF Ratio (TTM): {row.get('pcf_ratio', 'N/A')}",
            f"Market Cap (CNY):{row.get('market_cap', 'N/A')}",
            f"Circulating Cap: {row.get('circulating_market_cap', 'N/A')}",
            f"Turnover Rate:   {row.get('turnover_ratio', 'N/A')}",
            f"EPS:             {row.get('eps', 'N/A')}",
        ]
        return "\n".join(lines)
    except JQError:
        raise
    except Exception as e:
        logger.warning("JoinQuant get_jq_fundamentals failed for %s: %s", ticker, e)
        raise JQError(f"JoinQuant fundamentals failed for {ticker}: {e}") from e


def _get_jq_statement(ticker: str, statement_type: str, curr_date: Optional[str] = None) -> str:
    """Shared helper for financial statements via JoinQuant."""
    _ensure_auth()
    try:
        import jqdatasdk as jq
        from jqdatasdk import query, balance, income, cash_flow

        jq_code = _to_jq_code(ticker)
        date = curr_date or datetime.now().strftime("%Y-%m-%d")

        table_map = {"balance": balance, "income": income, "cashflow": cash_flow}
        label_map = {"balance": "Balance Sheet (资产负债表)",
                     "income": "Income Statement (利润表)",
                     "cashflow": "Cash Flow Statement (现金流量表)"}

        tbl = table_map[statement_type]
        q = query(tbl).filter(tbl.code == jq_code)
        df = jq.get_fundamentals(q, date=date)

        if df is None or df.empty:
            return f"No {statement_type} data for {ticker}"

        header = (
            f"# {label_map[statement_type]} for {ticker.upper()}\n"
            f"# Source: JoinQuant | Date: {date}\n\n"
        )
        # Drop internal columns
        df = df.drop(columns=["id", "code", "pubDate", "statDate"], errors="ignore")
        return header + df.to_csv(index=False)
    except JQError:
        raise
    except Exception as e:
        logger.warning("JoinQuant %s failed for %s: %s", statement_type, ticker, e)
        raise JQError(f"JoinQuant {statement_type} failed for {ticker}: {e}") from e


def get_jq_balance_sheet(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    return _get_jq_statement(ticker, "balance", curr_date)


def get_jq_income_statement(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    return _get_jq_statement(ticker, "income", curr_date)


def get_jq_cashflow(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    return _get_jq_statement(ticker, "cashflow", curr_date)


# ── Connection test ────────────────────────────────────────────────────────────

def test_jq_connection() -> dict:
    """Test JoinQuant connectivity. Returns status dict."""
    try:
        import jqdatasdk as jq
        jq.auth(_JQ_USERNAME, _JQ_PASSWORD)
        cnt = jq.get_query_count()
        return {
            "connected": True,
            "username": _JQ_USERNAME,
            "queries_remaining": cnt,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}
