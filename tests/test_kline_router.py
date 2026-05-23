# tests/test_kline_router.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)

SAMPLE_DATA = [
    {"date": "2025-01-02", "open": 7.50, "high": 7.65,
     "low": 7.45, "close": 7.60, "volume": 1234567},
    {"date": "2025-01-03", "open": 7.60, "high": 7.80,
     "low": 7.55, "close": 7.75, "volume": 9876543},
]


@pytest.mark.unit
@patch("server.routers.kline._fetch_with_fallback", return_value=(SAMPLE_DATA, None))
def test_kline_success(mock_fetch):
    resp = client.get("/api/kline/601985.SS?time_range=1M")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "601985.SS"
    assert body["range"] == "1M"
    assert len(body["data"]) == 2
    assert body["error"] is None
    first = body["data"][0]
    assert set(first.keys()) == {"date", "open", "high", "low", "close", "volume"}


@pytest.mark.unit
@patch("server.routers.kline._fetch_with_fallback", return_value=([], "所有数据源均不可用"))
def test_kline_all_sources_fail(mock_fetch):
    resp = client.get("/api/kline/INVALID.XX")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["error"] == "所有数据源均不可用"
    assert "max-age" not in resp.headers.get("cache-control", "")


@pytest.mark.unit
@patch("server.routers.kline._fetch_with_fallback", return_value=(SAMPLE_DATA, None))
def test_kline_invalid_range_defaults_to_1y(mock_fetch):
    resp = client.get("/api/kline/601985.SS?time_range=INVALID")
    assert resp.status_code == 200
    assert resp.json()["range"] == "1Y"


@pytest.mark.unit
def test_kline_cache_header():
    with patch("server.routers.kline._fetch_with_fallback", return_value=(SAMPLE_DATA, None)):
        resp = client.get("/api/kline/601985.SS")
    assert "max-age=3600" in resp.headers.get("cache-control", "")


@pytest.mark.unit
def test_kline_rejects_invalid_ticker():
    """Path traversal attempts must not return valid kline data.

    FastAPI/Starlette rejects percent-encoded slashes (%2F) in path segments at
    the routing layer before the handler runs, returning 404.  Dot-only segments
    that *do* reach the handler (e.g. ``...``) are caught by
    safe_ticker_component and return 200 with an error payload and no-store.
    """
    # %2F in a path segment → rejected at framework level before handler runs
    resp = client.get("/api/kline/..%2F..%2Fetc")
    assert resp.status_code == 404

    # All-dots segment that reaches the handler → safe_ticker_component rejects it
    resp2 = client.get("/api/kline/...")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["data"] == []
    assert body["error"] is not None
    assert "no-store" in resp2.headers.get("cache-control", "").lower()


@pytest.mark.unit
def test_short_code():
    from server.routers.kline import _short_code, _bs_code, _hk_code, _jq_code
    assert _short_code("600519.SS") == "600519"
    assert _bs_code("600519.SS") == "sh.600519"
    assert _bs_code("000001.SZ") == "sz.000001"
    assert _hk_code("0700.HK") == "00700"
    assert _jq_code("600519.SS") == "600519.XSHG"
    assert _jq_code("000001.SZ") == "000001.XSHE"


@pytest.mark.unit
def test_is_etf():
    from server.routers.kline import _is_etf
    assert _is_etf("159158.SZ") is True
    assert _is_etf("510050.SS") is True
    assert _is_etf("601985.SS") is False
    assert _is_etf("AAPL") is False
    assert _is_etf("520000.SS") is True
    assert _is_etf("588000.SS") is True
