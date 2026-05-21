from typing import Annotated

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .akshare_data import (
    AkShareError,
    get_cn_stock_data,
    get_cn_news,
    get_cn_global_news,
    get_cn_fundamentals,
    get_cn_balance_sheet,
    get_cn_cashflow,
    get_cn_income_statement,
    get_cn_indicators,
)
from .futu_data import (
    FutuError,
    get_futu_stock_data,
    get_futu_fundamentals,
    get_futu_balance_sheet,
    get_futu_cashflow,
    get_futu_income_statement,
)
from .jq_data import (
    JQError,
    get_jq_stock_data,
    get_jq_indicators,
    get_jq_fundamentals,
    get_jq_balance_sheet,
    get_jq_income_statement,
    get_jq_cashflow,
)
from .baostock_data import (
    BaoStockError,
    get_bs_stock_data,
    get_bs_indicators,
    get_bs_fundamentals,
    get_bs_balance_sheet,
    get_bs_income_statement,
    get_bs_cashflow,
)
from .mairui_data import (
    MaiRuiError,
    get_mr_stock_data,
    get_mr_indicators,
    get_mr_fundamentals,
)

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "akshare",
    "futu",
    "joinquant",
    "baostock",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "akshare": get_cn_stock_data,
        "futu": get_futu_stock_data,
        "joinquant": get_jq_stock_data,
        "baostock": get_bs_stock_data,
        "mairui": get_mr_stock_data,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "akshare": get_cn_indicators,
        "joinquant": get_jq_indicators,
        "baostock": get_bs_indicators,
        "mairui": get_mr_indicators,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "akshare": get_cn_fundamentals,
        "futu": get_futu_fundamentals,
        "joinquant": get_jq_fundamentals,
        "baostock": get_bs_fundamentals,
        "mairui": get_mr_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "akshare": get_cn_balance_sheet,
        "futu": get_futu_balance_sheet,
        "joinquant": get_jq_balance_sheet,
        "baostock": get_bs_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "akshare": get_cn_cashflow,
        "futu": get_futu_cashflow,
        "joinquant": get_jq_cashflow,
        "baostock": get_bs_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "akshare": get_cn_income_statement,
        "futu": get_futu_income_statement,
        "joinquant": get_jq_income_statement,
        "baostock": get_bs_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "akshare": get_cn_news,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "akshare": get_cn_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        # akshare not registered — A-share insider disclosures are limited
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None, ticker_hint: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.

    Resolution order:
    1. market_vendor_overrides — ticker-suffix-based auto-detection (.SS → akshare)
    2. tool_vendors config — per-tool override
    3. data_vendors config — per-category default
    """
    config = get_config()

    # 1. Ticker-suffix-based auto-detection
    if ticker_hint:
        market_overrides = config.get("market_vendor_overrides", {})
        ticker_upper = ticker_hint.upper()
        for suffix, vendor in market_overrides.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return vendor

        # Futu for US stocks (no exchange suffix = pure ticker like AAPL, CANG)
        is_us_stock = (
            "." not in ticker_upper
            and not ticker_upper.endswith("-USD")
            and config.get("futu_enabled", False)
        )
        if is_us_stock and method in ("get_stock_data", "get_fundamentals",
                                       "get_balance_sheet", "get_cashflow",
                                       "get_income_statement"):
            return "futu"

    # 2. Tool-level override
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # 3. Category-level default
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor with fallback support.

    Ticker-hint extraction:
    - For ticker-first methods (get_stock_data, get_news, etc.): first arg is ticker
    - For date-first methods (get_global_news): use config["current_ticker"] as hint
    """
    category = get_category_for_method(method)

    # Extract ticker hint for market-based auto-detection
    ticker_hint = None
    if args and isinstance(args[0], str):
        first_arg = args[0]
        # Date strings look like YYYY-MM-DD
        is_date = (
            len(first_arg) == 10
            and first_arg[4:5] == "-"
            and first_arg[7:8] == "-"
        )
        if not is_date:
            ticker_hint = first_arg
        else:
            ticker_hint = get_config().get("current_ticker")

    vendor_config = get_vendor(category, method, ticker_hint=ticker_hint)
    primary_vendors = [v.strip() for v in vendor_config.split(",")]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except (AlphaVantageRateLimitError, AkShareError, FutuError, JQError, BaoStockError, MaiRuiError):
            continue  # All trigger fallback to next vendor

    raise RuntimeError(f"No available vendor for '{method}'")
