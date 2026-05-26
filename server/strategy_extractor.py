# server/strategy_extractor.py
"""Extract structured strategy fields from LLM decision text and fetch price data."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ── Text extraction ────────────────────────────────────────────────────────────

def _first_float(patterns: list[str], text: str) -> Optional[float]:
    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _first_str(patterns: list[str], text: str) -> Optional[str]:
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def extract_strategy_fields(text: str) -> dict:
    """Parse stop_loss, target_price, position_size, time_horizon from decision text."""
    if not text:
        return {}

    stop_loss = _first_float([
        r'止损[价位线点参考]*\s*[：:]\s*([\d,.]+)',
        r'止损\s*[设定在价格区间]*\s*([\d,.]+)',
        r'[严格]*\s*止损[至到]\s*([\d,.]+)',
        r'跌[破穿至]\s*([\d,.]+)\s*[元止损]',
    ], text)

    target_price = _first_float([
        r'目标[价位价格区间]*\s*[：:]\s*([\d,.]+)',
        r'止盈[价位线点]*\s*[：:]\s*([\d,.]+)',
        r'目标\s*价格\s*[：:]\s*([\d,.]+)',
        r'上涨[至到]\s*([\d,.]+)',
        r'涨[至到]\s*([\d,.]+)\s*元',
    ], text)

    position_size = _first_str([
        r'[建议]*仓位\s*[：:]\s*(\d+[\-~至到]\d+)\s*[%％]',
        r'[建议]*仓位\s*[：:]\s*(\d+)\s*[%％]',
        r'持仓\s*比例\s*[：:]\s*(\d+[\-~至到]\d+)\s*[%％]',
        r'持仓\s*比例\s*[：:]\s*(\d+)\s*[%％]',
        r'配置\s*(\d+[\-~至到]\d+)\s*[%％]',
    ], text)
    if position_size:
        position_size = position_size + "%"

    time_horizon = _first_str([
        r'[投持时操]\w{0,4}周期\s*[：:]\s*([^\n，,。；;]{2,20})',
        r'持有\s*期限?\s*[：:]\s*([^\n，,。；;]{2,20})',
        r'(\d+[\-~至到]\d+\s*[个]?[天周月年])',
        r'(\d+\s*[个]?[天周月年][以内左右以上以下]+)',
        r'(短期|中期|长期)',
    ], text)

    return {
        "stop_loss": stop_loss,
        "target_price": target_price,
        "position_size": position_size,
        "time_horizon": time_horizon,
    }


# ── Price helpers (akshare) ────────────────────────────────────────────────────

def _is_etf(ticker: str) -> bool:
    base = ticker.upper().rsplit(".", 1)[0]
    if not base.isdigit() or len(base) != 6:
        return False
    p2, p3 = base[:2], base[:3]
    return p3 == "159" or p2 in ("51", "52") or p3 == "588"


def _short_code(ticker: str) -> str:
    return ticker.upper().rsplit(".", 1)[0]


def get_stock_price_at_date(ticker: str, date_str: str) -> Optional[float]:
    """Return closing price on or before date_str (YYYY-MM-DD)."""
    try:
        import akshare as ak
        code = _short_code(ticker)
        d_nodash = date_str.replace("-", "")
        # Look back up to 10 days to skip holidays
        start = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y%m%d")
        if _is_etf(ticker):
            df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
            if df is None or df.empty:
                return None
            df["_d"] = df["日期"].astype(str).str.replace("-", "")
            df = df[df["_d"] <= d_nodash].tail(1)
        else:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=d_nodash, adjust="qfq",
            )
            if df is None or df.empty:
                return None
            df = df.tail(1)
        if df.empty:
            return None
        return float(df.iloc[-1]["收盘"])
    except Exception as e:
        logger.warning("get_stock_price_at_date(%s, %s): %s", ticker, date_str, e)
        return None


def get_stock_current_price(ticker: str) -> Optional[float]:
    """Return the latest available closing price."""
    try:
        import akshare as ak
        code = _short_code(ticker)
        today = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
        if _is_etf(ticker):
            df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="qfq")
        else:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=today, adjust="qfq",
            )
        if df is None or df.empty:
            return None
        return float(df.iloc[-1]["收盘"])
    except Exception as e:
        logger.warning("get_stock_current_price(%s): %s", ticker, e)
        return None


# ── Main entry: build a strategy record dict from an Analysis ORM row ──────────

def build_strategy_from_analysis(record) -> Optional[dict]:
    """
    Given an Analysis ORM object, extract strategy fields and fetch entry price.
    Returns a dict suitable for creating/updating AnalysisStrategy, or None on failure.
    """
    result = record.result or {}
    text = result.get("final_trade_decision", "") or ""
    if not text:
        return None

    fields = extract_strategy_fields(text)
    entry_price = get_stock_price_at_date(record.ticker, record.trade_date)

    return {
        "analysis_id": record.id,
        "ticker": record.ticker,
        "ticker_name": record.ticker_name,
        "trade_date": record.trade_date,
        "direction": record.decision,
        "entry_price": entry_price,
        "stop_loss": fields.get("stop_loss"),
        "target_price": fields.get("target_price"),
        "position_size": fields.get("position_size"),
        "time_horizon": fields.get("time_horizon"),
        "status": "active",
    }
