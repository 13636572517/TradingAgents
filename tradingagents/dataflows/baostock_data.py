"""BaoStock data provider for A-share markets.

Zero registration, zero API key — install and use immediately.
Provides stable daily OHLCV, financial statements, and valuation data.

Ticker format (Yahoo Finance style):
  600519.SS → sh.600519
  000001.SZ → sz.000001
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd

logger = logging.getLogger(__name__)


class BaoStockError(Exception):
    """Raised when BaoStock fails — triggers vendor fallback."""
    pass


# ── Ticker conversion ──────────────────────────────────────────────────────────

def _to_bs_code(ticker: str) -> str:
    """600519.SS → sh.600519 | 000001.SZ → sz.000001"""
    t = ticker.upper().strip()
    if t.endswith(".SS"):
        return "sh." + t.replace(".SS", "")
    if t.endswith(".SZ"):
        return "sz." + t.replace(".SZ", "")
    return t


# ── Session management (login once per call, logout after) ────────────────────

def _bs_session():
    """Context manager that logs into BaoStock and logs out on exit."""
    import baostock as bs

    class _Session:
        def __enter__(self):
            result = bs.login()
            if result.error_code != "0":
                raise BaoStockError(f"BaoStock login failed: {result.error_msg}")
            return bs
        def __exit__(self, *_):
            bs.logout()

    return _Session()


# ── Price / OHLCV ──────────────────────────────────────────────────────────────

def get_bs_stock_data(
    symbol: Annotated[str, "ticker in Yahoo Finance format e.g. 600519.SS"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get A-share daily OHLCV + PE/PB from BaoStock (前复权, qfq)."""
    try:
        import baostock as bs
    except ImportError:
        raise BaoStockError("baostock not installed. Run: pip install baostock")

    try:
        bs_code = _to_bs_code(symbol)
        with _bs_session() as bs:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,turn,peTTM,pbMRQ",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",   # 2=前复权
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

        if not rows:
            return f"No data for {symbol} between {start_date} and {end_date}"

        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
            "amount": "Turnover(CNY)", "turn": "TurnoverRate(%)",
            "peTTM": "PE(TTM)", "pbMRQ": "PB(MRQ)",
        })

        header = (
            f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            f"# Source: BaoStock (证券宝) | Currency: CNY | Adjusted: 前复权 (qfq)\n"
            f"# Records: {len(df)} | Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.to_csv(index=False)

    except BaoStockError:
        raise
    except Exception as e:
        logger.warning("BaoStock get_bs_stock_data failed for %s: %s", symbol, e)
        raise BaoStockError(f"BaoStock price data failed for {symbol}: {e}") from e


# ── Technical indicators (via stockstats on BaoStock OHLCV) ───────────────────

def get_bs_indicators(
    symbol: Annotated[str, "ticker in Yahoo Finance format"],
    indicator: Annotated[str, "technical indicator e.g. rsi, close_50_sma, macd"],
    curr_date: Annotated[str, "current trading date YYYY-MM-DD"],
    look_back_days: Annotated[int, "calendar days to look back"] = 60,
) -> str:
    """Compute technical indicators via BaoStock OHLCV + stockstats."""
    try:
        import baostock as bs
        from stockstats import wrap
        from dateutil.relativedelta import relativedelta as rdelta
    except ImportError as e:
        raise BaoStockError(f"Missing dependency: {e}")

    try:
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - rdelta(years=1)
        bs_code = _to_bs_code(symbol)

        with _bs_session() as bs:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume",
                start_date=start_dt.strftime("%Y-%m-%d"),
                end_date=curr_date,
                frequency="d",
                adjustflag="2",
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

        if not rows:
            raise BaoStockError(f"No OHLCV data for {symbol}")

        df = pd.DataFrame(rows, columns=rs.fields)
        df["date"] = pd.to_datetime(df["date"])
        df["Date"] = df["date"].dt.strftime("%Y-%m-%d")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)

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

    except BaoStockError:
        raise
    except Exception as e:
        logger.warning("BaoStock indicator %s failed for %s: %s", indicator, symbol, e)
        raise BaoStockError(f"BaoStock indicator {indicator} failed for {symbol}: {e}") from e


