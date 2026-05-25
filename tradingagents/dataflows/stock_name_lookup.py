"""Stock name lookup utilities for display purposes."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Cache for ETF names to avoid repeated API calls
_ETF_CACHE: Optional[dict] = None


def get_stock_name(ticker: str) -> Optional[str]:
    """Look up the stock/fund name for a given ticker symbol.

    Tries multiple sources in order:
    1. yfinance (works for US stocks and some CN stocks)
    2. akshare A-share list (works for CN individual stocks)
    3. akshare ETF list (works for CN ETFs/funds)

    Returns None if name cannot be determined.
    """
    ticker_upper = ticker.upper().strip()

    # Try yfinance first (fastest for US stocks)
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker_upper)
        info = stock.info
        name = info.get("shortName") or info.get("longName")
        if name:
            return name
    except Exception as e:
        logger.debug("yfinance name lookup failed for %s: %s", ticker, e)

    # Try akshare for A-shares (individual stocks)
    try:
        name = _get_cn_stock_name_akshare(ticker_upper)
        if name:
            return name
    except Exception as e:
        logger.debug("akshare stock name lookup failed for %s: %s", ticker, e)

    # Try akshare for ETFs/funds
    try:
        name = _get_cn_etf_name_akshare(ticker_upper)
        if name:
            return name
    except Exception as e:
        logger.debug("akshare ETF name lookup failed for %s: %s", ticker, e)

    return None


def _get_cn_stock_name_akshare(ticker: str) -> Optional[str]:
    """Get Chinese stock name using akshare."""
    try:
        import akshare as ak

        # Convert Yahoo Finance ticker to akshare format
        # 600519.SS → 600519 (Shanghai)
        # 000001.SZ → 000001 (Shenzhen)
        code = ticker.split(".")[0]

        # Get A-share list
        df = ak.stock_info_a_code_name()

        # Find the stock
        match = df[df["code"] == code]
        if not match.empty:
            return match.iloc[0]["name"]

        return None
    except Exception as e:
        logger.debug("akshare stock_info_a_code_name failed: %s", e)
        return None


def _get_cn_etf_name_akshare(ticker: str) -> Optional[str]:
    """Get Chinese ETF/fund name using akshare fund_etf_spot_em."""
    global _ETF_CACHE

    try:
        import akshare as ak

        # Extract code without exchange suffix
        code = ticker.split(".")[0]

        # Build cache on first call
        if _ETF_CACHE is None:
            df = ak.fund_etf_spot_em()
            _ETF_CACHE = dict(zip(df["代码"].astype(str), df["名称"]))
            logger.info("Cached %d ETF names", len(_ETF_CACHE))

        return _ETF_CACHE.get(code)
    except Exception as e:
        logger.debug("akshare fund_etf_spot_em failed: %s", e)
        return None
