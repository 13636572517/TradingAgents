# Phase B — CN Market Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AkShare as a data vendor so A-share (.SS/.SZ) and H-share (.HK) tickers are automatically routed to Chinese data sources with no changes to US-stock code paths.

**Architecture:** New `akshare_data.py` module registers as a third vendor in the existing `route_to_vendor` fallback chain. Ticker-suffix detection in `get_vendor()` selects AkShare automatically for .SS/.SZ tickers. Sentiment analyst gains a CN/HK branch that replaces Reddit/StockTwits with Eastmoney news.

**Tech Stack:** Python, AkShare ≥1.9.0, existing LangChain tool wrappers, pytest

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `tradingagents/dataflows/akshare_data.py` | All AkShare data functions + ticker helpers |
| Modify | `tradingagents/dataflows/interface.py` | Register akshare vendor; ticker-hint routing; AkShareError fallback |
| Modify | `tradingagents/default_config.py` | A-share benchmarks; `market_vendor_overrides` |
| Modify | `tradingagents/graph/trading_graph.py` | Write `current_ticker` to config in `propagate()` |
| Modify | `tradingagents/agents/utils/agent_utils.py` | CN/HK market rules in `build_instrument_context` |
| Modify | `tradingagents/agents/analysts/sentiment_analyst.py` | CN/HK branch replacing Reddit/StockTwits |
| Modify | `cli/utils.py` | Add A-share/HK ticker examples |
| Modify | `pyproject.toml` | Add `akshare>=1.9.0` dependency |
| Create | `tests/test_akshare_data.py` | Unit tests for pure ticker-helper functions |
| Create | `tests/test_cn_vendor_routing.py` | Unit tests for vendor routing with .SS/.SZ tickers |

---

## Task 1: Create `akshare_data.py` with ticker helpers

**Files:**
- Create: `tradingagents/dataflows/akshare_data.py`
- Create: `tests/test_akshare_data.py`

- [ ] **Step 1: Write failing tests for pure ticker-helper functions**

```python
# tests/test_akshare_data.py
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/michael/tradingagents/TradingAgents
python -m pytest tests/test_akshare_data.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'tradingagents.dataflows.akshare_data'`

- [ ] **Step 3: Create `akshare_data.py` with the full implementation**

