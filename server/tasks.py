# server/tasks.py
import logging
import os
from datetime import datetime

from server.celery_app import celery_app
from server.database import SessionLocal
from server.models import Analysis, AnalysisStrategy

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

# stage key (from frontend TREE) → (analyst_key, report_field)
_ANALYST_STAGE_MAP = {
    "market":       ("market",       "market_report"),
    "social":       ("social",       "sentiment_report"),
    "news":         ("news",         "news_report"),
    "fundamentals": ("fundamentals", "fundamentals_report"),
}
_ALL_REPORT_FIELDS = ["market_report", "sentiment_report", "news_report", "fundamentals_report"]

# Frontend uses "sentiment" as the analyst key; the graph uses "social".
# This alias map lets us accept both.
_ANALYST_KEY_ALIAS: dict[str, str] = {"sentiment": "social"}


def _normalize_analysts(analysts: list) -> list:
    """Translate any legacy/frontend analyst key aliases to graph-internal keys."""
    return [_ANALYST_KEY_ALIAS.get(a, a) for a in (analysts or [])]


def _extract_strategy(db, record: Analysis) -> None:
    """Build / upsert an AnalysisStrategy record after an analysis completes."""
    try:
        import uuid as _uuid
        from server.strategy_extractor import build_strategy_from_analysis
        existing = db.query(AnalysisStrategy).filter_by(analysis_id=record.id).first()
        data = build_strategy_from_analysis(record)
        if not data:
            return
        if existing:
            for k, v in data.items():
                if k != "analysis_id":
                    setattr(existing, k, v)
        else:
            db.add(AnalysisStrategy(id=str(_uuid.uuid4()), **data))
        db.commit()
    except Exception as exc:
        logger.warning("_extract_strategy failed for %s: %s", record.id, exc)
        try:
            db.rollback()
        except Exception:
            pass


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
        from server.models import AppSettings as _AppSettings
        _app_cfg = db.get(_AppSettings, 1)
        _max_calls = (_app_cfg.max_api_calls if _app_cfg and _app_cfg.max_api_calls else 60)
        _input_cost = (_app_cfg.input_cost_per_million if _app_cfg else 0.0) or 0.0
        _output_cost = (_app_cfg.output_cost_per_million if _app_cfg else 0.0) or 0.0
        usage_tracker = CombinedUsageTracker(
            quick_model=config["quick_think_llm"],
            deep_model=config["deep_think_llm"],
            max_calls=_max_calls,
            input_cost_per_million=_input_cost,
            output_cost_per_million=_output_cost,
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

        from server.usage import APICallLimitError
        for chunk in ta.graph.stream(init_state, **args):
            if usage_tracker.total_calls > usage_tracker.max_calls:
                raise APICallLimitError(
                    f"API 调用次数已达上限 ({usage_tracker.max_calls} 次），分析已自动中止。"
                    f"如需继续，请人工确认后重新运行。"
                )
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
                
                # Update stage_detail to trigger SSE event on new report
                done = [lbl for fld, lbl in _ANALYST_FIELDS.items() if final_state.get(fld)]
                if done:
                    detail = f"分析师进度 {len(done)}/4：已完成 {', '.join(done)}"
                    _update_progress(db, record, detail=detail)

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
        _extract_strategy(db, record)

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


@celery_app.task(bind=True, name="server.tasks.rerun_stage")
def rerun_stage(self, analysis_id: str, stage: str):
    """Re-run a single stage of an existing analysis and merge results back.

    For analyst stages (market/social/news/fundamentals):
      - Runs only that analyst, pre-populating other reports from existing result.
      - Debate/risk/decision also re-run with new + existing reports.

    For decision stages (investment_plan/trader_investment_plan/final_trade_decision):
      - Runs the full pipeline (all analysts fresh).
    """
    for proxy_var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                      "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"):
        os.environ.pop(proxy_var, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    db = SessionLocal()
    try:
        record = db.get(Analysis, analysis_id)
        if not record:
            logger.error("rerun_stage: analysis %s not found", analysis_id)
            return

        existing = dict(record.result or {})
        is_analyst_stage = stage in _ANALYST_STAGE_MAP

        if is_analyst_stage:
            analyst_key, _ = _ANALYST_STAGE_MAP[stage]
            selected_analysts = [analyst_key]
            label = _ANALYST_FIELDS.get(_ANALYST_STAGE_MAP[stage][1], stage)
        else:
            selected_analysts = _normalize_analysts(
                record.analysts or ["market", "social", "news", "fundamentals"]
            )
            label = {"investment_plan": "投研总结", "trader_investment_plan": "交易建议",
                     "final_trade_decision": "最终决策"}.get(stage, stage)

        record.status = "running"
        record.stage = "debate" if not is_analyst_stage else "analysts"
        record.stage_detail = f"正在重新分析: {label}…"
        record.celery_task_id = self.request.id
        db.commit()

        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config["output_language"] = "Chinese"
        config["max_debate_rounds"] = record.depth
        config["max_risk_discuss_rounds"] = record.depth
        config["debug"] = True
        config["checkpoint_enabled"] = False
        if not os.getenv("FUTU_ENABLED", "").lower() in ("1", "true", "yes"):
            config["futu_enabled"] = False
        # Always use CURRENT settings for rerun so the user can switch models
        # before retrying a failed analysis.
        from server.models import AppSettings
        current_settings = db.get(AppSettings, 1)
        current_llm_config = {
            "provider":    current_settings.provider    if current_settings else None,
            "api_key":     current_settings.api_key     if current_settings else None,
            "deep_model":  current_settings.deep_model  if current_settings else None,
            "quick_model": current_settings.quick_model if current_settings else None,
            "backend_url": current_settings.backend_url if current_settings else None,
        } if current_settings else (record.llm_config or {})
        config = _apply_llm_config(config, current_llm_config)

        from server.usage import CombinedUsageTracker
        from server.models import AppSettings as _AppSettings
        _app_cfg = db.get(_AppSettings, 1)
        _max_calls = (_app_cfg.max_api_calls if _app_cfg and _app_cfg.max_api_calls else 60)
        _input_cost = (_app_cfg.input_cost_per_million if _app_cfg else 0.0) or 0.0
        _output_cost = (_app_cfg.output_cost_per_million if _app_cfg else 0.0) or 0.0
        usage_tracker = CombinedUsageTracker(
            quick_model=config["quick_think_llm"],
            deep_model=config["deep_think_llm"],
            max_calls=_max_calls,
            input_cost_per_million=_input_cost,
            output_cost_per_million=_output_cost,
        )

        ta = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            debug=True,
            config=config,
            callbacks=[usage_tracker],
            decision_only=(not is_analyst_stage),
        )
        init_state = ta.propagator.create_initial_state(
            record.ticker, record.trade_date, asset_type="stock", past_context=""
        )

        report_key: str | None = None
        if is_analyst_stage:
            _, report_key = _ANALYST_STAGE_MAP[stage]
            # Pre-populate all other analyst reports so only the target one is re-run
            for fld in _ALL_REPORT_FIELDS:
                if fld != report_key and existing.get(fld):
                    init_state[fld] = existing[fld]
        else:
            # Decision-only rerun: inject all existing analyst reports so the
            # debate/trader/decision nodes can use them directly
            for fld in _ALL_REPORT_FIELDS:
                if existing.get(fld):
                    init_state[fld] = existing[fld]

        args = ta.propagator.get_graph_args()

        _PARTIAL_FIELDS = [
            "market_report", "sentiment_report", "news_report", "fundamentals_report",
            "investment_plan", "trader_investment_plan",
        ]

        final_state: dict = {}
        result_cache: dict = dict(existing)

        from server.usage import APICallLimitError
        for chunk in ta.graph.stream(init_state, **args):
            if usage_tracker.total_calls > usage_tracker.max_calls:
                raise APICallLimitError(
                    f"API 调用次数已达上限 ({usage_tracker.max_calls} 次），分析已自动中止。"
                    f"如需继续，请人工确认后重新运行。"
                )
            final_state.update(chunk)

            # ── Analyst-only rerun: stop as soon as target report appears ──
            if report_key and final_state.get(report_key):
                new_result = dict(existing)
                new_result[report_key] = final_state[report_key]
                record.result = new_result
                record.status = "complete"
                record.stage = "complete"
                record.stage_detail = f"{label} 重新分析完成"
                record.completed_at = datetime.utcnow()
                record.seen = False
                db.commit()
                return   # ← exit task; do NOT run debate/risk/decision

            new_fields = {
                f: final_state[f]
                for f in _PARTIAL_FIELDS
                if final_state.get(f) and final_state[f] != existing.get(f)
            }
            if new_fields:
                result_cache.update(new_fields)
                record.result = dict(result_cache)
                db.commit()

            new_stage, detail = _detect_progress(final_state, record)
            _update_progress(db, record, stage=new_stage, detail=detail)

        # ── Decision-stage rerun: full pipeline finished ───────────────────
        raw_decision = _strip_tool_call_prefix(final_state.get("final_trade_decision", ""))
        decision_str = ta.process_signal(raw_decision) if raw_decision else ""
        decision = _extract_decision_label(decision_str) if decision_str else record.decision

        new_result = dict(existing)
        for fld in _PARTIAL_FIELDS + ["final_trade_decision"]:
            if final_state.get(fld):
                new_result[fld] = final_state[fld]

        record.status = "complete"
        record.stage = "complete"
        record.stage_detail = f"{label} 重新分析完成"
        record.decision = decision
        record.result = new_result
        record.completed_at = datetime.utcnow()
        record.seen = False
        db.commit()
        _extract_strategy(db, record)

    except Exception as exc:
        logger.exception("rerun_stage failed for %s stage %s", analysis_id, stage)
        rec = db.get(Analysis, analysis_id)
        if rec:
            rec.status = "failed"
            rec.stage_detail = f"重新分析失败: {str(exc)[:150]}"
            rec.error = str(exc)
            rec.seen = False
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
