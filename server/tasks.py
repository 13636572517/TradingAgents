# server/tasks.py
import logging
import os
from datetime import datetime, timedelta

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
    """Build / upsert an AnalysisStrategy record after an analysis completes.
    Uses regex first, then refines with AI (using current AppSettings)."""
    try:
        import uuid as _uuid
        from server.strategy_extractor import build_strategy_from_analysis
        from server.models import AppSettings
        settings = db.get(AppSettings, 1)
        existing = db.query(AnalysisStrategy).filter_by(analysis_id=record.id).first()
        data = build_strategy_from_analysis(record, settings=settings)
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


def _build_past_context(db, ticker: str, exclude_id: str) -> str:
    """Build a past_context string from the most recent completed analysis of the same ticker."""
    from server.models import Analysis as _Analysis
    prev = (
        db.query(_Analysis)
        .filter(
            _Analysis.ticker == ticker,
            _Analysis.status == "complete",
            _Analysis.id != exclude_id,
        )
        .order_by(_Analysis.completed_at.desc())
        .first()
    )
    if not prev:
        return ""

    result = prev.result or {}
    decision_text = result.get("final_trade_decision") or result.get("trader_investment_plan") or ""
    date_str = prev.trade_date or (prev.completed_at.strftime("%Y-%m-%d") if prev.completed_at else "unknown")
    tag = f"[{date_str} | {ticker} | {prev.decision or 'N/A'}]"
    return f"{tag}\n\nDECISION:\n{decision_text}" if decision_text else tag


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
        from server.pricing_utils import get_model_tiers
        _app_cfg = db.get(_AppSettings, 1)
        _max_calls = (_app_cfg.max_api_calls if _app_cfg and _app_cfg.max_api_calls else 60)
        _input_cost = (_app_cfg.input_cost_per_million if _app_cfg else 0.0) or 0.0
        _output_cost = (_app_cfg.output_cost_per_million if _app_cfg else 0.0) or 0.0
        _quick_tiers = get_model_tiers(db, config["quick_think_llm"])
        _deep_tiers  = get_model_tiers(db, config["deep_think_llm"])
        usage_tracker = CombinedUsageTracker(
            quick_model=config["quick_think_llm"],
            deep_model=config["deep_think_llm"],
            max_calls=_max_calls,
            input_cost_per_million=_input_cost,
            output_cost_per_million=_output_cost,
            quick_pricing_tiers=_quick_tiers,
            deep_pricing_tiers=_deep_tiers,
        )

        ta = TradingAgentsGraph(
            debug=True,
            config=config,
            callbacks=[usage_tracker],
        )
        past_context = _build_past_context(db, record.ticker, exclude_id=analysis_id)
        init_state = ta.propagator.create_initial_state(
            record.ticker, record.trade_date, asset_type="stock", past_context=past_context
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
        from server.pricing_utils import get_model_tiers
        _app_cfg = db.get(_AppSettings, 1)
        _max_calls = (_app_cfg.max_api_calls if _app_cfg and _app_cfg.max_api_calls else 60)
        _input_cost = (_app_cfg.input_cost_per_million if _app_cfg else 0.0) or 0.0
        _output_cost = (_app_cfg.output_cost_per_million if _app_cfg else 0.0) or 0.0
        _quick_tiers = get_model_tiers(db, config["quick_think_llm"])
        _deep_tiers  = get_model_tiers(db, config["deep_think_llm"])
        usage_tracker = CombinedUsageTracker(
            quick_model=config["quick_think_llm"],
            deep_model=config["deep_think_llm"],
            max_calls=_max_calls,
            input_cost_per_million=_input_cost,
            output_cost_per_million=_output_cost,
            quick_pricing_tiers=_quick_tiers,
            deep_pricing_tiers=_deep_tiers,
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


# ── Shared analysis launcher (used by API + screener) ───────────────────────────

_DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals"]


def launch_analysis(db, ticker: str, owner_id=None, depth: int = 1,
                    analysts: list = None, trade_date: str = None):
    """Create an Analysis record and dispatch run_analysis. Returns the record.

    Mirrors the logic in routers/analyses.create_analysis so the screener can
    trigger deep analyses programmatically.
    """
    from server.models import AppSettings

    settings = db.get(AppSettings, 1)
    llm_config = {
        "provider":    settings.provider    if settings else "openai",
        "api_key":     settings.api_key     if settings else None,
        "deep_model":  settings.deep_model  if settings else "gpt-4o",
        "quick_model": settings.quick_model if settings else "gpt-4o-mini",
        "backend_url": settings.backend_url if settings else None,
    } if settings else {}

    ticker_name = None
    try:
        from tradingagents.dataflows.stock_name_lookup import get_stock_name
        ticker_name = get_stock_name(ticker)
    except Exception as e:
        logger.debug("Stock name lookup failed for %s: %s", ticker, e)

    record = Analysis(
        ticker=ticker.upper(),
        ticker_name=ticker_name,
        trade_date=trade_date or datetime.now().strftime("%Y-%m-%d"),
        analysts=_normalize_analysts(analysts or _DEFAULT_ANALYSTS),
        depth=depth,
        status="pending",
        stage="pending",
        seen=True,
        llm_config=llm_config,
        owner_id=owner_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    task = run_analysis.delay(record.id)
    record.celery_task_id = task.id
    db.commit()
    return record


# ── Stock screening tasks ───────────────────────────────────────────────────────

@celery_app.task(bind=True, name="server.tasks.run_screening_task")
def run_screening_task(self, run_id: str, auto_analyze: bool = False,
                       auto_analyze_top: int = 3, depth: int = 1):
    """Execute the screening pipeline for an existing ScreeningRun row.

    Persists ScreeningCandidate rows, updates the run summary/status, and
    optionally launches deep analyses for the top-scoring candidates.

    Progress is written to ScreeningRun.error as human-readable step messages,
    visible on the frontend via the polling GET /screener/runs/{id} endpoint.
    """
    import uuid
    from server.models import ScreeningRun, ScreeningCandidate
    from server.screener import run_screening

    # Pre-flight: check TickFlow before launching the heavy screening pipeline.
    # The screener needs TickFlow for board PE/PB percentiles — without it the
    # results degrade to sparse AkShare/JoinQuant data that may mislead users.
    from tradingagents.dataflows.tickflow_data import tickflow_available
    tf_ok, tf_reason = tickflow_available()
    if not tf_ok:
        logger.warning("run_screening_task: TickFlow unavailable (%s) — aborting run %s", tf_reason, run_id)
        db = SessionLocal()
        try:
            run = db.get(ScreeningRun, run_id)
            if run and run.status == "running":
                run.status = "failed"
                run.error = f"TickFlow 数据源不可用（{tf_reason}），请稍后重试。"
                run.completed_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
        return
    logger.info("run_screening_task: TickFlow OK (%s), starting run %s...", tf_reason, run_id)

    db = SessionLocal()
    run = None
    try:
        run = db.get(ScreeningRun, run_id)
        if not run:
            logger.warning("run_screening_task: run %s not found", run_id)
            return

        # Re-read the TickFlow key from DB on every run. The worker only
        # hydrates keys at startup, so a key saved/changed via the settings
        # page after the worker booted would otherwise be missed, silently
        # degrading screening to the AkShare/JoinQuant fallbacks (which don't
        # carry price/pct_change). Refreshing here keeps screening on TickFlow.
        try:
            import os
            from server.models import AppSettings
            _s = db.get(AppSettings, 1)
            if _s and _s.tickflow_api_key:
                os.environ["TICKFLOW_API_KEY"] = _s.tickflow_api_key
        except Exception:
            pass  # non-critical; screening will degrade to akshare/joinquant

        def _progress(msg: str):
            """Write progress message to DB so frontend can poll it."""
            run.error = msg
            db.commit()
            logger.info("[screening %s] %s", run_id, msg)

        _progress("正在获取全市场行情快照（TickFlow → AkShare → JoinQuant）…")
        try:
            result = run_screening(db, params=run.params or None, progress=_progress)
        except Exception as e:
            logger.error("run_screening_task failed: %s", e)
            run.status = "failed"
            run.error = str(e)
            run.completed_at = datetime.utcnow()
            db.commit()
            return

        _progress("正在持久化候选股并更新筛选记录…")
        candidates = result["candidates"]
        # Persist candidates, ranked globally by score for auto-analysis ordering
        candidates_sorted = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
        rows = []
        for c in candidates:
            row = ScreeningCandidate(
                id=str(uuid.uuid4()),
                run_id=run.id,
                board_name=c["board_name"],
                board_level=c.get("board_level", 1),
                board_pe_pct=c.get("board_pe_pct"),
                board_pb_pct=c.get("board_pb_pct"),
                board_valuation_method=c.get("board_valuation_method"),
                code=c.get("code"),
                ticker=c["ticker"],
                ticker_name=c.get("name"),
                price=c.get("price"),
                pct_change=c.get("pct_change"),
                total_mktcap=c.get("total_mktcap"),
                pe=c.get("pe"),
                pb=c.get("pb"),
                roe=c.get("roe"),
                amount=c.get("amount"),
                net_inflow=c.get("net_inflow"),
                net_profit_yoy=c.get("net_profit_yoy"),
                debt_ratio=c.get("debt_ratio"),
                gross_margin=c.get("gross_margin"),
                ocf_to_revenue=c.get("ocf_to_revenue"),
                eps_ttm=c.get("eps_ttm"),
                bps=c.get("bps"),
                rank_in_board=c.get("rank_in_board"),
                score=c.get("score"),
                reason=c.get("reason"),
            )
            db.add(row)
            rows.append(row)
        db.commit()

        run.status = "complete"
        run.summary = {
            **result["summary"],
            "undervalued_boards": [
                {
                    "name": b["name"],
                    "pe": b.get("pe"),
                    "pb": b.get("pb"),
                    "pe_pct": b.get("pe_pct"),
                    "pb_pct": b.get("pb_pct"),
                    "valuation_method": b.get("valuation_method"),
                    "pct_change": b.get("pct_change"),
                    "member_count": b.get("member_count"),
                }
                for b in result["summary"].get("all_boards", [])
                if b.get("is_undervalued")
            ],
        }
        # Backfill the legacy summary counter (used by progress msg + frontend
        # badge); c8ea451 stopped emitting it as a single top-level key.
        run.summary["undervalued_count"] = sum(
            1 for b in result["summary"].get("all_boards", [])
            if b.get("is_undervalued")
        )
        run.completed_at = datetime.utcnow()
        run.error = None  # Clear progress messages on success
        db.commit()

        _progress(f"筛选完成！{run.summary['undervalued_count']} 个低估板块，{len(candidates)} 只候选股")

        # Optionally auto-analyze the top-N candidates by score
        if auto_analyze and candidates_sorted:
            ticker_to_row = {r.ticker: r for r in rows}
            launched_tickers = set()
            for c in candidates_sorted[:auto_analyze_top]:
                tk = c["ticker"]
                if tk in launched_tickers:
                    continue
                launched_tickers.add(tk)
                try:
                    analysis = launch_analysis(db, tk, owner_id=run.owner_id, depth=depth)
                    cand = ticker_to_row.get(tk)
                    if cand:
                        cand.analysis_id = analysis.id
                    db.commit()
                except Exception as e:
                    logger.warning("auto-analyze failed for %s: %s", tk, e)
                    db.rollback()
    except Exception as e:
        # Safety net: any uncaught error (incl. DB commit failures during
        # persistence) must not leave the row stuck in 'running' — otherwise
        # the frontend polls a zombie progress message forever.
        logger.exception("run_screening_task uncaught error for run %s", run_id)
        if run is not None:
            try:
                db.rollback()
                run.status = "failed"
                run.error = f"任务异常中断：{type(e).__name__}: {e}"
                run.completed_at = datetime.utcnow()
                db.commit()
            except Exception:
                logger.exception("failed to mark run %s as failed", run_id)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="server.tasks.scheduled_daily_screening")
def scheduled_daily_screening(self):
    """Celery-beat entry point: create a scheduled ScreeningRun and execute it
    with auto-analysis of the top candidates."""
    import uuid
    from server.models import ScreeningRun

    db = SessionLocal()
    try:
        run = ScreeningRun(
            id=str(uuid.uuid4()),
            run_date=datetime.now().strftime("%Y-%m-%d"),
            status="running",
            trigger="scheduled",
            params=None,
            owner_id=None,
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    run_screening_task.apply(args=[run_id], kwargs={"auto_analyze": True, "auto_analyze_top": 3})


@celery_app.task(bind=True, name="server.tasks.nightly_cache_backfill")
def nightly_cache_backfill(self):
    """Warm the OHLCV + financials cache for actively-tracked symbols overnight.

    Targets every symbol already in the OHLCV cache plus the latest screening
    run's candidates, and pulls just the incremental delta (handled by
    ``_load_ohlcv_cached`` / ``tf_financials_valuation``). This means by the
    time users open the detail page or the next screener runs in the morning,
    TickFlow round-trips are already paid for.
    """
    # Pre-flight: skip if TickFlow is down to avoid flooding the dead endpoint
    # with thousands of retries. The cache is 5 min TTL, so a transient glitch
    # will self-heal on the next minute's cron window.
    from tradingagents.dataflows.tickflow_data import tickflow_available
    tf_ok, tf_reason = tickflow_available()
    if not tf_ok:
        logger.warning("nightly_cache_backfill: TickFlow unavailable (%s) — skipping", tf_reason)
        return
    logger.info("nightly_cache_backfill: TickFlow OK (%s), starting...", tf_reason)

    from tradingagents.dataflows.tickflow_data import (
        _to_tf_code, _load_ohlcv_cached, tf_financials_valuation,
    )
    from server.models import StockOHLCV, ScreeningCandidate, ScreeningRun

    db = SessionLocal()
    try:
        tf_symbols = {s for (s,) in db.query(StockOHLCV.symbol).distinct().all()}

        latest_run = (
            db.query(ScreeningRun)
            .filter(ScreeningRun.status == "complete")
            .order_by(ScreeningRun.created_at.desc())
            .first()
        )
        if latest_run:
            candidates = (
                db.query(ScreeningCandidate)
                .filter(ScreeningCandidate.run_id == latest_run.id)
                .all()
            )
            for c in candidates:
                try:
                    tf_symbols.add(_to_tf_code(c.ticker))
                except Exception:
                    pass
    finally:
        db.close()

    tf_symbols = sorted(tf_symbols)
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")

    ohlcv_ok = ohlcv_fail = 0
    for sym in tf_symbols:
        try:
            _load_ohlcv_cached(sym, start, today, adjust="forward")
            ohlcv_ok += 1
        except Exception:
            ohlcv_fail += 1

    fin_count = 0
    try:
        fin_result = tf_financials_valuation(tf_symbols)
        fin_count = len(fin_result)
    except Exception:
        logger.exception("nightly_cache_backfill: financials refresh failed")

    logger.info(
        "nightly_cache_backfill: %d symbols, ohlcv ok=%d fail=%d, financials updated=%d",
        len(tf_symbols), ohlcv_ok, ohlcv_fail, fin_count,
    )


@celery_app.task(bind=True, name="server.tasks.full_market_backfill")
def full_market_backfill(self):
    """One-time backfill of ~10 years of OHLCV + financial-statement history

    Most expensive TickFlow task — pulls hundreds of thousands of OHLCV bars
    and financial statement rows. Skip entirely if TickFlow is down.
    """
    from tradingagents.dataflows.tickflow_data import tickflow_available
    tf_ok, tf_reason = tickflow_available()
    if not tf_ok:
        logger.warning("full_market_backfill: TickFlow unavailable (%s) — skipping", tf_reason)
        return
    logger.info("full_market_backfill: TickFlow OK (%s), starting...", tf_reason)
    for the entire CN A-share universe.

    Not on the beat schedule — trigger manually (e.g. via
    ``full_market_backfill.delay()`` from a shell) during off-peak hours.
    At ~28 kline batches (200 symbols/req) + ~220 financial batches
    (100 symbols/req x4 statements) this is well within TickFlow Expert's
    120/min limits and should complete in a few minutes.
    """
    from tradingagents.dataflows.tickflow_data import (
        tf_universe_symbols, tf_batch_klines_history, tf_financials_full_history,
    )

    tf_symbols = tf_universe_symbols(["CN_Equity_A"])
    logger.info("full_market_backfill: %d symbols in CN_Equity_A universe", len(tf_symbols))

    # Resume support: skip symbols already covered (have bars fetched within last 30 days)
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        from sqlalchemy import text as _text
        rows = db.execute(
            _text("SELECT DISTINCT symbol FROM stock_ohlcv WHERE fetched_at >= :cutoff"),
            {"cutoff": cutoff},
        ).fetchall()
        done_symbols = {r[0] for r in rows}
    finally:
        db.close()
    pending_symbols = [s for s in tf_symbols if s not in done_symbols]
    logger.info("full_market_backfill: %d already done, %d pending",
                len(done_symbols), len(pending_symbols))

    ohlcv_result = tf_batch_klines_history(pending_symbols, count=2500)
    logger.info("full_market_backfill: OHLCV history cached for %d/%d symbols",
                 len(ohlcv_result), len(tf_symbols))

    start_date = (datetime.now() - timedelta(days=365 * 10)).strftime("%Y%m%d")
    fin_totals = tf_financials_full_history(tf_symbols, start_date)
    logger.info("full_market_backfill: financial records upserted: %s", fin_totals)

    return {
        "symbol_count": len(tf_symbols),
        "ohlcv_symbols_cached": len(ohlcv_result),
        "financials": fin_totals,
    }