```python
# tradingagents/dataflows/akshare_data.py
"""AkShare-based data provider for Chinese A-share and Hong Kong markets.

Ticker format conventions (Yahoo Finance style, used throughout this project):
  A-share Shanghai : 600519.SS
  A-share Shenzhen : 000001.SZ
  Hong Kong        : 0700.HK

AkShare internal formats (converted inside this module):
  A-share          : sh600519  /  sz000001
  6-digit code     : 600519    /  000001
  HK 5-digit       : 00700
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Optional

import pandas as pd
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


class AkShareError(Exception):
    """Raised when AkShare fails in a way that should trigger vendor fallback."""
    pass


# ── Ticker helpers ─────────────────────────────────────────────────────────────

def detect_cn_market(ticker: str) -> str:
    """Return 'a_share', 'hk', or 'other' based on Yahoo Finance ticker suffix."""
    upper = ticker.upper()
    if upper.endswith(".SS") or upper.endswith(".SZ"):
        return "a_share"
    if upper.endswith(".HK"):
        return "hk"
    return "other"


def _yf_to_akshare_a_code(ticker: str) -> str:
    """600519.SS → sh600519,  000001.SZ → sz000001"""
    parts = ticker.upper().rsplit(".", 1)
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    if suffix == "SS":
        return f"sh{code}"
    elif suffix == "SZ":
        return f"sz{code}"
    return code


def _yf_to_short_code(ticker: str) -> str:
    """600519.SS → 600519"""
    return ticker.upper().rsplit(".", 1)[0]


def _yf_to_hk_code(ticker: str) -> str:
    """0700.HK → 00700  (5-digit with leading zero for AkShare)"""
    code = ticker.upper().replace(".HK", "")
    return code.zfill(5)


# ── A-share price data ─────────────────────────────────────────────────────────

def get_cn_stock_data(
    symbol: Annotated[str, "ticker symbol in Yahoo Finance format, e.g. 600519.SS"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get A-share OHLCV data using AkShare (backward-dividend-adjusted 后复权)."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed. Run: pip install akshare")
    try:
        ak_code = _yf_to_akshare_a_code(symbol)
        df = ak.stock_zh_a_hist(
            symbol=ak_code,
            period="daily",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
            adjust="hfq",
        )
        if df is None or df.empty:
            return f"No data found for {symbol} between {start_date} and {end_date}"

        col_map = {
            "日期": "Date", "开盘": "Open", "收盘": "Close",
            "最高": "High", "最低": "Low", "成交量": "Volume",
            "成交额": "Amount(CNY)", "涨跌幅": "ChangePercent(%)",
            "涨跌额": "Change(CNY)", "换手率": "Turnover(%)",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        header = (
            f"# A-share stock data for {symbol.upper()} from {start_date} to {end_date}\n"
            f"# Total records: {len(df)}\n"
            f"# Currency: CNY | Adjusted: post-dividend (后复权)\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.to_csv(index=False)
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_stock_data failed for %s: %s", symbol, e)
        raise AkShareError(f"AkShare data fetch failed for {symbol}: {e}") from e


# ── A-share news ───────────────────────────────────────────────────────────────

def get_cn_news(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Get stock-specific news from Eastmoney (东方财富) for an A-share ticker."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        short_code = _yf_to_short_code(ticker)
        news_df = ak.stock_news_em(symbol=short_code)
        if news_df is None or news_df.empty:
            return f"No news found for {ticker}"

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        count = 0
        for _, row in news_df.iterrows():
            pub_time = str(row.get("发布时间", ""))
            if pub_time:
                try:
                    pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
                    if not (start_dt <= pub_dt <= end_dt + relativedelta(days=1)):
                        continue
                except (ValueError, TypeError):
                    pass

            title = row.get("新闻标题", row.get("标题", "No title"))
            source = row.get("文章来源", row.get("来源", "Unknown"))
            link = row.get("新闻链接", row.get("链接", ""))
            content = str(row.get("新闻内容", ""))

            news_str += f"### {title} (来源: {source})\n"
            if content and len(content) > 10:
                news_str += content[:300] + ("…" if len(content) > 300 else "") + "\n"
            if link:
                news_str += f"Link: {link}\n"
            news_str += "\n"
            count += 1
            if count >= 20:
                break

        if count == 0:
            return f"No news found for {ticker} between {start_date} and {end_date}"
        return f"## {ticker} 新闻资讯 ({start_date} 至 {end_date}):\n\n{news_str}"
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_news failed for %s: %s", ticker, e)
        raise AkShareError(f"AkShare news fetch failed for {ticker}: {e}") from e


def get_cn_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Get Chinese macro/market news using Eastmoney index news as market proxy."""
    from .config import get_config
    config = get_config()
    if look_back_days is None:
        look_back_days = config.get("global_news_lookback_days", 7)
    if limit is None:
        limit = config.get("global_news_article_limit", 10)

    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        market_symbols = ["000001", "399001"]
        all_articles: list = []
        seen_titles: set = set()

        for sym in market_symbols:
            try:
                df = ak.stock_news_em(symbol=sym)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        title = str(row.get("新闻标题", row.get("标题", "")))
                        if title and title not in seen_titles:
                            seen_titles.add(title)
                            all_articles.append(row)
                        if len(all_articles) >= limit * 2:
                            break
            except Exception:
                continue
            if len(all_articles) >= limit * 2:
                break

        if not all_articles:
            return f"No Chinese market news found for {curr_date}"

        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - relativedelta(days=look_back_days)

        news_str = ""
        count = 0
        for row in all_articles:
            pub_time = str(row.get("发布时间", ""))
            if pub_time:
                try:
                    pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
                    if pub_dt > curr_dt + relativedelta(days=1):
                        continue
                except (ValueError, TypeError):
                    pass

            title = row.get("新闻标题", row.get("标题", "No title"))
            source = row.get("文章来源", row.get("来源", "Unknown"))
            link = row.get("新闻链接", row.get("链接", ""))

            news_str += f"### {title} (来源: {source})\n"
            if link:
                news_str += f"Link: {link}\n"
            news_str += "\n"
            count += 1
            if count >= limit:
                break

        if count == 0:
            return f"No Chinese market news found for {curr_date}"

        start_date_str = start_dt.strftime("%Y-%m-%d")
        return f"## 中国市场宏观新闻 ({start_date_str} 至 {curr_date}):\n\n{news_str}"
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_global_news failed: %s", e)
        raise AkShareError(f"AkShare global news failed: {e}") from e


# ── A-share fundamentals ───────────────────────────────────────────────────────

def get_cn_fundamentals(
    ticker: Annotated[str, "ticker symbol in Yahoo Finance format e.g. 600519.SS"],
    curr_date: Annotated[str, "current date (unused for AkShare)"] = None,
) -> str:
    """Get A-share company fundamentals from Eastmoney via AkShare."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        short_code = _yf_to_short_code(ticker)
        info_df = ak.stock_individual_info_em(stock=short_code)
        if info_df is None or info_df.empty:
            return f"No fundamentals data found for {ticker}"

        lines = []
        for _, row in info_df.iterrows():
            if len(row) >= 2:
                item = str(row.iloc[0])
                value = str(row.iloc[1])
                if item.lower() != "nan" and value.lower() != "nan":
                    lines.append(f"{item}: {value}")

        header = (
            f"# Company Fundamentals for {ticker.upper()} (A-share)\n"
            f"# Source: Eastmoney (东方财富)\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + "\n".join(lines)
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_fundamentals failed for %s: %s", ticker, e)
        raise AkShareError(f"AkShare fundamentals failed for {ticker}: {e}") from e


def get_cn_balance_sheet(
    ticker: Annotated[str, "ticker symbol in Yahoo Finance format e.g. 600519.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share balance sheet (资产负债表) from Sina Finance via AkShare."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        ak_code = _yf_to_akshare_a_code(ticker)
        df = ak.stock_financial_report_sina(stock=ak_code, symbol="资产负债表")
        if df is None or df.empty:
            return f"No balance sheet data found for {ticker}"
        header = (
            f"# Balance Sheet (资产负债表) for {ticker.upper()}\n"
            f"# Source: Sina Finance | Currency: CNY\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.head(8).to_csv(index=False)
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_balance_sheet failed for %s: %s", ticker, e)
        raise AkShareError(f"AkShare balance sheet failed for {ticker}: {e}") from e


def get_cn_cashflow(
    ticker: Annotated[str, "ticker symbol in Yahoo Finance format e.g. 600519.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share cash flow statement (现金流量表) from Sina Finance via AkShare."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        ak_code = _yf_to_akshare_a_code(ticker)
        df = ak.stock_financial_report_sina(stock=ak_code, symbol="现金流量表")
        if df is None or df.empty:
            return f"No cash flow data found for {ticker}"
        header = (
            f"# Cash Flow Statement (现金流量表) for {ticker.upper()}\n"
            f"# Source: Sina Finance | Currency: CNY\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.head(8).to_csv(index=False)
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_cashflow failed for %s: %s", ticker, e)
        raise AkShareError(f"AkShare cashflow failed for {ticker}: {e}") from e


def get_cn_income_statement(
    ticker: Annotated[str, "ticker symbol in Yahoo Finance format e.g. 600519.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share income statement (利润表) from Sina Finance via AkShare."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        ak_code = _yf_to_akshare_a_code(ticker)
        df = ak.stock_financial_report_sina(stock=ak_code, symbol="利润表")
        if df is None or df.empty:
            return f"No income statement data found for {ticker}"
        header = (
            f"# Income Statement (利润表) for {ticker.upper()}\n"
            f"# Source: Sina Finance | Currency: CNY\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.head(8).to_csv(index=False)
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_income_statement failed for %s: %s", ticker, e)
        raise AkShareError(f"AkShare income statement failed for {ticker}: {e}") from e


# ── Sentiment data ─────────────────────────────────────────────────────────────

def fetch_eastmoney_news_for_sentiment(ticker: str, limit: int = 30) -> str:
    """Fetch recent Eastmoney news for a CN/HK ticker for sentiment analysis.

    Degrades gracefully — returns a placeholder string on failure so the
    sentiment analyst always sees something.
    """
    try:
        import akshare as ak
        market = detect_cn_market(ticker)
        if market == "a_share":
            short_code = _yf_to_short_code(ticker)
        elif market == "hk":
            short_code = _yf_to_hk_code(ticker)
        else:
            return f"<不适用于 {ticker} (非A股/港股)>"

        news_df = ak.stock_news_em(symbol=short_code)
        if news_df is None or news_df.empty:
            return f"<东方财富: 暂无 {ticker} 的新闻资讯>"

        lines = [f"东方财富财经新闻 — {ticker} 最新资讯（共 {min(limit, len(news_df))} 条）:"]
        for i, (_, row) in enumerate(news_df.iterrows()):
            if i >= limit:
                break
            title = str(row.get("新闻标题", row.get("标题", ""))).replace("\n", " ").strip()
            source = str(row.get("文章来源", row.get("来源", "")))
            pub_time = str(row.get("发布时间", ""))[:16]
            lines.append(f"  [{pub_time} · {source}] {title}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("fetch_eastmoney_news_for_sentiment failed for %s: %s", ticker, e)
        return f"<东方财富数据获取失败: {type(e).__name__}>"
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_akshare_data.py -v
```

