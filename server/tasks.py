# server/tasks.py
import logging
import os
from datetime import datetime

from server.celery_app import celery_app
from server.database import SessionLocal
from server.models import Analysis

logger = logging.getLogger(__name__)

_PROVIDER_ENV = {
    "qwen":       "DASHSCOPE_API_KEY",
    "qwen-cn":    "DASHSCOPE_CN_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "glm":        "ZHIPU_API_KEY",
    "glm-cn":     "ZHIPU_CN_API_KEY",
}

# Analyst report field → display label
_ANALYST_FIELDS = {
    "fundamentals_report": "基本面分析师",
    "sentiment_report":    "情绪分析师",
    "news_report":         "新闻分析师",
    "market_report":       "技术分析师",
}


def _update_progress(db, record: Analysis, stage: str = None, detail: str = None):
    """Write stage and/or detail to DB and commit."""
    changed = False
    if stage and record.stage != stage:
        record.stage = stage
        changed = True
    if detail is not None and record.stage_detail != detail:
        record.stage_detail = detail
        changed = True
    if changed:
        db.commit()


def _detect_progress(state: dict, record: Analysis):
    """Return (stage, detail) based on which state fields are populated.

    LangGraph's default stream_mode='values' yields the FULL state after each
    node — so we infer which node just ran by checking which new fields appeared.

    Transition logic (matches the actual graph execution order):
      All analyst reports set        → analysts → debate (when investment_plan appears)
      investment_plan set            → Research Manager done → move to "debate"
      trader_investment_plan set     → Trader done → move to "risk"
      final_trade_decision set       → Portfolio Manager done → move to "decision"
    """
    # Stage forward transitions (never go backwards)
    stage_order = ["analysts", "debate", "risk", "decision", "complete"]
    current_idx = stage_order.index(record.stage) if record.stage in stage_order else 0

    new_stage = record.stage
    if state.get("final_trade_decision") and current_idx < 4:
        new_stage = "decision"
    elif state.get("trader_investment_plan") and current_idx < 3:
        new_stage = "risk"
    elif state.get("investment_plan") and current_idx < 2:
        new_stage = "debate"

    # Build a human-readable detail string
    if new_stage == "decision":
        detail = "组合经理正在生成最终决策…"
    elif new_stage == "risk":
        detail = "风险评估团队讨论中…"
    elif new_stage == "debate":
        detail = "多空辩论进行中…"
    else:
        # Still in analysts stage — show per-analyst progress
        done = [lbl for fld, lbl in _ANALYST_FIELDS.items() if state.get(fld)]
        total = len([f for f in record.analysts
                     if f + "_report" in _ANALYST_FIELDS or
                     ("market" in f and "market_report" in _ANALYST_FIELDS)])
        if done:
            detail = f"分析师进度 {len(done)}/4：已完成 {', '.join(done)}"
        else:
            detail = "分析师团队数据采集中…"

    return new_stage, detail


def _apply_llm_config(config: dict, llm_config: dict) -> dict:
    if not llm_config:
        return config
    provider = llm_config.get("provider")
    if provider:
        config["llm_provider"] = provider
    if llm_config.get("deep_model"):
        config["deep_think_llm"] = llm_config["deep_model"]
    if llm_config.get("quick_model"):
        config["quick_think_llm"] = llm_config["quick_model"]
    if llm_config.get("backend_url"):
        config["backend_url"] = llm_config["backend_url"]
    api_key = llm_config.get("api_key")
    if api_key and provider:
        env_var = _PROVIDER_ENV.get(provider)
        if env_var:
            os.environ[env_var] = api_key
    return config


