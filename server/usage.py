# server/usage.py
"""Per-model LLM usage tracking via LangChain callbacks.

A single CombinedUsageTracker is injected into TradingAgentsGraph.callbacks.
LangChain passes it to both the quick and deep LLM clients, so the tracker
identifies which model fired each event via invocation_params and routes to
the appropriate per-role sub-tracker.

Cost estimation uses user-configurable prices per 1M tokens (input/output).
If prices are not set (0.0), cost_cny will be 0.0 — users can check their
actual bills on the provider's dashboard.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


def _extract_model_name(kwargs: dict) -> str | None:
    """Try to get the model name from LangChain callback kwargs."""
    # invocation_params is present for OpenAI-compatible providers
    ip = kwargs.get("invocation_params", {})
    return ip.get("model") or ip.get("model_name") or ip.get("model_id")


# ── Per-role slot ──────────────────────────────────────────────────────────────

class _Slot:
    def __init__(self, model_name: str, role: str, input_cost_per_million: float = 0.0, output_cost_per_million: float = 0.0):
        self.model_name = model_name
        self.role = role
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.tool_calls = 0
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million

    def _calc_cost(self) -> float:
        """Calculate cost in CNY based on token counts and configured prices."""
        if self.input_cost_per_million <= 0 and self.output_cost_per_million <= 0:
            return 0.0
        cost = (
            self.tokens_in / 1_000_000 * self.input_cost_per_million +
            self.tokens_out / 1_000_000 * self.output_cost_per_million
        )
        return round(cost, 4)

    def to_dict(self) -> dict:
        return {
            "model":      self.model_name,
            "calls":      self.calls,
            "tokens_in":  self.tokens_in,
            "tokens_out": self.tokens_out,
            "tool_calls": self.tool_calls,
            "cost_cny":   self._calc_cost(),
        }


# ── Combined tracker (single callback, routes by model name) ───────────────────

class APICallLimitError(RuntimeError):
    """Raised when an analysis exceeds its per-run API call budget."""


class CombinedUsageTracker(BaseCallbackHandler):
    """Single callback handler that routes events to quick/deep slots by model name."""

    def __init__(self, quick_model: str, deep_model: str, max_calls: int = 60,
                 input_cost_per_million: float = 0.0, output_cost_per_million: float = 0.0) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.quick = _Slot(quick_model, "quick", input_cost_per_million, output_cost_per_million)
        self.deep  = _Slot(deep_model,  "deep",  input_cost_per_million, output_cost_per_million)
        self.max_calls = max_calls
        # thread-local to remember which slot fired on_chat_model_start
        self._active: threading.local = threading.local()

    @property
    def total_calls(self) -> int:
        return self.quick.calls + self.deep.calls

    def _slot_for(self, model_hint: str | None) -> _Slot:
        """Return the slot matching model_hint, defaulting to quick."""
        if model_hint and self.deep.model_name.lower() in model_hint.lower():
            return self.deep
        if model_hint and self.quick.model_name.lower() in model_hint.lower():
            return self.quick
        # Fallback: if no match, use quick (it's the majority caller)
        return self.quick

    def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        model_hint = _extract_model_name(kwargs)
        slot = self._slot_for(model_hint)
        with self._lock:
            slot.calls += 1
        # Remember active slot for on_llm_end (same thread in prefork)
        self._active.slot = slot

    def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        model_hint = _extract_model_name(kwargs)
        slot = self._slot_for(model_hint)
        with self._lock:
            slot.calls += 1
        self._active.slot = slot

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        slot = getattr(self._active, "slot", self.quick)
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        tokens_in = 0
        tokens_out = 0

        # Path 1: usage_metadata on AIMessage (LangChain standard — OpenAI, Anthropic, Gemini)
        if hasattr(generation, "message"):
            msg = generation.message
            if isinstance(msg, AIMessage):
                meta = getattr(msg, "usage_metadata", None) or {}
                if meta:
                    tokens_in  = meta.get("input_tokens",  0)
                    tokens_out = meta.get("output_tokens", 0)

        # Path 2: generation_info["token_usage"] (OpenAI-compatible providers incl. DashScope/Qwen)
        if not tokens_in and not tokens_out:
            info = getattr(generation, "generation_info", None) or {}
            tu = info.get("token_usage") or info.get("usage") or {}
            tokens_in  = tu.get("prompt_tokens",     0) or tu.get("input_tokens",  0)
            tokens_out = tu.get("completion_tokens", 0) or tu.get("output_tokens", 0)

        if tokens_in or tokens_out:
            with self._lock:
                slot.tokens_in  += tokens_in
                slot.tokens_out += tokens_out

    def on_tool_start(self, serialized: Any, input_str: Any, **kwargs: Any) -> None:
        # Tool calls are attributed to the quick model (all analysts use quick)
        with self._lock:
            self.quick.tool_calls += 1

    def collect(self) -> dict:
        """Return usage summary dict for storage in Analysis.usage."""
        with self._lock:
            q = self.quick.to_dict()
            d = self.deep.to_dict()
        total_cost = round(q["cost_cny"] + d["cost_cny"], 4)
        return {
            "quick":          q,
            "deep":           d,
            "total_cost_cny": total_cost,
        }