# ── Fundamentals ───────────────────────────────────────────────────────────────

def get_bs_fundamentals(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Get A-share valuation and profitability indicators from BaoStock."""
    try:
        import baostock as bs
    except ImportError:
        raise BaoStockError("baostock not installed")

    try:
        bs_code = _to_bs_code(ticker)
        date = curr_date or datetime.now().strftime("%Y-%m-%d")
        # Use last 4 quarters of profit data
        with _bs_session() as bs:
            rs = bs.query_profit_data(code=bs_code, year=date[:4], quarter=4)
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

        lines = [
            f"# Fundamentals for {ticker.upper()} (BaoStock)",
            f"# Date: {date}\n",
        ]

        if rows:
            df = pd.DataFrame(rows, columns=rs.fields)
            latest = df.iloc[-1]
            field_map = {
                "roeAvg": "ROE (平均)",
                "npMargin": "Net Profit Margin",
                "gpMargin": "Gross Profit Margin",
                "netProfit": "Net Profit (元)",
                "epsTTM": "EPS TTM",
                "MBRevenue": "Main Business Revenue",
                "totalShare": "Total Shares",
                "liqaShare": "Circulating Shares",
            }
            for field, label in field_map.items():
                val = latest.get(field, "")
                if val and str(val) not in ("", "nan"):
                    lines.append(f"{label}: {val}")

        return "\n".join(lines)

    except BaoStockError:
        raise
    except Exception as e:
        logger.warning("BaoStock fundamentals failed for %s: %s", ticker, e)
        raise BaoStockError(f"BaoStock fundamentals failed for {ticker}: {e}") from e


def _get_bs_statement(ticker: str, statement_type: str, curr_date: str = None) -> str:
    """Shared helper for financial statements via BaoStock."""
    try:
        import baostock as bs
    except ImportError:
        raise BaoStockError("baostock not installed")

    try:
        bs_code = _to_bs_code(ticker)
        year = (curr_date or datetime.now().strftime("%Y-%m-%d"))[:4]

        label_map = {
            "balance":  "Balance Sheet (资产负债表)",
            "cashflow": "Cash Flow Statement (现金流量表)",
            "profit":   "Income Statement (利润表)",
        }

        with _bs_session() as bs:
            if statement_type == "balance":
                rs = bs.query_balance_data(code=bs_code, year=year, quarter=4)
            elif statement_type == "cashflow":
                rs = bs.query_cash_flow_data(code=bs_code, year=year, quarter=4)
            else:
                rs = bs.query_profit_data(code=bs_code, year=year, quarter=4)
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

        if not rows:
            return f"No {statement_type} data for {ticker}"

        df = pd.DataFrame(rows, columns=rs.fields)
        header = (
            f"# {label_map.get(statement_type, statement_type)} for {ticker.upper()}\n"
            f"# Source: BaoStock | Year: {year}\n\n"
        )
        return header + df.to_csv(index=False)

    except BaoStockError:
        raise
    except Exception as e:
        logger.warning("BaoStock %s failed for %s: %s", statement_type, ticker, e)
        raise BaoStockError(f"BaoStock {statement_type} failed for {ticker}: {e}") from e


def get_bs_balance_sheet(ticker, freq="quarterly", curr_date=None):
    return _get_bs_statement(ticker, "balance", curr_date)

def get_bs_cashflow(ticker, freq="quarterly", curr_date=None):
    return _get_bs_statement(ticker, "cashflow", curr_date)

def get_bs_income_statement(ticker, freq="quarterly", curr_date=None):
    return _get_bs_statement(ticker, "profit", curr_date)


# ── Connection test ────────────────────────────────────────────────────────────

def test_bs_connection() -> dict:
    try:
        import baostock as bs
        result = bs.login()
        ok = result.error_code == "0"
        bs.logout()
        return {"connected": ok, "message": result.error_msg if ok else result.error_msg}
    except Exception as e:
        return {"connected": False, "error": str(e)}
