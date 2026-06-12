"""A-share stock-screening engine.

Pipeline:
  1. Scan all industry boards, aggregate constituent valuations (median PE / PB).
  2. Persist a daily SectorSnapshot per board (builds a self time-series).
  3. Compute each board's PE & PB percentile:
       - historical : percentile within this board's own snapshot history (preferred,
                       used once we have >= MIN_HISTORY data points)
       - cross_section : percentile across ALL boards today (bootstrap fallback)
     A board is "undervalued" when PE percentile < THRESHOLD and PB percentile < THRESHOLD.
  4. Within each undervalued board, score constituents with a composite leader score:
       market cap (40%) + liquidity/成交额 (25%) + ROE (20%) + 主力净流入 (15%),
     each min-max normalised within the board. Drop ST / illiquid names.
  5. Return top-N leaders per board as candidates.

All numeric inputs come from cached AkShare snapshots (see dataflows/sector_data.py),
so a full run issues only a handful of network calls regardless of universe size.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from server.models import SectorSnapshot
from tradingagents.dataflows import sector_data as sd

logger = logging.getLogger(__name__)

# ── Tunable parameters ───────────────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "valuation_threshold_pct": 30.0,   # PE & PB percentile must be below this
    "min_history_points": 20,          # min snapshots before using historical percentile
    "max_undervalued_boards": 8,       # cap on undervalued boards reported
    "leaders_per_board": 5,            # top-N leaders per board
    "min_amount_cny": 5e7,             # liquidity floor: 成交额 >= 50M CNY
    "min_member_count": 5,             # ignore tiny boards
    # leader score weights (sum need not be 1; normalised internally)
    "w_mktcap": 0.40,
    "w_liquidity": 0.25,
    "w_roe": 0.20,
    "w_inflow": 0.15,
}


# ── Helpers ───────────────────────────────────────────────────────────────────────

def _median(values: list[float]) -> Optional[float]:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return float(statistics.median(vals))


def _percentile_rank(value: float, population: list[float]) -> Optional[float]:
    """Return the percentile (0-100) of `value` within `population` (lower = cheaper)."""
    pop = [p for p in population if p is not None]
    if value is None or not pop:
        return None
    below = sum(1 for p in pop if p < value)
    equal = sum(1 for p in pop if p == value)
    return round((below + 0.5 * equal) / len(pop) * 100, 1)


def _minmax(value: Optional[float], lo: float, hi: float) -> float:
    if value is None or hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


# ── Step 1-2: board valuation + snapshot ───────────────────────────────────────────

def compute_board_valuations(spot: dict) -> list[dict]:
    """For every industry board compute median PE/PB from its constituents.

    Returns list of dicts:
      {name, code, pe, pb, total_mktcap, pct_change, turnover, member_count}
    """
    boards = sd.get_industry_boards()
    results: list[dict] = []
    for b in boards:
        codes = sd.get_board_constituents(b["name"])
        if not codes:
            continue
        pes, pbs = [], []
        for code in codes:
            row = spot.get(code)
            if not row:
                continue
            pes.append(row.get("pe"))
            pbs.append(row.get("pb"))
        pe_med = _median(pes)
        pb_med = _median(pbs)
        if pe_med is None and pb_med is None:
            continue
        results.append({
            "name": b["name"],
            "code": b["code"],
            "pe": pe_med,
            "pb": pb_med,
            "total_mktcap": b.get("total_mktcap"),
            "pct_change": b.get("pct_change"),
            "turnover": b.get("turnover"),
            "member_count": len(codes),
        })
    return results


def persist_snapshots(db: Session, run_date: str, board_vals: list[dict]) -> None:
    """Write one SectorSnapshot per board for run_date (idempotent per date)."""
    existing = {
        s.board_name for s in db.query(SectorSnapshot.board_name)
        .filter(SectorSnapshot.date == run_date).all()
    }
    for bv in board_vals:
        if bv["name"] in existing:
            continue
        db.add(SectorSnapshot(
            date=run_date,
            board_name=bv["name"],
            board_code=bv.get("code"),
            pe=bv.get("pe"),
            pb=bv.get("pb"),
            total_mktcap=bv.get("total_mktcap"),
            pct_change=bv.get("pct_change"),
            turnover=bv.get("turnover"),
            member_count=bv.get("member_count"),
        ))
    db.commit()


# ── Step 3: percentiles + undervalued selection ────────────────────────────────────

def _board_history(db: Session, board_name: str, field: str, before_date: str) -> list[float]:
    rows = (
        db.query(SectorSnapshot)
        .filter(SectorSnapshot.board_name == board_name,
                SectorSnapshot.date < before_date)
        .all()
    )
    return [getattr(r, field) for r in rows if getattr(r, field) is not None]


def select_undervalued_boards(db: Session, run_date: str, board_vals: list[dict],
                              params: dict) -> list[dict]:
    """Annotate boards with PE/PB percentiles and return those that pass the threshold."""
    threshold = params["valuation_threshold_pct"]
    min_hist = params["min_history_points"]

    # Cross-sectional populations (today, all boards)
    pe_pop = [b["pe"] for b in board_vals if b.get("pe")]
    pb_pop = [b["pb"] for b in board_vals if b.get("pb")]

    undervalued: list[dict] = []
    for b in board_vals:
        if (b.get("member_count") or 0) < params["min_member_count"]:
            continue

        pe_hist = _board_history(db, b["name"], "pe", run_date)
        pb_hist = _board_history(db, b["name"], "pb", run_date)
        use_hist = len(pe_hist) >= min_hist and len(pb_hist) >= min_hist

        if use_hist:
            method = "historical"
            pe_pct = _percentile_rank(b.get("pe"), pe_hist)
            pb_pct = _percentile_rank(b.get("pb"), pb_hist)
        else:
            method = "cross_section"
            pe_pct = _percentile_rank(b.get("pe"), pe_pop)
            pb_pct = _percentile_rank(b.get("pb"), pb_pop)

        b["pe_pct"] = pe_pct
        b["pb_pct"] = pb_pct
        b["valuation_method"] = method

        if pe_pct is not None and pb_pct is not None and pe_pct < threshold and pb_pct < threshold:
            undervalued.append(b)

    # Cheapest first (by combined percentile)
    undervalued.sort(key=lambda x: (x.get("pe_pct", 100) + x.get("pb_pct", 100)))
    return undervalued[: params["max_undervalued_boards"]]


# ── Step 4: leader scoring within a board ───────────────────────────────────────────

def score_leaders(board: dict, spot: dict, roe_map: dict, flow_map: dict,
                  params: dict) -> list[dict]:
    """Rank constituents of one board by composite leader score; return top-N."""
    codes = sd.get_board_constituents(board["name"])
    rows: list[dict] = []
    for code in codes:
        s = spot.get(code)
        if not s:
            continue
        if not sd.is_tradeable(s.get("name", "")):
            continue
        if (s.get("amount") or 0) < params["min_amount_cny"]:
            continue
        rows.append({
            "code": code,
            "ticker": sd.code_to_yf(code),
            "name": s.get("name"),
            "total_mktcap": s.get("total_mktcap"),
            "pe": s.get("pe"),
            "pb": s.get("pb"),
            "amount": s.get("amount"),
            "roe": roe_map.get(code),
            "net_inflow": flow_map.get(code),
        })
    if not rows:
        return []

    # Normalisation bounds per factor (within this board)
    def _bounds(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return (min(vals), max(vals)) if vals else (0.0, 0.0)

    mc_lo, mc_hi = _bounds("total_mktcap")
    amt_lo, amt_hi = _bounds("amount")
    roe_lo, roe_hi = _bounds("roe")
    flow_lo, flow_hi = _bounds("net_inflow")

    wsum = params["w_mktcap"] + params["w_liquidity"] + params["w_roe"] + params["w_inflow"]
    for r in rows:
        s_mc = _minmax(r.get("total_mktcap"), mc_lo, mc_hi)
        s_amt = _minmax(r.get("amount"), amt_lo, amt_hi)
        s_roe = _minmax(r.get("roe"), roe_lo, roe_hi)
        s_flow = _minmax(r.get("net_inflow"), flow_lo, flow_hi)
        raw = (params["w_mktcap"] * s_mc + params["w_liquidity"] * s_amt
               + params["w_roe"] * s_roe + params["w_inflow"] * s_flow)
        r["score"] = round(raw / wsum * 100, 1) if wsum else 0.0

    rows.sort(key=lambda x: x["score"], reverse=True)
    top = rows[: params["leaders_per_board"]]
    for i, r in enumerate(top, start=1):
        r["rank_in_board"] = i
        r["reason"] = _build_reason(board, r)
    return top


def _fmt_yi(v: Optional[float]) -> str:
    """Format a CNY amount into 亿 units."""
    if v is None:
        return "—"
    return f"{v / 1e8:.1f}亿"


def _build_reason(board: dict, r: dict) -> str:
    parts = [
        f"{board['name']}板块估值偏低(PE分位{board.get('pe_pct')}% / PB分位{board.get('pb_pct')}%)",
        f"市值{_fmt_yi(r.get('total_mktcap'))}",
    ]
    if r.get("roe") is not None:
        parts.append(f"ROE {r['roe']:.1f}%")
    if r.get("net_inflow") is not None:
        sign = "净流入" if r["net_inflow"] >= 0 else "净流出"
        parts.append(f"主力{sign}{_fmt_yi(abs(r['net_inflow']))}")
    parts.append(f"板块内龙头排名第{r.get('rank_in_board')}")
    return "，".join(parts) + "。"


# ── Orchestration ───────────────────────────────────────────────────────────────────

def run_screening(db: Session, params: Optional[dict] = None) -> dict:
    """Execute the full screening pipeline. Returns a dict:
       {run_date, params, board_valuations, undervalued, candidates, summary}
    Does NOT persist a ScreeningRun row — callers (router/task) handle persistence.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    run_date = datetime.now().strftime("%Y-%m-%d")

    spot = sd.get_market_spot()
    if not spot:
        raise RuntimeError("全市场行情快照获取失败 (akshare stock_zh_a_spot_em)")

    board_vals = compute_board_valuations(spot)
    persist_snapshots(db, run_date, board_vals)

    undervalued = select_undervalued_boards(db, run_date, board_vals, p)

    roe_map = sd.get_roe_map()
    flow_map = sd.get_moneyflow_map()

    candidates: list[dict] = []
    for board in undervalued:
        leaders = score_leaders(board, spot, roe_map, flow_map, p)
        for ld in leaders:
            candidates.append({
                "board_name": board["name"],
                "board_pe_pct": board.get("pe_pct"),
                "board_pb_pct": board.get("pb_pct"),
                "board_valuation_method": board.get("valuation_method"),
                **ld,
            })

    summary = {
        "boards_scanned": len(board_vals),
        "undervalued_count": len(undervalued),
        "candidate_count": len(candidates),
        "roe_available": bool(roe_map),
        "moneyflow_available": bool(flow_map),
    }
    return {
        "run_date": run_date,
        "params": p,
        "board_valuations": board_vals,
        "undervalued": undervalued,
        "candidates": candidates,
        "summary": summary,
    }
