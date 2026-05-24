"""Tavily Search news fetcher (fallback for international news).

Requires TAVILY_API_KEY environment variable (free at https://app.tavily.com).
Free tier: 1 000 requests/month, accessible from Chinese servers.
Uses Tavily's AI-powered web search to find financial news.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_API_URL = "https://api.tavily.com/search"


class TavilyError(Exception):
    pass


def _get_key() -> str:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise TavilyError("TAVILY_API_KEY env var not set")
    return key


def _search(query: str, max_results: int = 10, timeout: float = 20.0) -> list[dict]:
    payload = json.dumps({
        "api_key": _get_key(),
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }).encode()
    req = Request(
        _API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "tradingagents/0.2"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
        raise TavilyError(f"Tavily request failed: {e}") from e
    results = data.get("results", [])
    if not results:
        raise TavilyError(f"Tavily returned no results for: {query}")
    return results


def _fmt_results(results: list[dict], header: str) -> str:
    lines = [header + "\n"]
    for r in results:
        title = r.get("title") or "No title"
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        lines.append(f"### {title}")
        if content:
            lines.append(content[:300] + ("…" if len(content) > 300 else ""))
        if url:
            lines.append(f"Link: {url}")
        lines.append("")
    return "\n".join(lines)


def get_news_tavily(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch ticker-specific news via Tavily Search."""
    symbol = ticker.upper().split(".")[0]
    query = f"{symbol} stock news financial analysis {start_date} to {end_date}"
    results = _search(query, max_results=10)
    return _fmt_results(
        results,
        f"## {ticker} News, from {start_date} to {end_date} (Tavily Search):",
    )


def get_global_news_tavily(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Fetch global macro/market news via Tavily Search."""
    from .config import get_config
    config = get_config()
    if look_back_days is None:
        look_back_days = config.get("global_news_lookback_days", 7)
    if limit is None:
        limit = config.get("global_news_article_limit", 10)

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_str = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    query = f"global stock market financial news macroeconomics {start_str} to {curr_date}"
    results = _search(query, max_results=min(limit * 2, 20))[:limit]
    return _fmt_results(
        results,
        f"## Global Market News, from {start_str} to {curr_date} (Tavily Search):",
    )