@celery_app.task(bind=True, name="server.tasks.run_analysis")
def run_analysis(self, analysis_id: str):
    """Run TradingAgentsGraph and write progress to Analysis.stage + stage_detail."""
    # Bypass system and env-var proxies so AkShare/yfinance can reach data sources directly.
    # NO_PROXY=* tells requests/urllib to skip ALL proxy settings (including macOS system proxy).
    for proxy_var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                      "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"):
        os.environ.pop(proxy_var, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    db = SessionLocal()
    try:
        record = db.get(Analysis, analysis_id)
        if not record:
            logger.error("run_analysis: analysis %s not found", analysis_id)
            return

        _update_progress(db, record, stage="analysts", detail="分析师团队数据采集中…")

        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config["output_language"] = "Chinese"
        config["max_debate_rounds"] = record.depth
        config["max_risk_discuss_rounds"] = record.depth
        config["debug"] = True
        config["checkpoint_enabled"] = False
        # Disable Futu on server unless explicitly enabled via env var
        if not os.getenv("FUTU_ENABLED", "").lower() in ("1", "true", "yes"):
            config["futu_enabled"] = False
        config = _apply_llm_config(config, record.llm_config or {})

        # Mark as running after config is ready
        record.status = "running"
        db.commit()

        # Set up combined usage tracker — routes events to quick/deep by model name
        from server.usage import CombinedUsageTracker
        usage_tracker = CombinedUsageTracker(
            quick_model=config["quick_think_llm"],
            deep_model=config["deep_think_llm"],
        )

        ta = TradingAgentsGraph(
            debug=True,
            config=config,
            callbacks=[usage_tracker],
        )
        init_state = ta.propagator.create_initial_state(
            record.ticker, record.trade_date, asset_type="stock", past_context=""
        )
        args = ta.propagator.get_graph_args()

        # Fields to save incrementally (as each analyst/node completes)
        _PARTIAL_FIELDS = [
            "market_report", "sentiment_report",
            "news_report", "fundamentals_report",
            "investment_plan", "trader_investment_plan",
        ]

        final_state: dict = {}
        result_cache: dict = {}

        for chunk in ta.graph.stream(init_state, **args):
            final_state.update(chunk)

            # Save any newly-appeared partial results immediately
            new_fields = {
                f: final_state[f]
                for f in _PARTIAL_FIELDS
                if final_state.get(f) and f not in result_cache
            }
            if new_fields:
                result_cache.update(new_fields)
                record.result = dict(result_cache)
                db.commit()

            # Update stage + detail
            new_stage, detail = _detect_progress(final_state, record)
            _update_progress(db, record, stage=new_stage, detail=detail)

        raw_decision = _strip_tool_call_prefix(final_state.get("final_trade_decision", ""))
        decision_str = ta.process_signal(raw_decision)
        decision = _extract_decision_label(decision_str)

        record.status = "complete"
        record.stage = "complete"
        record.stage_detail = "分析完成"
        record.decision = decision
        record.result = {
            "market_report":          final_state.get("market_report"),
            "sentiment_report":       final_state.get("sentiment_report"),
            "news_report":            final_state.get("news_report"),
            "fundamentals_report":    final_state.get("fundamentals_report"),
            "investment_plan":        final_state.get("investment_plan"),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
            "final_trade_decision":   raw_decision,
        }
        record.usage = usage_tracker.collect()
        record.completed_at = datetime.utcnow()
        record.seen = False
        db.commit()

    except Exception as exc:
        logger.exception("run_analysis failed for %s", analysis_id)
        record = db.get(Analysis, analysis_id)
        if record:
            record.status = "failed"
            # Keep record.stage as-is (shows where analysis got to before failure)
            # Keep record.result as-is (preserves completed analyst reports)
            record.stage_detail = f"中途失败: {str(exc)[:150]}"
            record.error = str(exc)
            record.seen = False
            db.commit()
        raise
    finally:
        db.close()


def _extract_decision_label(decision_str: str) -> str:
    upper = (decision_str or "").upper()
    for label in ("BUY", "SELL", "HOLD"):
        if label in upper:
            return label
    return "HOLD"


def _strip_tool_call_prefix(text: str) -> str:
    """Remove leading JSON tool-call code blocks that models sometimes emit.

    Some LLMs output a ```json {"tool": "..."} ``` block before the actual
    analysis when they mistake the instrument context for a tool-call prompt.
    """
    import re
    if not text:
        return text
    # Strip one or more leading ```...``` blocks that contain "tool" key
    cleaned = re.sub(
        r'^\s*```[a-z]*\s*\{[^`]*?"tool"[^`]*?\}\s*```\s*',
        "",
        text,
        flags=re.DOTALL,
    )
    return cleaned.strip() or text.strip()
