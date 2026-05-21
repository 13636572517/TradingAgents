# TradingAgents A股/港股改造方案

> 本文档是完整的技术交接文件，供 AI 助手继续实施改造。
> 项目路径：`/Users/michael/tradingagents/TradingAgents`

---

## 一、项目背景

TradingAgents 是一个基于 LangGraph 的多 Agent LLM 金融投研框架（v0.2.5）。
核心流程：`数据获取 → 4个分析师报告 → 多空辩论 → 研究经理总结 → 交易员建议 → 风控讨论 → 组合经理最终决策`。

当前框架是为**美股**设计的，需要改造以支持 **A股（沪深两市）** 和 **港股（港交所）**。

---

## 二、关键架构说明

### 数据层 vendor 路由机制（重要）

```
tradingagents/dataflows/interface.py
```

所有数据工具调用统一走 `route_to_vendor(method, *args)` 函数：
- 根据配置的 `data_vendors` 或 `tool_vendors` 选择供应商（yfinance / alpha_vantage）
- 有 fallback 链：primary vendor 失败 → 尝试下一个 vendor
- 目前只有 `AlphaVantageRateLimitError` 会触发 fallback，其他错误直接抛出

**改造目标**：新增 `akshare` 作为第三方 vendor，A股 ticker（`.SS`/`.SZ` 后缀）自动路由到 AkShare。

### Ticker 格式约定

项目统一使用 Yahoo Finance 格式：
- A股上海：`600519.SS`（贵州茅台）
- A股深圳：`000001.SZ`（平安银行）
- 港股：`0700.HK`（腾讯）
- AkShare 内部格式：`sh600519`、`sz000001`、`00700`（需转换）

### 配置系统

`DEFAULT_CONFIG` 在 `tradingagents/default_config.py`，通过 `set_config()` / `get_config()` 全局存取。

当前 benchmark_map 已有 `.HK -> ^HSI`，但缺 `.SS` 和 `.SZ`。

### 情绪分析师

`tradingagents/agents/analysts/sentiment_analyst.py`

当前逻辑：预取 Yahoo Finance 新闻 + StockTwits + Reddit → 注入 prompt → 单次 LLM 调用。
问题：StockTwits 和 Reddit 对中文股票几乎没有数据，容易生成空占位符。

---

## 三、需要改动的文件清单

| 优先级 | 类型 | 文件路径 | 说明 |
|--------|------|----------|------|
| 高 | **新建** | `tradingagents/dataflows/akshare_data.py` | AkShare 数据层全部实现 |
| 高 | 修改 | `tradingagents/dataflows/interface.py` | 注册 akshare vendor；实现 ticker 后缀自动路由 |
| 高 | 修改 | `tradingagents/default_config.py` | 补 A股 benchmark；加 `market_vendor_overrides` |
| 高 | 修改 | `tradingagents/agents/analysts/sentiment_analyst.py` | A股/港股用东方财富替代 Reddit/StockTwits |
| 中 | 修改 | `tradingagents/agents/utils/agent_utils.py` | `build_instrument_context` 增加 A股/港股市场规则上下文 |
| 中 | 修改 | `tradingagents/graph/trading_graph.py` | `propagate()` 时写 `current_ticker` 到 config（供全局新闻路由使用）|
| 低 | 修改 | `cli/utils.py` | 更新 ticker 示例，加入 A股/港股 |
| 低 | 修改 | `pyproject.toml` | 添加 `akshare>=1.9.0` 依赖 |

---

## 四、详细实现说明

---

### 文件 1：`tradingagents/dataflows/akshare_data.py`（新建）

**完整内容如下，直接创建此文件：**

