# server/tasks.py
import logging
import os
from datetime import datetime

from server.celery_app import celery_app
from server.database import SessionLocal
from server.models import Analysis

logger = logging.getLogger(__name__)

# Map LangGraph node names to UI stage labels
_NODE_TO_STAGE = {
    "Research Manager": "debate",
    "Trader": "risk",
    "Portfolio Manager": "decision",
}

# Map provider name → environment variable that holds the API key
_PROVIDER_ENV = {
    "qwen":       "DASHSCOPE_API_KEY",
    "qwen-cn":    "DASHSCOPE_CN_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "anthropic":  "ANTHROPIC_API_KEY",
    "deepseek":   "DEEPSEEK_API_KEY",
    "glm":        "ZHIPU_API_KEY",
    "glm-cn":     "ZHIPU_CN_API_KEY",
}


def _set_stage(db, record: Analysis, stage: str):
    record.stage = stage
    db.commit()


def _apply_llm_config(config: dict, llm_config: dict) -> dict:
    """Overlay DB settings onto the DEFAULT_CONFIG copy and set env vars."""
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

    # Inject API key into environment so the LLM client can find it
    api_key = llm_config.get("api_key")
    if api_key and provider:
        env_var = _PROVIDER_ENV.get(provider)
        if env_var:
            os.environ[env_var] = api_key

    return config


@celery_app.task(bind=True, name="server.tasks.run_analysis")
def run_analysis(self, analysis_id: str):
    """Run TradingAgentsGraph for the given analysis record.

    Progress is written to Analysis.stage so the SSE endpoint can stream it.
    Node names from LangGraph are mapped to 4 UI stages:
      analysts → debate → risk → decision → complete
    """
    db = SessionLocal()
    try:
        record = db.get(Analysis, analysis_id)
        if not record:
            logger.error("run_analysis: analysis %s not found", analysis_id)
            return

        record.status = "running"
        record.stage = "analysts"
        db.commit()

        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config["output_language"] = "Chinese"
        config["max_debate_rounds"] = record.depth
        config["max_risk_discuss_rounds"] = record.depth
        config["debug"] = True
        config["checkpoint_enabled"] = False

        # Apply LLM settings from DB (snapshotted at submission time)
        config = _apply_llm_config(config, record.llm_config or {})

        ta = TradingAgentsGraph(debug=True, config=config)

        init_state = ta.propagator.create_initial_state(
            record.ticker, record.trade_date, asset_type="stock", past_context=""
        )
        args = ta.propagator.get_graph_args()

        final_state = {}
        for chunk in ta.graph.stream(init_state, **args):
            final_state.update(chunk)
            for node_name, new_stage in _NODE_TO_STAGE.items():
                if node_name in chunk:
                    _set_stage(db, record, new_stage)
                    break

        decision_str = ta.process_signal(final_state.get("final_trade_decision", ""))
        decision = _extract_decision_label(decision_str)

        record.status = "complete"
        record.stage = "complete"
        record.decision = decision
        record.result = {
            "market_report": final_state.get("market_report"),
            "sentiment_report": final_state.get("sentiment_report"),
            "news_report": final_state.get("news_report"),
            "fundamentals_report": final_state.get("fundamentals_report"),
            "investment_plan": final_state.get("investment_plan"),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
            "final_trade_decision": final_state.get("final_trade_decision"),
        }
        record.completed_at = datetime.utcnow()
        record.seen = False
        db.commit()

    except Exception as exc:
        logger.exception("run_analysis failed for %s", analysis_id)
        record = db.get(Analysis, analysis_id)
        if record:
            record.status = "failed"
            record.error = str(exc)
            record.seen = False
            db.commit()
        raise
    finally:
        db.close()


def _extract_decision_label(decision_str: str) -> str:
    """Extract BUY, HOLD, or SELL from the process_signal output string."""
    upper = (decision_str or "").upper()
    for label in ("BUY", "SELL", "HOLD"):
        if label in upper:
            return label
    return "HOLD"
