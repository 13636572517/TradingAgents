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
        ak_code = _yf_to_short_code(symbol)
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
                    continue  # skip unparseable dates

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
                    if not (start_dt <= pub_dt <= curr_dt + relativedelta(days=1)):
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
    """Get A-share company key financial indicators from Tonghuashun via AkShare.

    Uses stock_financial_abstract_ths which is more stable than Eastmoney endpoints.
    Returns annual historical data: revenue, net profit, EPS, ROE, margins, debt ratios.
    """
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")
    try:
        short_code = _yf_to_short_code(ticker)

        # Primary: Tonghuashun financial abstract — stable, comprehensive
        df = ak.stock_financial_abstract_ths(symbol=short_code, indicator="按年度")
        if df is None or df.empty:
            raise ValueError("Empty result from stock_financial_abstract_ths")

        # Keep last 5 years, replace False with "-"
        df = df.tail(5).copy()
        df = df.replace(False, "-")

        header = (
            f"# Key Financial Indicators for {ticker.upper()} (A-share, 近5年)\n"
            f"# Source: Tonghuashun (同花顺) | Currency: CNY\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.to_csv(index=False)

    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_fundamentals (THS) failed for %s: %s", ticker, e)
        # Fallback: try Eastmoney basic company info
        try:
            import akshare as ak
            short_code = _yf_to_short_code(ticker)
            info_df = ak.stock_individual_info_em(symbol=short_code)
            if info_df is not None and not info_df.empty:
                lines = []
                for _, row in info_df.iterrows():
                    if len(row) >= 2:
                        item, value = str(row.iloc[0]), str(row.iloc[1])
                        if item.lower() not in ("nan",) and value.lower() not in ("nan",):
                            lines.append(f"{item}: {value}")
                header = (
                    f"# Company Info for {ticker.upper()} (A-share)\n"
                    f"# Source: Eastmoney (东方财富)\n\n"
                )
                return header + "\n".join(lines)
        except Exception as e2:
            logger.warning("Fallback Eastmoney also failed for %s: %s", ticker, e2)
        raise AkShareError(f"All fundamentals sources failed for {ticker}") from e


def get_cn_balance_sheet(
    ticker: Annotated[str, "ticker symbol in Yahoo Finance format e.g. 600519.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share balance sheet (资产负债表) from Sina Finance via AkShare.

    Note: freq parameter is accepted for interface parity with yfinance counterparts but is ignored — AkShare returns a fixed multi-period table regardless.
    """
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
    """Get A-share cash flow statement (现金流量表) from Sina Finance via AkShare.

    Note: freq parameter is accepted for interface parity with yfinance counterparts but is ignored — AkShare returns a fixed multi-period table regardless.
    """
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
    """Get A-share income statement (利润表) from Sina Finance via AkShare.

    Note: freq parameter is accepted for interface parity with yfinance counterparts but is ignored — AkShare returns a fixed multi-period table regardless.
    """
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
