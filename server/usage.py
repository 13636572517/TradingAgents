# server/usage.py
"""Per-model LLM usage tracking via LangChain callbacks.

A single CombinedUsageTracker is injected into TradingAgentsGraph.callbacks.
LangChain passes it to both the quick and deep LLM clients, so the tracker
identifies which model fired each event via invocation_params and routes to
the appropriate per-role sub-tracker.
"""
from __future__ import annotations

import threading
from typing import Any, Dict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult

# ── Pricing table (CNY per 1 000 tokens) ──────────────────────────────────────
_PRICE_CNY: Dict[str, tuple] = {
    # Qwen (DashScope)
    "qwen3.6-flash":             (0.00035, 0.001),
    "qwen3.5-flash":             (0.00035, 0.001),
    "qwen3.6-plus":              (0.004,   0.016),
    "qwen3.5-plus":              (0.004,   0.012),
    "qwen3-max":                 (0.024,   0.096),
    # OpenAI (7.2 CNY/USD)
    "gpt-4o-mini":               (0.0011,  0.0043),
    "gpt-4o":                    (0.018,   0.072),
    "gpt-4.1":                   (0.018,   0.072),
    "gpt-4.1-mini":              (0.0014,  0.0057),
    # Anthropic (7.2 CNY/USD)
    "claude-haiku-4-5-20251001": (0.0018,  0.009),
    "claude-sonnet-4-6":         (0.022,   0.108),
    "claude-opus-4-7":           (0.108,   0.540),
    # DeepSeek
    "deepseek-chat":             (0.002,   0.008),
    "deepseek-reasoner":         (0.004,   0.016),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    key = model.lower()
    # Exact match first
    price = _PRICE_CNY.get(key)
    # Fallback: strip date/version suffixes (e.g. "qwen3.5-plus-2026-04-20" → "qwen3.5-plus")
    if not price:
        for table_key in sorted(_PRICE_CNY, key=len, reverse=True):
            if key.startswith(table_key):
                price = _PRICE_CNY[table_key]
                break
    if not price:
        return 0.0
    p_in, p_out = price
    return round(tokens_in / 1000 * p_in + tokens_out / 1000 * p_out, 4)


def _extract_model_name(kwargs: dict) -> str | None:
    """Try to get the model name from LangChain callback kwargs."""
    # invocation_params is present for OpenAI-compatible providers
    ip = kwargs.get("invocation_params", {})
    return ip.get("model") or ip.get("model_name") or ip.get("model_id")


# ── Per-role slot ──────────────────────────────────────────────────────────────

class _Slot:
    def __init__(self, model_name: str, role: str):
        self.model_name = model_name
        self.role = role
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.tool_calls = 0

    def to_dict(self) -> dict:
        cost = estimate_cost(self.model_name, self.tokens_in, self.tokens_out)
        return {
            "model":      self.model_name,
            "calls":      self.calls,
            "tokens_in":  self.tokens_in,
            "tokens_out": self.tokens_out,
            "tool_calls": self.tool_calls,
            "cost_cny":   cost,
        }


# ── Combined tracker (single callback, routes by model name) ───────────────────

class APICallLimitError(RuntimeError):
    """Raised when an analysis exceeds its per-run API call budget."""


class CombinedUsageTracker(BaseCallbackHandler):
    """Single callback handler that routes events to quick/deep slots by model name."""

    def __init__(self, quick_model: str, deep_model: str, max_calls: int = 60) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.quick = _Slot(quick_model, "quick")
        self.deep  = _Slot(deep_model,  "deep")
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
