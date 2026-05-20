import pytest
from tradingagents.dataflows.akshare_data import (
    detect_cn_market,
    _yf_to_akshare_a_code,
    _yf_to_short_code,
    _yf_to_hk_code,
    AkShareError,
)


def test_detect_cn_market_shanghai():
    assert detect_cn_market("600519.SS") == "a_share"


def test_detect_cn_market_shenzhen():
    assert detect_cn_market("000001.SZ") == "a_share"


def test_detect_cn_market_hongkong():
    assert detect_cn_market("0700.HK") == "hk"


def test_detect_cn_market_us():
    assert detect_cn_market("AAPL") == "other"


def test_detect_cn_market_case_insensitive():
    assert detect_cn_market("600519.ss") == "a_share"


def test_yf_to_akshare_a_code_ss():
    assert _yf_to_akshare_a_code("600519.SS") == "sh600519"


def test_yf_to_akshare_a_code_sz():
    assert _yf_to_akshare_a_code("000001.SZ") == "sz000001"


def test_yf_to_short_code():
    assert _yf_to_short_code("600519.SS") == "600519"
    assert _yf_to_short_code("000001.SZ") == "000001"


def test_yf_to_hk_code():
    assert _yf_to_hk_code("0700.HK") == "00700"
    assert _yf_to_hk_code("9988.HK") == "09988"


def _import_build_instrument_context():
    """Load build_instrument_context directly from its source file.

    This avoids triggering tradingagents/agents/__init__.py, which pulls in
    langgraph and langchain_core — packages not installed in the lightweight
    test environment used for unit tests.
    """
    import importlib.util
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent
        / "tradingagents" / "agents" / "utils" / "agent_utils.py"
    )
    spec = importlib.util.spec_from_file_location("agent_utils_direct", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_instrument_context


def test_build_instrument_context_a_share_contains_t1():
    build_instrument_context = _import_build_instrument_context()
    context = build_instrument_context("600519.SS")
    assert "T+1" in context
    assert "CNY" in context


def test_build_instrument_context_hk_contains_hkd():
    build_instrument_context = _import_build_instrument_context()
    context = build_instrument_context("0700.HK")
    assert "HKD" in context or "Hong Kong" in context


def test_build_instrument_context_us_unchanged():
    build_instrument_context = _import_build_instrument_context()
    context = build_instrument_context("AAPL")
    assert "AAPL" in context
    assert "T+1" not in context
