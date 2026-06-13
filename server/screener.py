"""A-share stock-screening engine.

Pipeline:
  1. Scan all industry boards (SW1 一级 + SW2 二级), aggregate constituent valuations.
  2. Persist a daily SectorSnapshot per board (builds a self time-series).
  3. Compute each board's PE & PB percentile (historical or cross-section).
  4. Score ALL constituents with a composite leader score.
  5. Return top-N leaders per board.

Supports two tab views in the frontend:
  - SW1 (申万一级, ~31 industries)
  - SW2 (申万二级, ~130 sub-industries)
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
    "valuation_threshold_pct": 30.0,
    "min_history_points": 20,
    "leaders_per_board": 5,
    "min_amount_cny": 5e7,
    "min_member_count": 5,
    "w_mktcap": 0.40,
    "w_liquidity": 0.25,
    "w_roe": 0.20,
    "w_inflow": 0.15,
}


def _median(values: list[float]) -> Optional[float]:
    vals = [v for v in values if v is not None and v > 0]
    if not vals:
        return None
    return float(statistics.median(vals))


def _percentile_rank(value: float, population: list[float]) -> Optional[float]:
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

def compute_board_valuations(spot: dict, level: int = 1) -> list[dict]:
    """For every industry board at the given SW level, compute median PE/PB."""
    boards = sd.get_industry_boards(level=level)
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
            "code": b.get("code", b["name"]),
            "level": level,
            "pe": pe_med,
            "pb": pb_med,
            "total_mktcap": b.get("total_mktcap"),
            "pct_change": b.get("pct_change"),
            "turnover": b.get("turnover"),
            "member_count": len(codes),
        })
    return results


def persist_snapshots(db: Session, run_date: str, board_vals: list[dict]) -> None:
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


# ── Step 3: percentiles + undervalued ──────────────────────────────────────────────

def _board_history(db: Session, board_name: str, field: str, before_date: str) -> list[float]:
    rows = (
        db.query(SectorSnapshot)
        .filter(SectorSnapshot.board_name == board_name,
                SectorSnapshot.date < before_date)
        .all()
    )
    return [getattr(r, field) for r in rows if getattr(r, field) is not None]


def annotate_boards(db: Session, run_date: str, board_vals: list[dict],
                    params: dict) -> list[dict]:
    """Annotate boards with PE/PB percentiles. Returns same list with extra fields."""
    threshold = params["valuation_threshold_pct"]
    min_hist = params["min_history_points"]

    pe_pop = [b["pe"] for b in board_vals if b.get("pe")]
    pb_pop = [b["pb"] for b in board_vals if b.get("pb")]

    for b in board_vals:
        if (b.get("member_count") or 0) < params["min_member_count"]:
            b["pe_pct"] = None
            b["pb_pct"] = None
            b["valuation_method"] = None
            b["is_undervalued"] = False
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
        b["is_undervalued"] = (
            pe_pct is not None and pb_pct is not None
            and pe_pct < threshold and pb_pct < threshold
        )

    return board_vals


# ── Step 4: leader scoring ─────────────────────────────────────────────────────────

def score_leaders(board: dict, spot: dict, roe_map: dict, flow_map: dict,
                  params: dict) -> list[dict]:
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
    return top


# ── Orchestration ───────────────────────────────────────────────────────────────────

def run_screening(db: Session, params: Optional[dict] = None,
                  progress: Optional[callable] = None) -> dict:
    def _p(msg: str):
        if progress: progress(msg)
        logger.info("[screener] %s", msg)

    p = {**DEFAULT_PARAMS, **(params or {})}
    run_date = datetime.now().strftime("%Y-%m-%d")

    # Step 1: market snapshot
    _p("Step 1/4 — 获取全市场行情快照…")
    spot = sd.get_market_spot()
    if not spot:
        raise RuntimeError("全市场行情快照获取失败")
    _p(f"Step 1/4 — 行情快照获取完成（{len(spot)} 只股票）")

    # Step 2: scan boards for BOTH levels
    _p("Step 2/4 — 扫描 SW1 申万一级行业（~31个）…")
    sw1_boards = compute_board_valuations(spot, level=1)
    annotate_boards(db, run_date, sw1_boards, p)
    persist_snapshots(db, run_date, sw1_boards)
    _p(f"Step 2/4 — SW1 扫描完成，{len(sw1_boards)} 个板块")

    _p("Step 3/4 — 扫描 SW2 申万二级行业（~130个）…")
    sw2_boards = compute_board_valuations(spot, level=2)
    annotate_boards(db, run_date, sw2_boards, p)
    persist_snapshots(db, run_date, sw2_boards)
    _p(f"Step 3/4 — SW2 扫描完成，{len(sw2_boards)} 个板块")

    # Step 4: score leaders for ALL boards (both levels)
    _p("Step 4/4 — 计算各板块龙头评分…")
    roe_map = sd.get_roe_map()
    flow_map = sd.get_moneyflow_map()

    all_boards_data = []
    candidates = []

    for level, boards in [(1, sw1_boards), (2, sw2_boards)]:
        for b in boards:
            leaders = score_leaders(b, spot, roe_map, flow_map, p)
            for ld in leaders:
                candidates.append({
                    "board_name": b["name"],
                    "board_level": level,
                    "board_pe_pct": b.get("pe_pct"),
                    "board_pb_pct": b.get("pb_pct"),
                    "board_valuation_method": b.get("valuation_method"),
                    **ld,
                })

            all_boards_data.append({
                "name": b["name"],
                "level": level,
                "pe": b.get("pe"),
                "pb": b.get("pb"),
                "pe_pct": b.get("pe_pct"),
                "pb_pct": b.get("pb_pct"),
                "is_undervalued": b.get("is_undervalued", False),
                "valuation_method": b.get("valuation_method"),
                "pct_change": b.get("pct_change"),
                "member_count": b.get("member_count"),
            })

    sw1_undervalued = sum(1 for b in sw1_boards if b.get("is_undervalued"))
    sw2_undervalued = sum(1 for b in sw2_boards if b.get("is_undervalued"))
    _p(f"Step 4/4 — 龙头评分完成，共 {len(candidates)} 只候选股")

    summary = {
        "boards_scanned": len(sw1_boards) + len(sw2_boards),
        "sw1_count": len(sw1_boards),
        "sw2_count": len(sw2_boards),
        "sw1_undervalued": sw1_undervalued,
        "sw2_undervalued": sw2_undervalued,
        "candidate_count": len(candidates),
        "roe_available": bool(roe_map),
        "moneyflow_available": bool(flow_map),
        "all_boards": all_boards_data,
    }
    return {
        "run_date": run_date,
        "params": p,
        "candidates": candidates,
        "summary": summary,
    }
