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
from .stockstats_utils import fix_cn_exchange

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
    """600519.SS → sh600519,  000001.SZ → sz000001 | 513180.SZ → sh513180 (auto-corrected)"""
    parts = fix_cn_exchange(ticker).upper().rsplit(".", 1)
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


def is_etf(ticker: str) -> bool:
    """Return True if ticker looks like an A-share ETF.

    Checks code range only — exchange suffix (.SS / .SZ) is intentionally
    ignored because some ETFs are mis-labelled (e.g. 517180.SZ should be .SS).

    Shenzhen ETF codes: 159xxx
    Shanghai ETF codes: 51xxxx, 52xxxx, 588xxx
    """
    upper = ticker.upper().strip()
    base = upper.rsplit(".", 1)[0]
    if not base.isdigit() or len(base) != 6:
        return False
    p2 = base[:2]
    p3 = base[:3]
    return p3 == "159" or p2 in ("51", "52") or p3 == "588"


def get_cn_etf_fundamentals(
    ticker: Annotated[str, "ETF ticker in Yahoo Finance format, e.g. 159992.SZ"],
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Return an ETF-specific analysis report: price performance, top holdings, NAV history."""
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")

    code = _yf_to_short_code(ticker)
    today = curr_date or datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# ETF Analysis Report: {ticker}",
        f"# Date: {today}",
        f"# Note: ETFs hold a basket of securities. Traditional financial statements",
        f"#       (balance sheet / income statement / cashflow) do not apply.",
        "",
    ]

    # ── 1. Recent price & volume ─────────────────────────────────────────────────
    try:
        price_df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
        if price_df is not None and not price_df.empty:
            recent = price_df.tail(30).copy()
            recent = recent.rename(columns={
                "日期": "Date", "开盘": "Open", "收盘": "Close",
                "最高": "High", "最低": "Low", "成交量": "Volume",
                "成交额": "Amount(CNY)", "涨跌幅": "Change(%)", "换手率": "Turnover(%)",
            })
            last = price_df.iloc[-1]
            close_price = last.get("收盘", "N/A")
            chg = last.get("涨跌幅", "N/A")
            lines += [
                "## Recent Price Performance (last 30 trading days)",
                f"Latest close: {close_price} CNY  |  Change: {chg}%",
                "",
                recent[["Date","Open","Close","High","Low","Volume","Change(%)"]].to_csv(index=False),
            ]
    except Exception as e:
        lines.append(f"## Price data unavailable: {e}\n")

    # ── 2. Top holdings (latest quarterly disclosure) ────────────────────────────
    try:
        year = today[:4]
        holds = ak.fund_portfolio_hold_em(symbol=code, date=year)
        if holds is not None and not holds.empty:
            top10 = holds.head(10)
            lines += [
                "## Top Holdings (Latest Quarter)",
                top10.to_csv(index=False),
            ]
    except Exception as e:
        lines.append(f"## Holdings data unavailable: {e}\n")

    # ── 3. NAV history (last 10 rows) ────────────────────────────────────────────
    try:
        nav_df = ak.fund_etf_fund_info_em(fund=code)
        if nav_df is not None and not nav_df.empty:
            recent_nav = nav_df.tail(10)
            lines += [
                "## Recent NAV History",
                recent_nav.to_csv(index=False),
            ]
    except Exception as e:
        lines.append(f"## NAV data unavailable: {e}\n")

    return "\n".join(lines)


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
        if is_etf(symbol):
            df = ak.fund_etf_hist_em(symbol=ak_code, period="daily", adjust="qfq")
            if df is not None and not df.empty:
                df["日期"] = df["日期"].astype(str)
                df = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)]
        else:
            df = ak.stock_zh_a_hist(
                symbol=ak_code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
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
            f"# Currency: CNY | Adjusted: forward-split-adjusted (前复权, current price preserved)\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + df.to_csv(index=False)
    except AkShareError:
        raise
    except Exception as e:
        logger.warning("AkShare get_cn_stock_data failed for %s: %s", symbol, e)
        raise AkShareError(f"AkShare data fetch failed for {symbol}: {e}") from e


# ── A-share news ───────────────────────────────────────────────────────────────

def _parse_news_rows(
    df,
    start_dt,
    end_dt,
    limit: int = 20,
    source_label: str = "",
) -> tuple[str, int]:
    """Shared formatter for news DataFrames — returns (news_str, count)."""
    news_str = ""
    count = 0
    for _, row in df.iterrows():
        pub_time = str(row.get("发布时间", row.get("时间", "")))
        if pub_time:
            try:
                pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
                if not (start_dt <= pub_dt <= end_dt + relativedelta(days=1)):
                    continue
            except (ValueError, TypeError):
                continue
        title = row.get("新闻标题", row.get("标题", row.get("title", "No title")))
        source = row.get("文章来源", row.get("来源", source_label or "Unknown"))
        link = row.get("新闻链接", row.get("链接", ""))
        content = str(row.get("新闻内容", row.get("内容", "")))
        news_str += f"### {title} (来源: {source})\n"
        if content and len(content) > 10:
            news_str += content[:300] + ("…" if len(content) > 300 else "") + "\n"
        if link:
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1
        if count >= limit:
            break
    return news_str, count


def get_cn_news(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Get stock-specific news for an A-share ticker.

    Source priority:
    1. Eastmoney (东方财富) — ak.stock_news_em
    2. Cailian (财联社 CLS) — ak.stock_news_cu  [fallback]
    """
    try:
        import akshare as ak
    except ImportError:
        raise AkShareError("akshare is not installed")

    short_code = _yf_to_short_code(ticker)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # 1) Eastmoney
    try:
        news_df = ak.stock_news_em(symbol=short_code)
        if news_df is not None and not news_df.empty:
            news_str, count = _parse_news_rows(news_df, start_dt, end_dt, limit=20)
            if count > 0:
                return f"## {ticker} 新闻资讯 ({start_date} 至 {end_date}):\n\n{news_str}"
            logger.warning("get_cn_news: Eastmoney returned 0 in-range articles for %s", ticker)
    except Exception as e:
        logger.warning("get_cn_news: Eastmoney failed for %s: %s", ticker, e)

    # 2) Cailian (财联社)
    try:
        cls_df = ak.stock_news_cu(symbol=short_code)
        if cls_df is not None and not cls_df.empty:
            news_str, count = _parse_news_rows(cls_df, start_dt, end_dt, limit=20,
                                               source_label="财联社")
            if count > 0:
                logger.info("get_cn_news: serving %s news from 财联社", ticker)
                return f"## {ticker} 新闻资讯 ({start_date} 至 {end_date}):\n\n{news_str}"
    except Exception as e:
        logger.warning("get_cn_news: 财联社 failed for %s: %s", ticker, e)

    raise AkShareError(f"All CN news sources failed for {ticker}")


def get_cn_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Get Chinese macro/market news.

    Source priority:
    1. Eastmoney (东方财富) index news — ak.stock_news_em on 000001/399001
    2. Cailian Telegraph (财联社电报) — ak.news_cls_telegraph  [fallback]
    3. CCTV Finance (央视财经) — ak.news_cctv                  [fallback]
    """
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

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")

    # 1) Eastmoney index news (000001 沪指 / 399001 深成指)
    try:
        all_articles: list = []
        seen_titles: set = set()
        for sym in ["000001", "399001"]:
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
        if all_articles:
            news_str, count = _parse_news_rows(
                __import__("pandas").DataFrame(all_articles),
                start_dt, curr_dt, limit=limit,
            )
            if count > 0:
                return f"## 中国市场宏观新闻 ({start_date_str} 至 {curr_date}):\n\n{news_str}"
    except Exception as e:
        logger.warning("get_cn_global_news: Eastmoney index news failed: %s", e)

    # 2) Cailian Telegraph (财联社电报)
    try:
        cls_df = ak.news_cls_telegraph(symbol="全部")
        if cls_df is not None and not cls_df.empty:
            news_str, count = _parse_news_rows(
                cls_df, start_dt, curr_dt, limit=limit, source_label="财联社电报"
            )
            if count > 0:
                logger.info("get_cn_global_news: serving from 财联社电报")
                return f"## 中国市场宏观新闻 ({start_date_str} 至 {curr_date}):\n\n{news_str}"
    except Exception as e:
        logger.warning("get_cn_global_news: 财联社电报 failed: %s", e)

    # 3) CCTV Finance (央视财经)
    try:
        cctv_df = ak.news_cctv(date=curr_date.replace("-", ""))
        if cctv_df is not None and not cctv_df.empty:
            news_str, count = _parse_news_rows(
                cctv_df, start_dt, curr_dt, limit=limit, source_label="央视财经"
            )
            if count > 0:
                logger.info("get_cn_global_news: serving from 央视财经")
                return f"## 中国市场宏观新闻 ({start_date_str} 至 {curr_date}):\n\n{news_str}"
    except Exception as e:
        logger.warning("get_cn_global_news: 央视财经 failed: %s", e)

    raise AkShareError("All CN global news sources failed (Eastmoney / 财联社 / 央视)")


# ── A-share technical indicators (computed via stockstats on AkShare OHLCV) ───

def get_cn_indicators(
    symbol: Annotated[str, "ticker in Yahoo Finance format e.g. 600519.SS"],
    indicator: Annotated[str, "technical indicator name, e.g. close_50_sma, rsi, macd"],
    curr_date: Annotated[str, "current trading date YYYY-MM-DD"],
    look_back_days: Annotated[int, "number of calendar days to look back"] = 60,
) -> str:
    """Compute technical indicators for A-share stocks using AkShare OHLCV + stockstats.

    Fetches ~1 year of daily OHLCV from AkShare (前复权, qfq), then uses stockstats
    to compute the same indicators supported by the yfinance path (SMA, EMA, MACD,
    RSI, Bollinger Bands, ATR, etc.).
    """
    try:
        import akshare as ak
        import pandas as pd
        from stockstats import wrap
        from dateutil.relativedelta import relativedelta as rdelta
    except ImportError as e:
        raise AkShareError(f"Missing dependency: {e}")

    try:
        short_code = _yf_to_short_code(symbol)
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")

        # Use Sina Finance (stable, different endpoint from Eastmoney's rate-limited API)
        suffix = symbol.upper().rsplit(".", 1)[-1] if "." in symbol else "SS"
        sina_symbol = ("sh" if suffix == "SS" else "sz") + short_code

        df = ak.stock_zh_a_daily(symbol=sina_symbol, adjust="qfq")
        if df is None or df.empty:
            raise AkShareError(f"No OHLCV data for {symbol}")

        # stock_zh_a_daily already returns lowercase columns: date, open, high, low, close, volume
        # stockstats needs these lowercase columns
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            raise AkShareError(f"Missing OHLCV columns: {df.columns.tolist()}")

        # Parse date and filter to <= curr_date
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] <= pd.Timestamp(curr_dt)].copy()
        df = df.sort_values("date").reset_index(drop=True)
        df["Date"] = df["date"].dt.strftime("%Y-%m-%d")

        # Compute indicator via stockstats
        stock = wrap(df)
        stock[indicator]  # triggers calculation

        # Build result dict {date_str → value}
        result_dict = {}
        for _, row in stock.iterrows():
            date_str = row["Date"]
            val = row.get(indicator)
            result_dict[date_str] = "N/A" if pd.isna(val) else str(round(float(val), 4))

        # Generate the requested look_back_days window
        before = curr_dt - rdelta(days=look_back_days)
        lines = []
        d = curr_dt
        while d >= before:
            ds = d.strftime("%Y-%m-%d")
            lines.append(f"{ds}: {result_dict.get(ds, 'N/A: Not a trading day')}")
            d -= rdelta(days=1)

        return (
            f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
        )

    except AkShareError:
        raise
    except Exception as e:
        logger.warning("get_cn_indicators failed for %s %s: %s", symbol, indicator, e)
        raise AkShareError(f"AkShare indicator {indicator} failed for {symbol}: {e}") from e


# ── A-share fundamentals ───────────────────────────────────────────────────────

def get_cn_fundamentals(
    ticker: Annotated[str, "ticker symbol in Yahoo Finance format e.g. 600519.SS"],
    curr_date: Annotated[str, "current date (unused for AkShare)"] = None,
) -> str:
    """Get A-share company key financial indicators from Tonghuashun via AkShare.

    Uses stock_financial_abstract_ths which is more stable than Eastmoney endpoints.
    Returns annual historical data: revenue, net profit, EPS, ROE, margins, debt ratios.
    For ETFs, delegates to get_cn_etf_fundamentals.
    """
    if is_etf(ticker):
        return get_cn_etf_fundamentals(ticker, curr_date)
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
    if is_etf(ticker):
        return (
            f"# {ticker} is an ETF — balance sheets do not apply to ETFs.\n"
            f"# Call get_fundamentals() instead to get NAV, holdings and performance data.\n"
        )
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
    if is_etf(ticker):
        return (
            f"# {ticker} is an ETF — cash flow statements do not apply to ETFs.\n"
            f"# Call get_fundamentals() instead to get NAV, holdings and performance data.\n"
        )
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
    if is_etf(ticker):
        return (
            f"# {ticker} is an ETF — income statements do not apply to ETFs.\n"
            f"# Call get_fundamentals() instead to get NAV, holdings and performance data.\n"
        )
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
