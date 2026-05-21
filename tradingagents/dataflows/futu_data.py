"""Futu OpenD data provider for US, HK, and A-share markets.

Requires Futu OpenD to be running locally (default: 127.0.0.1:11111).
Configure via environment variables:
  FUTU_HOST  — OpenD host (default: 127.0.0.1)
  FUTU_PORT  — OpenD port (default: 11111)

Ticker format conventions (Yahoo Finance style, same as rest of project):
  US stocks : AAPL, CANG, BABA
  HK stocks : 0700.HK → converted to HK.00700
  A-share   : 600519.SS → converted to SH.600519
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Annotated

logger = logging.getLogger(__name__)

_FUTU_HOST = os.getenv("FUTU_HOST", "127.0.0.1")
_FUTU_PORT = int(os.getenv("FUTU_PORT", "11111"))


class FutuError(Exception):
    """Raised when Futu OpenD is unavailable or returns an error."""
    pass


# ── Ticker format helpers ──────────────────────────────────────────────────────

def _to_futu_code(ticker: str) -> str:
    """Convert Yahoo Finance ticker to Futu code format.

    Examples:
      AAPL      → US.AAPL
      CANG      → US.CANG
      0700.HK   → HK.00700
      600519.SS → SH.600519
      000001.SZ → SZ.000001
    """
    t = ticker.upper().strip()
    if t.endswith(".HK"):
        code = t.replace(".HK", "").zfill(5)
        return f"HK.{code}"
    if t.endswith(".SS"):
        return f"SH.{t.replace('.SS', '')}"
    if t.endswith(".SZ"):
        return f"SZ.{t.replace('.SZ', '')}"
    # US stock (no suffix)
    return f"US.{t}"


def _get_quote_ctx():
    """Return a connected Futu QuoteContext. Raises FutuError if OpenD is down."""
    try:
        import futu as ft
        ctx = ft.OpenQuoteContext(host=_FUTU_HOST, port=_FUTU_PORT)
        return ctx
    except Exception as e:
        raise FutuError(
            f"Cannot connect to Futu OpenD at {_FUTU_HOST}:{_FUTU_PORT}. "
            f"Please ensure the Futu app is running and OpenD is enabled. Error: {e}"
        ) from e


# ── Price / OHLCV data ─────────────────────────────────────────────────────────

def get_futu_stock_data(
    symbol: Annotated[str, "ticker in Yahoo Finance format, e.g. CANG or 0700.HK"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV data via Futu OpenD (daily K-line)."""
    import futu as ft
    ctx = _get_quote_ctx()
    try:
        futu_code = _to_futu_code(symbol)
        ret, df, pg_key = ctx.request_history_kline(
            code=futu_code,
            start=start_date,
            end=end_date,
            ktype=ft.KLType.K_DAY,
            autype=ft.AuType.QFQ,   # 前复权
            fields=[
                ft.KL_FIELD.DATE_TIME,
                ft.KL_FIELD.OPEN,
                ft.KL_FIELD.HIGH,
                ft.KL_FIELD.LOW,
                ft.KL_FIELD.CLOSE,
                ft.KL_FIELD.VOLUME,
                ft.KL_FIELD.TURNOVER,
                ft.KL_FIELD.CHANGE_RATE,
            ],
        )
        if ret != ft.RET_OK:
            raise FutuError(f"Futu get_history_kline failed for {symbol}: {df}")
        if df is None or df.empty:
            return f"No OHLCV data for {symbol} between {start_date} and {end_date}"

        col_map = {
            "time_key": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume",
            "turnover": "Turnover", "change_rate": "ChangeRate(%)",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        header = (
            f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            f"# Source: Futu OpenD | Records: {len(df)}\n"
            f"# Adjusted: forward-split-adjusted (前复权)\n\n"
        )
        return header + df.to_csv(index=False)
    except FutuError:
        raise
    except Exception as e:
        logger.warning("Futu get_futu_stock_data failed for %s: %s", symbol, e)
        raise FutuError(f"Futu data fetch failed for {symbol}: {e}") from e
    finally:
        ctx.close()


# ── Snapshot (current price) ───────────────────────────────────────────────────

def get_futu_snapshot(symbol: str) -> str:
    """Get current quote snapshot for a ticker."""
    import futu as ft
    ctx = _get_quote_ctx()
    try:
        futu_code = _to_futu_code(symbol)
        ret, df = ctx.get_market_snapshot([futu_code])
        if ret != ft.RET_OK or df is None or df.empty:
            raise FutuError(f"Futu snapshot failed for {symbol}")
        row = df.iloc[0]
        return (
            f"# Market Snapshot for {symbol.upper()}\n"
            f"Last Price: {row.get('last_price', 'N/A')}\n"
            f"Change: {row.get('change_val', 'N/A')} ({row.get('change_rate', 'N/A')}%)\n"
            f"Volume: {row.get('volume', 'N/A')}\n"
            f"Market Cap: {row.get('market_val', 'N/A')}\n"
            f"52W High: {row.get('high_52weeks_price', 'N/A')}\n"
            f"52W Low:  {row.get('low_52weeks_price', 'N/A')}\n"
        )
    except FutuError:
        raise
    except Exception as e:
        raise FutuError(f"Futu snapshot failed for {symbol}: {e}") from e
    finally:
        ctx.close()


# ── Financials ─────────────────────────────────────────────────────────────────

def get_futu_fundamentals(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    curr_date: Annotated[str, "current date (for context)"] = None,
) -> str:
    """Get financial summary (income, balance, valuation) via Futu."""
    import futu as ft
    ctx = _get_quote_ctx()
    try:
        futu_code = _to_futu_code(ticker)
        lines = [f"# Fundamentals for {ticker.upper()} via Futu\n"]

        # Basic quote info
        ret, df = ctx.get_market_snapshot([futu_code])
        if ret == ft.RET_OK and df is not None and not df.empty:
            row = df.iloc[0]
            for field, label in [
                ("last_price", "Price"), ("pe_ratio", "P/E Ratio"),
                ("pb_ratio", "P/B Ratio"), ("market_val", "Market Cap"),
                ("eps", "EPS"), ("dividend_ttm", "Dividend TTM"),
                ("net_profit_growth_rate", "Net Profit Growth Rate"),
                ("revenue_growth_rate", "Revenue Growth Rate"),
            ]:
                val = row.get(field, "N/A")
                if str(val).lower() not in ("nan", "none", "n/a", ""):
                    lines.append(f"{label}: {val}")

        return "\n".join(lines)
    except FutuError:
        raise
    except Exception as e:
        raise FutuError(f"Futu fundamentals failed for {ticker}: {e}") from e
    finally:
        ctx.close()


def get_futu_income_statement(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "annual",
    curr_date: str = None,
) -> str:
    """Get income statement via Futu financial data."""
    import futu as ft
    ctx = _get_quote_ctx()
    try:
        futu_code = _to_futu_code(ticker)
        period = ft.RelativePosition.ANNUAL if freq == "annual" else ft.RelativePosition.QUARTER
        ret, df = ctx.get_income_statement(code=futu_code, start="", end="", pdl_period_type=period)
        if ret != ft.RET_OK or df is None or df.empty:
            raise FutuError(f"Futu income statement failed for {ticker}: {df}")
        header = f"# Income Statement for {ticker.upper()} (Futu)\n\n"
        return header + df.head(8).to_csv(index=False)
    except FutuError:
        raise
    except Exception as e:
        raise FutuError(f"Futu income statement failed for {ticker}: {e}") from e
    finally:
        ctx.close()


def get_futu_balance_sheet(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "annual",
    curr_date: str = None,
) -> str:
    """Get balance sheet via Futu financial data."""
    import futu as ft
    ctx = _get_quote_ctx()
    try:
        futu_code = _to_futu_code(ticker)
        period = ft.RelativePosition.ANNUAL if freq == "annual" else ft.RelativePosition.QUARTER
        ret, df = ctx.get_balance_sheet(code=futu_code, start="", end="", pdl_period_type=period)
        if ret != ft.RET_OK or df is None or df.empty:
            raise FutuError(f"Futu balance sheet failed for {ticker}: {df}")
        header = f"# Balance Sheet for {ticker.upper()} (Futu)\n\n"
        return header + df.head(8).to_csv(index=False)
    except FutuError:
        raise
    except Exception as e:
        raise FutuError(f"Futu balance sheet failed for {ticker}: {e}") from e
    finally:
        ctx.close()


def get_futu_cashflow(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "annual",
    curr_date: str = None,
) -> str:
    """Get cash flow statement via Futu financial data."""
    import futu as ft
    ctx = _get_quote_ctx()
    try:
        futu_code = _to_futu_code(ticker)
        period = ft.RelativePosition.ANNUAL if freq == "annual" else ft.RelativePosition.QUARTER
        ret, df = ctx.get_cash_flow(code=futu_code, start="", end="", pdl_period_type=period)
        if ret != ft.RET_OK or df is None or df.empty:
            raise FutuError(f"Futu cashflow failed for {ticker}: {df}")
        header = f"# Cash Flow Statement for {ticker.upper()} (Futu)\n\n"
        return header + df.head(8).to_csv(index=False)
    except FutuError:
        raise
    except Exception as e:
        raise FutuError(f"Futu cashflow failed for {ticker}: {e}") from e
    finally:
        ctx.close()


# ── Connection test ────────────────────────────────────────────────────────────

def test_futu_connection() -> dict:
    """Test Futu OpenD connectivity. Returns status dict."""
    try:
        import futu as ft
        ctx = ft.OpenQuoteContext(host=_FUTU_HOST, port=_FUTU_PORT)
        ret, df = ctx.get_global_state()
        ctx.close()
        if ret == ft.RET_OK:
            return {"connected": True, "host": _FUTU_HOST, "port": _FUTU_PORT}
        return {"connected": False, "error": str(df)}
    except Exception as e:
        return {"connected": False, "error": str(e)}