Expected: all 9 tests PASS (pure functions, no network calls)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/akshare_data.py tests/test_akshare_data.py
git commit -m "feat(dataflows): add akshare_data module with CN/HK ticker helpers and data functions"
```

---

## Task 2: Update `interface.py` — register AkShare vendor + ticker-hint routing

**Files:**
- Modify: `tradingagents/dataflows/interface.py`
- Create: `tests/test_cn_vendor_routing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cn_vendor_routing.py
import pytest
from unittest.mock import patch, MagicMock


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

    with patch("tradingagents.dataflows.akshare_data.get_cn_stock_data",
               side_effect=AkShareError("network error")):
        with patch("tradingagents.dataflows.y_finance.get_YFin_data_online",
                   return_value="yfinance_data") as mock_yf:
            result = route_to_vendor("get_stock_data", "600519.SS", "2024-01-01", "2024-01-31")
            assert result == "yfinance_data"
            mock_yf.assert_called_once()
```

- [ ] **Step 2: Run tests — expect fail**

```bash
python -m pytest tests/test_cn_vendor_routing.py -v 2>&1 | head -30
```

Expected: FAIL — `get_vendor` doesn't accept `ticker_hint` yet

- [ ] **Step 3: Apply changes to `interface.py`**

At the top of `tradingagents/dataflows/interface.py`, after the existing imports, add:

```python
from .akshare_data import (
    AkShareError,
    get_cn_stock_data,
    get_cn_news,
    get_cn_global_news,
    get_cn_fundamentals,
    get_cn_balance_sheet,
    get_cn_cashflow,
    get_cn_income_statement,
)
```

Replace `VENDOR_LIST`:

```python
VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "akshare",
]
```

Replace `VENDOR_METHODS` with:

```python
VENDOR_METHODS = {
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "akshare": get_cn_stock_data,
    },
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        # akshare not registered — falls back to yfinance automatically
    },
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "akshare": get_cn_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "akshare": get_cn_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "akshare": get_cn_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "akshare": get_cn_income_statement,
    },
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
```

Replace `get_vendor` function:

```python
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

    # 2. Tool-level override
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # 3. Category-level default
    return config.get("data_vendors", {}).get(category, "default")
