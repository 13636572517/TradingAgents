"""TickFlow API client for A-share market data.

TickFlow (https://tickflow.org) is a RESTful market-data service covering
A-shares (沪深京), ETFs, indices, US and HK markets. Unlike East Money's public
endpoints it is authenticated and not IP-rate-limited per-scrape, which makes it
a stable data source for server-side batch jobs such as the stock screener.

Auth: every request carries an ``x-api-key`` header.
Configure via the ``TICKFLOW_API_KEY`` environment variable, or pass the key
explicitly (the settings UI stores it in the DB and injects it here).

Docs: https://docs.tickflow.org/zh-Hans
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tickflow.org/v1"


def _api_key(explicit: Optional[str] = None) -> str:
    return (explicit or os.getenv("TICKFLOW_API_KEY", "")).strip()


def test_tickflow_connection(api_key: Optional[str] = None) -> dict:
    """Probe TickFlow connectivity with the configured (or supplied) API key.

    Returns a dict shaped like the other vendor status checks (jq/mairui/futu):
      {connected: bool, latency_ms?: int, universe_count?: int, error?: str}
    Uses the lightweight ``GET /universes`` endpoint.
    """
    key = _api_key(api_key)
    if not key:
        return {"connected": False, "error": "未配置 TickFlow API Key"}

    try:
        import httpx
    except ImportError:
        return {"connected": False, "error": "httpx 未安装"}

    try:
        start = time.time()
        # trust_env=False bypasses system proxies that may lack required packages
        with httpx.Client(trust_env=False, timeout=12) as client:
            resp = client.get(f"{BASE_URL}/universes", headers={"x-api-key": key})
        latency_ms = int((time.time() - start) * 1000)
    except Exception as exc:
        return {"connected": False, "error": f"网络请求失败: {exc}"[:200]}

    if resp.status_code == 401 or resp.status_code == 403:
        return {"connected": False, "latency_ms": latency_ms,
                "error": "API Key 无效或无权限 (HTTP %d)" % resp.status_code}
    if resp.status_code == 429:
        # Key is valid but currently rate-limited — still proves connectivity.
        return {"connected": True, "latency_ms": latency_ms,
                "error": "请求频率受限 (HTTP 429)，但 Key 有效"}
    if resp.status_code != 200:
        return {"connected": False, "latency_ms": latency_ms,
                "error": "HTTP %d: %s" % (resp.status_code, resp.text[:120])}

    try:
        data = resp.json().get("data", [])
        count = len(data) if isinstance(data, list) else None
    except Exception:
        count = None

    return {"connected": True, "latency_ms": latency_ms, "universe_count": count}
