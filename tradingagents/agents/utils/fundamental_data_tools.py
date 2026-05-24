from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.akshare_data import is_etf, get_cn_etf_fundamentals

_ETF_STMT_MSG = (
    "This ticker is an ETF (Exchange Traded Fund). ETFs hold a basket of securities "
    "and do not have traditional corporate financial statements (balance sheet / "
    "income statement / cash flow). Please use get_fundamentals for ETF-specific data "
    "(price performance, top holdings, NAV history)."
)


@tool
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol.
    For ETFs, returns ETF-specific data (NAV, holdings, price performance).
    For stocks, uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company or ETF
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing comprehensive fundamental data
    """
    if is_etf(ticker):
        return get_cn_etf_fundamentals(ticker, curr_date)
    return route_to_vendor("get_fundamentals", ticker, curr_date)


@tool
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """Retrieve balance sheet data. Returns ETF notice for ETF tickers."""
    if is_etf(ticker):
        return _ETF_STMT_MSG
    return route_to_vendor("get_balance_sheet", ticker, freq, curr_date)


@tool
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve cash flow statement data for a given ticker symbol.
    Returns ETF notice for ETF tickers; uses configured vendor for stocks.
    """
    if is_etf(ticker):
        return _ETF_STMT_MSG
    return route_to_vendor("get_cashflow", ticker, freq, curr_date)


@tool
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve income statement data for a given ticker symbol.
    Returns ETF notice for ETF tickers; uses configured vendor for stocks.
    """
    if is_etf(ticker):
        return _ETF_STMT_MSG
    return route_to_vendor("get_income_statement", ticker, freq, curr_date)