```

Replace `route_to_vendor` function:

```python
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
        except (AlphaVantageRateLimitError, AkShareError):
            continue  # Both trigger fallback to next vendor

    raise RuntimeError(f"No available vendor for '{method}'")
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_cn_vendor_routing.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 5: Confirm existing tests still pass**

```bash
python -m pytest tests/test_dataflows_config.py tests/test_ticker_symbol_handling.py -v
```

Expected: all existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/interface.py tests/test_cn_vendor_routing.py
git commit -m "feat(dataflows): register akshare vendor with ticker-suffix auto-routing and AkShareError fallback"
```

---

## Task 3: Update `default_config.py` — A-share benchmarks + market_vendor_overrides

**Files:**
- Modify: `tradingagents/default_config.py`

- [ ] **Step 1: Replace `benchmark_map` to add A-share entries**

Find the `benchmark_map` block and replace it with:

```python
"benchmark_map": {
    ".NS":  "^NSEI",
    ".BO":  "^BSESN",
    ".T":   "^N225",
    ".HK":  "^HSI",
    ".L":   "^FTSE",
    ".TO":  "^GSPTSE",
    ".AX":  "^AXJO",
    ".SS":  "000001.SS",   # 上证综合指数
    ".SZ":  "399001.SZ",   # 深证成份指数
    "":     "SPY",
},
```

- [ ] **Step 2: Add `market_vendor_overrides` after the `tool_vendors` block**

Find the `"tool_vendors"` block and add immediately after it:

```python
    # Market-based vendor overrides — takes precedence over data_vendors and tool_vendors.
    # Tickers whose suffix matches are automatically routed to the mapped vendor.
    # HK (.HK) deliberately omitted — yfinance has good HK coverage.
    "market_vendor_overrides": {
        ".SS": "akshare",
        ".SZ": "akshare",
    },
