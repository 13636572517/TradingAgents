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


# ── AI-based extraction ────────────────────────────────────────────────────────

_AI_PROMPT = """你是一名专业量化分析助手，负责从投研报告中精确提取交易参数。

## 报告内容
{report_text}

## 分析日收盘价（入场参考价）
{entry_price} 元

## 任务
仔细阅读报告，提取以下交易参数，以**纯JSON**格式返回（不要有任何其他文字）：

{{
  "stop_loss": <止损价格（元，浮点），无法确定返回null>,
  "stop_loss_basis": <止损依据："绝对价格"|"百分比换算"|"均线支撑"|"前低支撑"|"其他"|"未明确">,
  "target_price": <目标止盈价格（元，浮点），无法确定返回null>,
  "target_price_basis": <目标价依据："绝对价格"|"百分比换算"|"压力位"|"估值目标"|"其他"|"未明确">,
  "position_size": <建议仓位字符串，如"20-30%"，无法确定返回null>,
  "time_horizon": <持有周期字符串，如"1-3个月"，无法确定返回null>,
  "confidence": <整体提取置信度："high"|"medium"|"low">,
  "extraction_note": <简短说明提取逻辑，100字以内>
}}

## 注意
- 若止损/目标以百分比表示（如"止损5%"），请结合入场价换算为绝对价格
- 仅提取报告中有明确依据的值，无依据时返回null
- 返回纯JSON，不要Markdown代码块，不要其他文字"""


def ai_extract_strategy_fields(
    report_text: str,
    entry_price: Optional[float],
    settings,                   # AppSettings ORM row
) -> dict:
    """
    Use quick LLM to extract structured strategy fields from report text.
    Returns a dict with keys: stop_loss, stop_loss_basis, target_price,
    target_price_basis, position_size, time_horizon, confidence, extraction_note.
    Raises on LLM or parse failure so caller can fall back to regex.
    """
    import json, os
    from tradingagents.llm_clients.factory import create_llm_client

    # Set API key env var
    _PROVIDER_ENV = {
        "qwen":       "DASHSCOPE_API_KEY",
        "qwen-cn":    "DASHSCOPE_CN_API_KEY",
        "openai":     "OPENAI_API_KEY",
        "anthropic":  "ANTHROPIC_API_KEY",
        "deepseek":   "DEEPSEEK_API_KEY",
        "glm":        "ZHIPU_API_KEY",
        "glm-cn":     "ZHIPU_CN_API_KEY",
    }
    provider = (settings.provider or "qwen-cn").lower()
    if settings.api_key:
        env_var = _PROVIDER_ENV.get(provider)
        if env_var:
            os.environ[env_var] = settings.api_key

    client = create_llm_client(
        provider=provider,
        model=settings.quick_model or "qwen3.6-flash",
        base_url=settings.backend_url or None,
    )
    llm = client.get_llm()

    price_str = f"{entry_price:.3f}" if entry_price else "未知"
    prompt = _AI_PROMPT.format(
        report_text=report_text[:6000],   # keep prompt within ~8K tokens
        entry_price=price_str,
    )

    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)

    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    parsed = json.loads(raw)

    # Normalise types
    def _float_or_none(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "stop_loss":          _float_or_none(parsed.get("stop_loss")),
        "stop_loss_basis":    parsed.get("stop_loss_basis"),
        "target_price":       _float_or_none(parsed.get("target_price")),
        "target_price_basis": parsed.get("target_price_basis"),
        "position_size":      parsed.get("position_size"),
        "time_horizon":       parsed.get("time_horizon"),
        "confidence":         parsed.get("confidence"),
        "extraction_note":    parsed.get("extraction_note"),
    }


# ── Main entry: build a strategy record dict from an Analysis ORM row ──────────

def build_strategy_from_analysis(record, settings=None) -> Optional[dict]:
    """
    Given an Analysis ORM object, extract strategy fields and fetch entry price.
    - Stage 1 (fast): regex extraction
    - Stage 2 (AI, optional): if settings provided, refine with LLM

    Returns a dict suitable for creating/updating AnalysisStrategy, or None on failure.
    """
    result = record.result or {}
    # Combine trader_investment_plan + final_trade_decision for richer context
    trader_plan = result.get("trader_investment_plan", "") or ""
    final_dec   = result.get("final_trade_decision", "") or ""
    combined_text = "\n\n".join(filter(None, [final_dec, trader_plan]))
    if not combined_text:
        return None

    # Stage 1: regex (fast, always)
    regex_fields = extract_strategy_fields(combined_text)
    entry_price  = get_stock_price_at_date(record.ticker, record.trade_date)

    base = {
        "analysis_id":     record.id,
        "ticker":          record.ticker,
        "ticker_name":     getattr(record, "ticker_name", None),
        "trade_date":      record.trade_date,
        "direction":       record.decision,
        "entry_price":     entry_price,
        "stop_loss":       regex_fields.get("stop_loss"),
        "target_price":    regex_fields.get("target_price"),
        "position_size":   regex_fields.get("position_size"),
        "time_horizon":    regex_fields.get("time_horizon"),
        "status":          "active",
        "extraction_method": "regex",
        "confidence":      None,
        "stop_loss_basis":    None,
        "target_price_basis": None,
        "extraction_note":    None,
    }

    # Stage 2: AI refinement (if settings available)
    if settings:
        try:
            ai_fields = ai_extract_strategy_fields(combined_text, entry_price, settings)
            base.update({
                "stop_loss":          ai_fields.get("stop_loss")       if ai_fields.get("stop_loss")       is not None else base["stop_loss"],
                "target_price":       ai_fields.get("target_price")    if ai_fields.get("target_price")    is not None else base["target_price"],
                "position_size":      ai_fields.get("position_size")   or base["position_size"],
                "time_horizon":       ai_fields.get("time_horizon")    or base["time_horizon"],
                "extraction_method":  "ai",
                "confidence":         ai_fields.get("confidence"),
                "stop_loss_basis":    ai_fields.get("stop_loss_basis"),
                "target_price_basis": ai_fields.get("target_price_basis"),
                "extraction_note":    ai_fields.get("extraction_note"),
            })
        except Exception as e:
            logger.warning("AI extraction failed for %s, using regex fallback: %s", record.ticker, e)

    return base
