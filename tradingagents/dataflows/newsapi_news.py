"""NewsAPI.org news fetcher.

Requires NEWSAPI_KEY environment variable (free at https://newsapi.org/register).
Free tier: 100 requests/day, accessible from Chinese servers.
Covers Reuters, CNBC, Bloomberg, BBC, Financial Times, etc.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

logger = logging.getLogger(__name__)

_EVERYTHING = "https://newsapi.org/v2/everything"
_TOP_HEADLINES = "https://newsapi.org/v2/top-headlines"


class NewsAPIError(Exception):
    pass


def _get_key() -> str:
    key = os.getenv("NEWSAPI_KEY", "").strip()
    if not key:
        raise NewsAPIError("NEWSAPI_KEY env var not set")
    return key


def _get(url: str, params: dict, timeout: float = 15.0) -> dict:
    full_url = url + "?" + urlencode(params)
    req = Request(full_url, headers={"User-Agent": "tradingagents/0.2"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
        raise NewsAPIError(f"NewsAPI request failed: {e}") from e
    if data.get("status") != "ok":
        raise NewsAPIError(f"NewsAPI error: {data.get('message', data)}")
    return data


def get_news_newsapi(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch ticker-specific news from NewsAPI.org.

    Searches for the ticker symbol in business/finance news sources.
    """
    key = _get_key()
    params = {
        "q": ticker.upper().split(".")[0],
        "from": start_date,
        "to": end_date,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 20,
        "apiKey": key,
    }
    data = _get(_EVERYTHING, params)
    articles = data.get("articles", [])
    if not articles:
        raise NewsAPIError(f"No NewsAPI articles for {ticker}")

    lines = [f"## {ticker} News, from {start_date} to {end_date} (NewsAPI):\n"]
    for a in articles:
        title = a.get("title") or "No title"
        source = (a.get("source") or {}).get("name", "Unknown")
        desc = (a.get("description") or "").strip()
        url = a.get("url", "")
        lines.append(f"### {title} (source: {source})")
        if desc:
            lines.append(desc[:280] + ("…" if len(desc) > 280 else ""))
        if url:
            lines.append(f"Link: {url}")
        lines.append("")
    return "\n".join(lines)


def get_global_news_newsapi(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Fetch global market/macro news from NewsAPI.org top business headlines."""
    from .config import get_config
    config = get_config()
    if look_back_days is None:
        look_back_days = config.get("global_news_lookback_days", 7)
    if limit is None:
        limit = config.get("global_news_article_limit", 10)

    key = _get_key()
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)

    params = {
        "category": "business",
        "language": "en",
        "pageSize": min(limit * 2, 100),
        "apiKey": key,
    }
    data = _get(_TOP_HEADLINES, params)
    articles = data.get("articles", [])
    if not articles:
        raise NewsAPIError("No NewsAPI global articles found")

    start_str = start_dt.strftime("%Y-%m-%d")
    lines = [f"## Global Market News, from {start_str} to {curr_date} (NewsAPI):\n"]
    count = 0
    for a in articles:
        if count >= limit:
            break
        title = a.get("title") or "No title"
        source = (a.get("source") or {}).get("name", "Unknown")
        desc = (a.get("description") or "").strip()
        url = a.get("url", "")
        lines.append(f"### {title} (source: {source})")
        if desc:
            lines.append(desc[:280] + ("…" if len(desc) > 280 else ""))
        if url:
            lines.append(f"Link: {url}")
        lines.append("")
        count += 1
    return "\n".join(lines)