```

- [ ] **Step 3: Verify env-override tests still pass**

```bash
python -m pytest tests/test_env_overrides.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tradingagents/default_config.py
git commit -m "feat(config): add A-share benchmarks (.SS/.SZ) and market_vendor_overrides for akshare routing"
```

---

## Task 4: Update `trading_graph.py` — write `current_ticker` to config

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`

- [ ] **Step 1: Find the `propagate` method (line ~295) and add one line after `self.ticker = company_name`**

Current code:
```python
def propagate(self, company_name, trade_date, asset_type: str = "stock"):
    ...
    self.ticker = company_name
    # Resolve any pending memory-log entries...
```

Add `set_config({"current_ticker": company_name})` immediately after `self.ticker = company_name`:

```python
def propagate(self, company_name, trade_date, asset_type: str = "stock"):
    ...
    self.ticker = company_name
    set_config({"current_ticker": company_name})
    # Resolve any pending memory-log entries...
```

`set_config` is already imported at the top of the file (line 27).

- [ ] **Step 2: Verify `set_config` is already imported**

```bash
grep "from tradingagents.dataflows.config import" tradingagents/graph/trading_graph.py
```

Expected: line containing `set_config`

- [ ] **Step 3: Run the checkpoint test to confirm no regressions**

```bash
python -m pytest tests/test_checkpoint_resume.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tradingagents/graph/trading_graph.py
git commit -m "feat(graph): write current_ticker to config in propagate() for global-news CN routing"
```

---

## Task 5: Update `agent_utils.py` — CN/HK market context in `build_instrument_context`

**Files:**
- Modify: `tradingagents/agents/utils/agent_utils.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_akshare_data.py`:

```python
def test_build_instrument_context_a_share_contains_t1():
    from tradingagents.agents.utils.agent_utils import build_instrument_context
    context = build_instrument_context("600519.SS")
    assert "T+1" in context
    assert "A-share" in context or "CNY" in context


def test_build_instrument_context_hk_contains_hkd():
    from tradingagents.agents.utils.agent_utils import build_instrument_context
    context = build_instrument_context("0700.HK")
    assert "HKD" in context or "Hong Kong" in context


def test_build_instrument_context_us_unchanged():
    from tradingagents.agents.utils.agent_utils import build_instrument_context
    context = build_instrument_context("AAPL")
    assert "AAPL" in context
    assert "T+1" not in context
```

- [ ] **Step 2: Run tests — expect fail**

```bash
python -m pytest tests/test_akshare_data.py::test_build_instrument_context_a_share_contains_t1 -v
```

Expected: FAIL — current function has no CN branch

- [ ] **Step 3: Replace `build_instrument_context` in `agent_utils.py`**

Find the function at line 39 and replace it entirely:

