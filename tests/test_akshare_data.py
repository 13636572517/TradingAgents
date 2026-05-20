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
