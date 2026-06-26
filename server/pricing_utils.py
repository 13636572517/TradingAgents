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


def _is_cn_region(cell: str) -> bool:
    """Check if a cell value indicates a China mainland region."""
    return bool(re.search(r'中国内地|华北|华东|华南|中国大陆', cell))


def _extract_table_rows(text: str) -> list[list[str]]:
    """Extract parsed table rows from Markdown text (skips separators and headers)."""
    rows: list[list[str]] = []
    for line in text.split('\n'):
        if '|' not in line:
            continue
        raw_cells = line.split('|')
        if len(raw_cells) < 4:
            continue
        cells = [c.strip() for c in raw_cells[1:-1]]
        if all(re.match(r'^[-: ]*$', c) for c in cells if c):
            continue
        if any(kw in c for c in cells[:3] for kw in ('模型', 'Model', 'model', '模式', 'Mode')):
            if not any('元' in c for c in cells):
                continue
        rows.append(cells)
    return rows


def _parse_rows_to_pricing(rows: list[list[str]]) -> dict[str, list]:
    """Parse table rows into {model_id: [tier, ...]} dict."""
    result: dict[str, list] = {}
    current_model: Optional[str] = None

    for cells in rows:
        first_cell = cells[0] if cells else ''
        maybe_model = _clean_model_id(first_cell)
        if maybe_model:
            current_model = maybe_model
        if not current_model:
            continue

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
            exists = any(
                t["max_k"] == max_k and t["input_price"] == prices[0]
                for t in tiers_list
            )
            if not exists:
                tiers_list.append(tier)

    for model_id in result:
        result[model_id].sort(key=lambda t: (t["max_k"] is None, t["max_k"] or 0))

    return result


def parse_cn_pricing_md(md_text: str) -> dict[str, list]:
    """Parse Alibaba Cloud Bailian pricing Markdown.

    Supports multiple formats:
      1. Legacy: '## 中国内地' section heading → parse that section
      2. New (2025+): per-model tables with '服务部署范围' column containing
         '中国内地' / '华北2' etc. → filter rows by region column
      3. Fallback: no region info at all → parse all rows (user copied
         only the CN table)

    Returns:
        {model_id: [{"max_k": int|None, "input_price": float, "output_price": float}, ...]}
    """
    # Strategy 1: Legacy '## 中国内地' section
    cn_positions = [m.start() for m in re.finditer(r'^## 中国内地', md_text, re.MULTILINE)]
    if cn_positions:
        all_h2 = [m.start() for m in re.finditer(r'^##[^#]', md_text, re.MULTILINE)]
        all_rows: list[list[str]] = []
        for cn_pos in cn_positions:
            next_h2s = [p for p in all_h2 if p > cn_pos]
            section_end = next_h2s[0] if next_h2s else len(md_text)
            all_rows.extend(_extract_table_rows(md_text[cn_pos:section_end]))
        return _parse_rows_to_pricing(all_rows)

    # Strategy 2: Filter rows where a cell matches CN region keywords
    all_rows = _extract_table_rows(md_text)
    if not all_rows:
        return {}

    has_region_col = any(
        any(_is_cn_region(c) or '美国' in c or '新加坡' in c or '德国' in c or '日本' in c
            for c in row)
        for row in all_rows[:20]
    )

    if has_region_col:
        cn_rows = [row for row in all_rows if any(_is_cn_region(c) for c in row)]
        if cn_rows:
            return _parse_rows_to_pricing(cn_rows)

    # Strategy 3: No region info — treat all rows as CN
    return _parse_rows_to_pricing(all_rows)


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
    Falls back to global AppSettings pricing if no tiered pricing found for the model.
    """
    import copy
    from server.models import AppSettings

    usage = copy.deepcopy(usage)

    # Load global pricing fallback from AppSettings
    app_cfg = db.query(AppSettings).first()
    global_input = (app_cfg.input_cost_per_million if app_cfg else 0.0) or 0.0
    global_output = (app_cfg.output_cost_per_million if app_cfg else 0.0) or 0.0

    total = 0.0
    for slot_key in ("quick", "deep"):
        slot = usage.get(slot_key)
        if not slot:
            continue
        model = slot.get("model", "")
        tiers = get_model_tiers(db, model) if model else None

        if tiers:
            # Use tiered pricing
            cost = calc_cost_tiered(
                slot.get("tokens_in", 0),
                slot.get("tokens_out", 0),
                slot.get("calls", 1),
                tiers,
            )
        elif global_input > 0 or global_output > 0:
            # Fallback to global flat-rate pricing
            cost = (
                slot.get("tokens_in", 0) / 1_000_000 * global_input +
                slot.get("tokens_out", 0) / 1_000_000 * global_output
            )
            cost = round(cost, 4)
        else:
            # No pricing available — keep existing or set to 0
            cost = slot.get("cost_cny", 0.0)

        slot["cost_cny"] = cost
        total += cost

    usage["total_cost_cny"] = round(total, 4)
    return usage