```python
def build_instrument_context(ticker: str, asset_type: str = "stock") -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    from tradingagents.dataflows.akshare_data import detect_cn_market

    if asset_type == "crypto":
        return (
            f"The asset to analyze is `{ticker}`. "
            "Use this exact ticker in every tool call, report, and recommendation, "
            "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`). "
            "Treat it as a crypto asset rather than a company, and do not assume company fundamentals are available."
        )

    market = detect_cn_market(ticker)

    if market == "a_share":
        market_hint = (
            " This is a Chinese A-share stock listed on the Shanghai (suffix .SS) or "
            "Shenzhen (suffix .SZ) Stock Exchange. "
            "Key market rules: T+1 settlement (shares bought today cannot be sold until the next trading day); "
            "daily price limit of ±10% (±5% for ST-prefixed stocks); "
            "currency is CNY (Chinese Yuan). "
            "Financial statements are reported in CNY. "
            "Use AkShare or yfinance data tools with the full ticker including exchange suffix."
        )
    elif market == "hk":
        market_hint = (
            " This is a Hong Kong-listed stock on the Hong Kong Stock Exchange (HKEX). "
            "Key market rules: T+2 settlement; no daily price limit; "
            "currency is HKD (Hong Kong Dollar). "
            "Financial statements may be reported in HKD or USD. "
            "Southbound flow (南向资金) from mainland investors is an important demand signal. "
            "Use yfinance data tools with the full ticker including the .HK suffix."
        )
    else:
        market_hint = ""

    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `.SS`, `.SZ`, `-USD`)."
        + market_hint
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_akshare_data.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Confirm crypto test still passes**

```bash
python -m pytest tests/test_crypto_asset_mode.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/utils/agent_utils.py tests/test_akshare_data.py
git commit -m "feat(agents): add CN/HK market rules to build_instrument_context"
```

---

## Task 6: Update `sentiment_analyst.py` — CN/HK branch

**Files:**
- Modify: `tradingagents/agents/analysts/sentiment_analyst.py`

- [ ] **Step 1: Add imports at the top of `sentiment_analyst.py`**

After the existing imports, add:

```python
from tradingagents.dataflows.akshare_data import detect_cn_market, fetch_eastmoney_news_for_sentiment
```

- [ ] **Step 2: Replace `sentiment_analyst_node` inside `create_sentiment_analyst`**

Replace the existing `sentiment_analyst_node` function body (keeping the function signature) with:

```python
def sentiment_analyst_node(state):
    ticker = state["company_of_interest"]
    end_date = state["trade_date"]
    start_date = _seven_days_back(end_date)
    instrument_context = build_instrument_context(ticker)

    market = detect_cn_market(ticker)

    if market in ("a_share", "hk"):
        news_block = get_news.func(ticker, start_date, end_date)
        em_block = fetch_eastmoney_news_for_sentiment(ticker, limit=30)
        system_message = _build_cn_system_message(
            ticker=ticker,
            market=market,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            em_block=em_block,
        )
    else:
        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
        reddit_block = fetch_reddit_posts(ticker)
        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful AI assistant, collaborating with other assistants."
                " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                "\n{system_message}\n"
                "For your reference, the current date is {current_date}. {instrument_context}",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    prompt = prompt.partial(system_message=system_message)
    prompt = prompt.partial(current_date=end_date)
    prompt = prompt.partial(instrument_context=instrument_context)

    chain = prompt | llm
    result = chain.invoke(state["messages"])

    return {
        "messages": [result],
        "sentiment_report": result.content,
    }
```

- [ ] **Step 3: Add `_build_cn_system_message` function before `create_sentiment_analyst`**

