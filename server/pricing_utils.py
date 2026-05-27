# server/pricing_utils.py
"""Utilities for per-model tiered LLM pricing.

Supports importing pricing from Alibaba Cloud Bailian Markdown tables and
calculating tiered costs based on average input tokens per API call.

Tier storage format (JSON array, sorted by max_k ascending):
    [{"max_k": 32, "input_price": 2.5, "output_price": 10.0}, ...]
    max_k: upper bound in thousands of tokens (32 → 32K); None = unlimited (last tier)
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ── Markdown parsing ───────────────────────────────────────────────────────────

def _parse_price(cell: str) -> Optional[float]:
    """Extract first number from strings like '2.5元', '10元', '0.15元'."""
    m = re.search(r'([\d]+(?:\.[\d]+)?)\s*元', cell)
    return float(m.group(1)) if m else None


def _parse_max_k(token_range: str) -> Optional[int]:
    """Parse token range → upper bound in K tokens. Returns None for unlimited.

    Examples:
        '0<Token≤32K'    → 32
        '32K<Token≤128K' → 128
        '0<Token≤1M'     → 1000
        '无阶梯计价'       → None
    """
    if not token_range or '无阶梯' in token_range:
        return None
    cleaned = token_range.replace(',', '').replace(' ', '')
    m = re.search(r'≤\s*(\d+)\s*(K|M|k|m)', cleaned)
    if m:
        val = int(m.group(1))
        unit = m.group(2).upper()
        return val if unit == 'K' else val * 1000
    return None


def _clean_model_id(cell: str) -> Optional[str]:
    """Extract a clean model ID from a cell like 'qwen3-max > alias > ...'."""
    if not cell:
        return None
    # Take text before first '>'
    first = cell.split('>')[0]
    # Strip markdown: bold (**), backticks, links [text](url), spaces
    first = re.sub(r'\*+', '', first)
    first = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', first)
    first = re.sub(r'`', '', first)
    first = first.strip()
    # Remove internal whitespace
    first = re.sub(r'\s+', '', first)
    # Must look like a model ID: starts with letter, contains only [a-z0-9.-]
    if re.match(r'^[a-zA-Z][a-zA-Z0-9\-\.]+$', first) and len(first) >= 4:
        return first.lower()
    return None


def parse_cn_pricing_md(md_text: str) -> dict[str, list]:
    """Parse Alibaba Cloud Bailian pricing Markdown (中国内地 region).

    Returns:
        {model_id: [{"max_k": int|None, "input_price": float, "output_price": float}, ...]}
        Tiers are sorted ascending by max_k; last entry may have max_k=None (unlimited).
    """
    result: dict[str, list] = {}

    # Find all ## headings to compute section boundaries
    all_h2 = [m.start() for m in re.finditer(r'^##[^#]', md_text, re.MULTILINE)]

    # Find all 中国内地 sections (## 中国内地)
    cn_positions = [m.start() for m in re.finditer(r'^## 中国内地', md_text, re.MULTILINE)]

    if not cn_positions:
        logger.warning("No '## 中国内地' section found in pricing MD")

    for cn_pos in cn_positions:
        # Section ends at next ## heading
        next_h2s = [p for p in all_h2 if p > cn_pos]
        section_end = next_h2s[0] if next_h2s else len(md_text)
        section = md_text[cn_pos:section_end]

        current_model: Optional[str] = None

        for line in section.split('\n'):
            if '|' not in line:
                continue

            # Parse pipe-delimited cells
            raw_cells = line.split('|')
            if len(raw_cells) < 4:
                continue
            cells = [c.strip() for c in raw_cells[1:-1]]  # strip border pipes

            # Skip separator rows (e.g., |---|---|)
            if all(re.match(r'^[-: ]*$', c) for c in cells if c):
                continue

            # Skip header rows
            if any(kw in c for c in cells[:3] for kw in ('模型', 'Model', 'model', '模式', 'Mode')):
                if not any('元' in c for c in cells):
                    continue

            first_cell = cells[0] if cells else ''

            # Detect model ID in first cell
            maybe_model = _clean_model_id(first_cell)
            if maybe_model:
                current_model = maybe_model

            if not current_model:
                continue

            # Scan all cells for token range and price values
            token_range: Optional[str] = None
            prices: list[float] = []

            for cell in cells:
                if not cell:
                    continue
                if 'Token' in cell or '无阶梯' in cell:
                    token_range = cell
                elif '元' in cell:
                    p = _parse_price(cell)
                    if p is not None:
                        prices.append(p)

            if len(prices) >= 2:
                max_k = _parse_max_k(token_range) if token_range else None
                tier: dict = {
                    "max_k": max_k,
                    "input_price": prices[0],
                    "output_price": prices[1],
                }
                tiers_list = result.setdefault(current_model, [])
                # Avoid duplicates
                exists = any(
                    t["max_k"] == max_k and t["input_price"] == prices[0]
                    for t in tiers_list
                )
                if not exists:
                    tiers_list.append(tier)

    # Sort tiers: bounded first (ascending max_k), unbounded last
    for model_id in result:
        result[model_id].sort(key=lambda t: (t["max_k"] is None, t["max_k"] or 0))

    return result


# ── Cost calculation ───────────────────────────────────────────────────────────

def calc_cost_tiered(
    tokens_in: int,
    tokens_out: int,
    calls: int,
    tiers: list,
) -> float:
    """Calculate cost (CNY) using tiered pricing.

    Alibaba Cloud bills per-request based on input token count. Since we track
    cumulative totals, we estimate the average input tokens per call and use
    that to find the applicable tier. All tokens are then priced at that rate.

    Args:
        tokens_in: total input tokens for the slot
        tokens_out: total output tokens for the slot
        calls: number of LLM calls (used to compute per-call average)
        tiers: list of tier dicts with keys max_k, input_price, output_price

    Returns:
        Estimated cost in CNY, rounded to 4 decimal places.
    """
    if not tiers or not (tokens_in or tokens_out):
        return 0.0

    effective_calls = max(calls, 1)
    avg_input_k = (tokens_in / effective_calls) / 1000  # average input K-tokens per call

    # Find the lowest-bounded tier that covers avg_input_k
    applicable = tiers[-1]  # default: last (highest / unlimited) tier
    for tier in tiers:
        max_k = tier.get("max_k")
        if max_k is None or avg_input_k <= max_k:
            applicable = tier
            break

    cost = (
        tokens_in  / 1_000_000 * applicable["input_price"] +
        tokens_out / 1_000_000 * applicable["output_price"]
    )
    return round(cost, 4)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_model_tiers(db, model_name: str) -> Optional[list]:
    """Load pricing tiers for a model from DB.

    Tries exact match, then strips date-version suffix (e.g. -2026-01-23),
    then strips -latest suffix.

    Returns:
        List of tier dicts if found, else None.
    """
    from server.models import ModelPricing

    key = model_name.lower().strip()

    def _lookup(k: str) -> Optional[list]:
        row = db.query(ModelPricing).filter(ModelPricing.model_id == k).first()
        return row.tiers if row else None

    # 1. Exact match
    tiers = _lookup(key)
    if tiers is not None:
        return tiers

    # 2. Strip date suffix like -2026-01-23
    base = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', key)
    if base != key:
        tiers = _lookup(base)
        if tiers is not None:
            return tiers

    # 3. Strip -latest suffix
    base2 = re.sub(r'-latest$', '', key)
    if base2 != key:
        tiers = _lookup(base2)
        if tiers is not None:
            return tiers

    return None


def recalc_usage_cost(usage: dict, db) -> dict:
    """Recalculate cost fields in a usage dict using current model pricing.

    Modifies a copy of the dict in-place and returns it.
    Falls back to stored cost if no pricing found for the model.
    """
    import copy
    usage = copy.deepcopy(usage)

    total = 0.0
    for slot_key in ("quick", "deep"):
        slot = usage.get(slot_key)
        if not slot:
            continue
        model = slot.get("model", "")
        tiers = get_model_tiers(db, model) if model else None
        if tiers:
            cost = calc_cost_tiered(
                slot.get("tokens_in", 0),
                slot.get("tokens_out", 0),
                slot.get("calls", 1),
                tiers,
            )
            slot["cost_cny"] = cost
        # If no tiers found, keep existing cost_cny
        total += slot.get("cost_cny", 0.0)

    usage["total_cost_cny"] = round(total, 4)
    return usage
