"""Mock LLM for data-fetching tests (MOCK_LLM=1 mode).

Simulates tool-calling: on first invocation calls every bound tool once
using args parsed from the conversation context, then on second invocation
returns a plain-text summary. LLM API is never contacted.
"""
from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime, timedelta
from typing import Any, List, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_ticker(messages: List[BaseMessage]) -> str:
    for m in messages:
        text = getattr(m, "content", "") or ""
        hit = re.search(r"\b([A-Z0-9]{1,6}\.(SS|SZ|HK))\b|ticker[:\s]+([A-Z0-9]{2,6})", text, re.I)
        if hit:
            return (hit.group(1) or hit.group(3) or "").upper()
    return "UNKNOWN"


def _extract_date(messages: List[BaseMessage]) -> str:
    for m in messages:
        text = getattr(m, "content", "") or ""
        hit = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if hit:
            return hit.group(1)
    return datetime.now().strftime("%Y-%m-%d")


def _start_date(curr: str, days: int = 90) -> str:
    d = datetime.strptime(curr[:10], "%Y-%m-%d") - timedelta(days=days)
    return d.strftime("%Y-%m-%d")


# Default args for every tool the agents use
_TOOL_ARGS: dict[str, Any] = {}   # populated per-call with ticker/date


def _tool_args(name: str, ticker: str, curr_date: str) -> dict:
    start = _start_date(curr_date)
    mapping = {
        # market analyst  (param name is 'symbol', not 'ticker')
        "get_stock_data":       {"symbol": ticker, "start_date": start, "end_date": curr_date},
        "get_indicators":       {"symbol": ticker, "indicator": "rsi", "curr_date": curr_date, "look_back_days": 60},
        # fundamentals analyst
        "get_fundamentals":     {"ticker": ticker, "curr_date": curr_date},
        "get_balance_sheet":    {"ticker": ticker, "freq": "quarterly", "curr_date": curr_date},
        "get_income_statement": {"ticker": ticker, "freq": "quarterly", "curr_date": curr_date},
        "get_cashflow":         {"ticker": ticker, "freq": "quarterly", "curr_date": curr_date},
        # news / sentiment
        "get_news":             {"ticker": ticker, "start_date": start, "end_date": curr_date},
        "get_global_news":      {"curr_date": curr_date, "look_back_days": 7},
        "get_insider_transactions": {"ticker": ticker},
    }
    return mapping.get(name, {"ticker": ticker})


# ── Mock model ─────────────────────────────────────────────────────────────────

class DataTestMockLLM(BaseChatModel):
    """Bind-tools-capable mock that actually calls data tools, skips the LLM."""

    _bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "data-test-mock"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "DataTestMockLLM":
        clone = DataTestMockLLM()
        clone._bound_tools = list(tools)
        return clone

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Check which tools have already been called
        called = {m.name for m in messages if isinstance(m, ToolMessage)}
        remaining = [t for t in self._bound_tools if t.name not in called]

        if remaining:
            ticker = _extract_ticker(messages)
            curr_date = _extract_date(messages)
            # Call ONE tool at a time to avoid concurrent-connection limits on JoinQuant
            tool = remaining[0]
            tool_calls = [{
                "id": str(uuid.uuid4()),
                "name": tool.name,
                "args": _tool_args(tool.name, ticker, curr_date),
                "type": "tool_call",
            }]
            logger.info("[MOCK LLM] calling tool: %s", tool.name)
            ai_msg = AIMessage(content="", tool_calls=tool_calls)
        else:
            tool_summaries = "\n".join(
                f"- {m.name}: {str(m.content)[:120]}…" for m in messages if isinstance(m, ToolMessage)
            )
            ai_msg = AIMessage(
                content=(
                    f"[MOCK ANALYSIS — data fetch test]\n\n"
                    f"All data tools executed successfully:\n{tool_summaries}\n\n"
                    f"Recommendation: HOLD (mock)"
                )
            )
            logger.info("[MOCK LLM] returning final text after %d tool results", len(called))

        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    # Required abstract — synchronous only needed
    def _stream(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    # LangChain requires this for serialisation
    @property
    def _identifying_params(self) -> dict:
        return {"model": "data-test-mock"}