```python
def _build_cn_system_message(
    *,
    ticker: str,
    market: str,
    start_date: str,
    end_date: str,
    news_block: str,
    em_block: str,
) -> str:
    """Assemble the sentiment-analyst system message for CN/HK markets."""
    market_label = "A-share (沪深两市)" if market == "a_share" else "Hong Kong (港交所)"
    market_notes = (
        """
**A-share Market Characteristics to consider:**
- T+1 settlement: shares bought today cannot be sold until tomorrow
- Daily price limit: ±10% (±5% for ST stocks) — extreme moves are capped
- Retail-dominated: ~70% of trading volume from individual investors
- Policy sensitivity: PBOC, CSRC, and government announcements have outsized impact
- Northbound flow (北向资金): foreign institutional buying/selling is a key signal
- Sector rotation driven by policy themes (e.g. tech self-sufficiency, green energy, consumption)
"""
        if market == "a_share"
        else """
**Hong Kong Market Characteristics to consider:**
- T+2 settlement, no daily price limit
- Dual influence: Chinese macro + global (USD, Fed) + local HK conditions
- Southbound flow (南向资金): mainland Chinese investor buying is a key demand driver
- H/A share premium: same company may trade at a discount vs A-share counterpart
- Hang Seng Index composition and sector weights affect institutional flows
"""
    )

    return f"""You are a financial market sentiment analyst covering {market_label}. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on two complementary data sources pre-collected for you.

{market_notes}

## Data Sources (pre-fetched, in this prompt)

### Yahoo Finance News — past 7 days
Institutional and international media framing. Fact-driven signal.

<start_of_yahoo_news>
{news_block}
<end_of_yahoo_news>

### Eastmoney (东方财富) News — most recent articles
Chinese financial media. Primary retail and institutional CN sentiment signal.
News titles may be in Chinese — read them as-is and incorporate their content into your analysis.

<start_of_eastmoney_news>
{em_block}
<end_of_eastmoney_news>

## How to analyze this data

1. **Cross-source convergence/divergence**: Do Yahoo Finance and Eastmoney tell the same story? If they diverge, that gap is itself a signal.
2. **Policy and regulatory themes**: For A-share especially, identify any government or regulator angle in the news.
3. **Catalysts and risks**: Surface upcoming earnings, product launches, regulatory risks, macro events.
4. **Data quality caveat**: If either source returned a `<no data>` placeholder, note this explicitly in your confidence assessment.
5. **Past sentiment is not predictive**: Frame conclusions as signals to weigh alongside fundamentals and technicals.

## Output

Produce a sentiment report covering:
1. **Overall sentiment direction** — Bullish / Bearish / Neutral / Mixed — with confidence note.
2. **Source-by-source breakdown** with specific evidence.
3. **Key narratives and divergences** across sources.
4. **Catalysts and risks** surfaced by the data.
5. **Markdown table** summarizing key sentiment signals, direction, source, and evidence.

{get_language_instruction()}"""
```

- [ ] **Step 4: Run structured agent tests to confirm no regressions**

```bash
python -m pytest tests/test_structured_agents.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/analysts/sentiment_analyst.py
git commit -m "feat(sentiment): add CN/HK branch using Eastmoney news instead of Reddit/StockTwits"
```

---

## Task 7: Polish + install AkShare + smoke test

**Files:**
- Modify: `cli/utils.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update ticker examples in `cli/utils.py`**

Find the line containing `TICKER_INPUT_EXAMPLES` and replace it:

```python
TICKER_INPUT_EXAMPLES = "Examples: SPY, CNC.TO, 7203.T, 0700.HK, 600519.SS, 000001.SZ, 9988.HK"
```

- [ ] **Step 2: Add akshare to `pyproject.toml` dependencies**

In the `dependencies` list, add:

```toml
    "akshare>=1.9.0",
```

- [ ] **Step 3: Install akshare**

```bash
pip install akshare>=1.9.0
```

- [ ] **Step 4: Run ticker-helper smoke test**

```bash
python -c "
from tradingagents.dataflows.akshare_data import get_cn_stock_data, detect_cn_market
print('detect_cn_market(600519.SS):', detect_cn_market('600519.SS'))
print('get_cn_stock_data (2024-01-01 to 2024-01-05):')
print(get_cn_stock_data('600519.SS', '2024-01-01', '2024-01-05')[:300])
"
```

Expected: market = "a_share"; CSV header + 3-4 rows of OHLCV data

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_checkpoint_resume.py -x
```

Expected: all tests PASS (checkpoint test excluded as it requires specific env)

- [ ] **Step 6: Commit**

```bash
git add cli/utils.py pyproject.toml
git commit -m "chore: add akshare>=1.9.0 dependency and update ticker examples for CN/HK"
```