```python
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
        # Use SSE Composite (000001) and SZSE Component (399001) as market proxies
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
    """Fetch recent Eastmoney news for a CN/HK ticker for use in sentiment analysis.

    Returns a formatted plaintext block. Degrades gracefully — returns a
    placeholder string on failure so the sentiment analyst always sees something.
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

---

### 文件 2：`tradingagents/dataflows/interface.py`（完整替换）

**在现有文件基础上做如下改动：**

#### 2a. 顶部 import 区域，追加以下导入（加在现有 import 之后）：

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

#### 2b. 修改 `VENDOR_LIST`：

```python
VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "akshare",        # 新增
]
```

#### 2c. 在 `VENDOR_METHODS` 字典中，每个方法下新增 `akshare` 条目：

```python
VENDOR_METHODS = {
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "akshare": get_cn_stock_data,          # 新增
    },
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        # akshare 不注册此方法，自动 fallback 到 yfinance
    },
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "akshare": get_cn_fundamentals,        # 新增
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "akshare": get_cn_balance_sheet,       # 新增
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "akshare": get_cn_cashflow,            # 新增
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "akshare": get_cn_income_statement,    # 新增
    },
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "akshare": get_cn_news,                # 新增
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "akshare": get_cn_global_news,         # 新增
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        # akshare 不注册，fallback 到 yfinance（A股内部人交易公示有限）
    },
}
```

#### 2d. 将 `get_vendor` 函数替换为以下版本（支持 ticker 后缀自动路由）：

```python
def get_vendor(category: str, method: str = None, ticker_hint: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.

    Resolution order:
    1. market_vendor_overrides — ticker-suffix-based auto-detection (e.g. .SS → akshare)
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

#### 2e. 将 `route_to_vendor` 函数替换为以下版本（自动提取 ticker_hint，捕获 AkShareError）：

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
        # Date strings look like YYYY-MM-DD (length 10, hyphens at [4] and [7])
        is_date = (
            len(first_arg) == 10
            and first_arg[4:5] == "-"
            and first_arg[7:8] == "-"
        )
        if not is_date:
            ticker_hint = first_arg
        else:
            # Fallback: use current_ticker from config (set by trading_graph.propagate)
            ticker_hint = get_config().get("current_ticker")

    vendor_config = get_vendor(category, method, ticker_hint=ticker_hint)
    primary_vendors = [v.strip() for v in vendor_config.split(",")]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue  # This vendor doesn't implement this method — skip silently

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except (AlphaVantageRateLimitError, AkShareError):
            continue  # Rate limits and AkShare errors trigger fallback to next vendor

    raise RuntimeError(f"No available vendor for '{method}'")
```

---

### 文件 3：`tradingagents/default_config.py`（修改两处）

#### 3a. 在 `benchmark_map` 中补充 A股基准：

找到：
```python
"benchmark_map": {
    ".NS":  "^NSEI",
    ".BO":  "^BSESN",
    ".T":   "^N225",
    ".HK":  "^HSI",
    ".L":   "^FTSE",
    ".TO":  "^GSPTSE",
    ".AX":  "^AXJO",
    "":     "SPY",
},
```

替换为：
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

#### 3b. 在 `data_vendors` 块后面追加 `market_vendor_overrides`：

找到：
```python
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
```

在其后追加：
```python
    # Market-based vendor overrides (takes precedence over data_vendors and tool_vendors)
    # Tickers whose suffix matches a key here will automatically use the mapped vendor.
    # A-share tickers (.SS / .SZ) use AkShare for better CN data quality.
    # HK tickers (.HK) continue using yfinance, which has good HK coverage.
    "market_vendor_overrides": {
        ".SS": "akshare",
        ".SZ": "akshare",
    },
```

---

### 文件 4：`tradingagents/agents/analysts/sentiment_analyst.py`（修改）

在文件顶部 import 区域追加：
```python
from tradingagents.dataflows.akshare_data import detect_cn_market, fetch_eastmoney_news_for_sentiment
```

将 `create_sentiment_analyst` 函数中的 `sentiment_analyst_node` 替换为：

```python
def sentiment_analyst_node(state):
    ticker = state["company_of_interest"]
    end_date = state["trade_date"]
    start_date = _seven_days_back(end_date)
    instrument_context = build_instrument_context(ticker)

    market = detect_cn_market(ticker)

    if market in ("a_share", "hk"):
        # CN/HK market: use Eastmoney news; Reddit/StockTwits have no CN coverage
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
        # US/International market: use original Reddit + StockTwits approach
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

在文件末尾（`create_social_media_analyst` 之前）追加新函数 `_build_cn_system_message`：

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

---

### 文件 5：`tradingagents/agents/utils/agent_utils.py`（修改一个函数）

将 `build_instrument_context` 函数替换为：

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

---

### 文件 6：`tradingagents/graph/trading_graph.py`（修改一行）

找到 `propagate` 方法，在 `self.ticker = company_name` 之后添加一行：

```python
def propagate(self, company_name, trade_date, asset_type: str = "stock"):
    self.ticker = company_name
    set_config({"current_ticker": company_name})   # ← 新增这一行
    # ... 其余代码不变
```

---

### 文件 7：`cli/utils.py`（修改一行）

找到：
```python
TICKER_INPUT_EXAMPLES = "Examples: SPY, CNC.TO, 7203.T, 0700.HK"
```

替换为：
```python
TICKER_INPUT_EXAMPLES = "Examples: SPY, CNC.TO, 7203.T, 0700.HK, 600519.SS, 000001.SZ, 9988.HK"
```

---

### 文件 8：`pyproject.toml`（修改一行）

在 `dependencies` 列表中追加：
```toml
    "akshare>=1.9.0",
```

---

## 五、实施顺序建议

1. 先安装 akshare：`pip install akshare`
2. 按顺序创建/修改文件：akshare_data.py → interface.py → default_config.py → trading_graph.py → sentiment_analyst.py → agent_utils.py → cli/utils.py → pyproject.toml
3. 快速验证数据层：
   ```python
   from tradingagents.dataflows.akshare_data import get_cn_stock_data, get_cn_news
   print(get_cn_stock_data("600519.SS", "2024-01-01", "2024-01-31"))
   print(get_cn_news("600519.SS", "2024-01-01", "2024-01-31"))
   ```
4. 运行完整分析验证：
   ```python
   from tradingagents.graph.trading_graph import TradingAgentsGraph
   from tradingagents.default_config import DEFAULT_CONFIG
   config = DEFAULT_CONFIG.copy()
   config["output_language"] = "Chinese"
   ta = TradingAgentsGraph(debug=True, config=config)
   _, decision = ta.propagate("600519.SS", "2024-05-10")
   print(decision)
   ```

---

## 六、设计约束（不要违反）

- **美股逻辑零改动**：所有改动通过 vendor 路由隔离，无 `.SS`/`.SZ` 后缀的 ticker 走原有代码路径
- **AkShare 是可选依赖**：所有 AkShare 调用都在 `try/import` 块内，未安装时抛 `AkShareError`，fallback 到 yfinance
- **不改变工具函数签名**：`get_stock_data`、`get_news` 等 LangChain tool 的签名保持不变
- **HK 股沿用 yfinance**：港股（`.HK`）不加入 `market_vendor_overrides`，继续用 yfinance（覆盖良好）
- **情绪分析保持单次 LLM 调用架构**：CN 版本也是预取数据后注入 prompt，不引入额外工具调用
