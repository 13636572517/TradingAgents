import sys
import types
import pytest
from unittest.mock import patch, MagicMock

# Stub out heavy optional dependencies that are not installed in the test environment.
# yfinance needs sub-module stubs because stockstats_utils does
# `from yfinance.exceptions import YFRateLimitError`.
if "yfinance" not in sys.modules:
    _yf_mock = MagicMock()
    _yf_exceptions = types.ModuleType("yfinance.exceptions")
    _yf_exceptions.YFRateLimitError = type("YFRateLimitError", (Exception,), {})
    sys.modules["yfinance"] = _yf_mock
    sys.modules["yfinance.exceptions"] = _yf_exceptions

for _mod in (
    "pandas",
    "pandas_market_calendars",
    "stockstats",
    "questionary",
    "akshare",
    "bs4",
    "requests",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def reset_config():
    """Restore default config after each test to prevent state leaks."""
    yield
    set_config(DEFAULT_CONFIG.copy())


def test_get_vendor_ss_returns_akshare():
    """Tickers with .SS suffix should route to akshare."""
    from tradingagents.dataflows.interface import get_vendor
    from tradingagents.dataflows.config import set_config, get_config
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["market_vendor_overrides"] = {".SS": "akshare", ".SZ": "akshare"}
    set_config(config)

    vendor = get_vendor("core_stock_apis", "get_stock_data", ticker_hint="600519.SS")
    assert vendor == "akshare"


def test_get_vendor_sz_returns_akshare():
    from tradingagents.dataflows.interface import get_vendor
    from tradingagents.dataflows.config import set_config
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["market_vendor_overrides"] = {".SS": "akshare", ".SZ": "akshare"}
    set_config(config)

    vendor = get_vendor("core_stock_apis", "get_stock_data", ticker_hint="000001.SZ")
    assert vendor == "akshare"


def test_get_vendor_us_not_affected():
    """US tickers must continue using configured vendor, not akshare."""
    from tradingagents.dataflows.interface import get_vendor
    from tradingagents.dataflows.config import set_config
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["market_vendor_overrides"] = {".SS": "akshare", ".SZ": "akshare"}
    set_config(config)

    vendor = get_vendor("core_stock_apis", "get_stock_data", ticker_hint="AAPL")
    assert vendor != "akshare"


def test_route_to_vendor_akshare_error_falls_back_to_yfinance():
    """AkShareError must trigger fallback to yfinance, not propagate."""
    from tradingagents.dataflows.interface import route_to_vendor
    from tradingagents.dataflows.akshare_data import AkShareError
    from tradingagents.dataflows.config import set_config
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["market_vendor_overrides"] = {".SS": "akshare", ".SZ": "akshare"}
    set_config(config)

    from tradingagents.dataflows.alpha_vantage_common import AlphaVantageRateLimitError
    import tradingagents.dataflows.interface as _iface

    mock_akshare = MagicMock(side_effect=AkShareError("network error"))
    mock_alpha = MagicMock(side_effect=AlphaVantageRateLimitError("rate limited"))
    mock_yf = MagicMock(return_value="yfinance_data")

    # VENDOR_METHODS holds captured function references at import time, so we
    # directly replace them for the duration of this test.
    _saved = dict(_iface.VENDOR_METHODS["get_stock_data"])
    _iface.VENDOR_METHODS["get_stock_data"]["akshare"] = mock_akshare
    _iface.VENDOR_METHODS["get_stock_data"]["alpha_vantage"] = mock_alpha
    _iface.VENDOR_METHODS["get_stock_data"]["yfinance"] = mock_yf
    try:
        result = route_to_vendor("get_stock_data", "600519.SS", "2024-01-01", "2024-01-31")
        mock_akshare.assert_called_once_with("600519.SS", "2024-01-01", "2024-01-31")
        assert result == "yfinance_data"
        mock_yf.assert_called_once()
    finally:
        _iface.VENDOR_METHODS["get_stock_data"].update(_saved)
