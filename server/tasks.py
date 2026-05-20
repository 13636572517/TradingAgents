# server/tasks.py
import logging
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


def _set_stage(db, record: Analysis, stage: str):
    record.stage = stage
    db.commit()


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
