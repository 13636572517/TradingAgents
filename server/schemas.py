# server/schemas.py
from __future__ import annotations
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel


class AnalysisCreate(BaseModel):
    ticker: str
    trade_date: str          # YYYY-MM-DD
    analysts: List[str]      # ["fundamentals", "sentiment", "news", "market"]
    depth: int = 1           # 1=fast 2=standard 3=deep


class AnalysisOut(BaseModel):
    id: str
    ticker: str
    ticker_name: Optional[str]
    trade_date: str
    analysts: List[str]
    depth: int
    status: str
    stage: str
    result: Optional[Any]
    decision: Optional[str]
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    seen: bool
    stage_detail: Optional[str] = None
    usage: Optional[Any] = None

    model_config = {"from_attributes": True}


class AnalysisListOut(BaseModel):
    items: List[AnalysisOut]
    total: int


class NotificationCount(BaseModel):
    unseen: int


class SettingsUpdate(BaseModel):
    provider: str
    api_key: Optional[str] = None      # None means "keep existing"
    deep_model: str
    quick_model: str
    backend_url: Optional[str] = None
    max_api_calls: int = 60
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


class SettingsOut(BaseModel):
    provider: str
    deep_model: str
    quick_model: str
    backend_url: Optional[str]
    has_api_key: bool                  # true if key is stored, never expose the key itself
    max_api_calls: int = 60
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    model_config = {"from_attributes": True}


# ── Stock screener ───────────────────────────────────────────────────────────────

class ScreeningRunCreate(BaseModel):
    auto_analyze: bool = False         # auto-launch deep analysis on top candidates
    auto_analyze_top: int = 3
    depth: int = 1
    params: Optional[Any] = None       # override DEFAULT_PARAMS in screener


class ScreeningCandidateOut(BaseModel):
    id: str
    run_id: str
    board_name: str
    board_pe_pct: Optional[float]
    board_pb_pct: Optional[float]
    board_valuation_method: Optional[str]
    code: Optional[str]
    ticker: str
    ticker_name: Optional[str]
    price: Optional[float]
    pct_change: Optional[float]
    total_mktcap: Optional[float]
    pe: Optional[float]
    pb: Optional[float]
    roe: Optional[float]
    amount: Optional[float]
    net_inflow: Optional[float]
    rank_in_board: Optional[int]
    score: Optional[float]
    reason: Optional[str]
    analysis_id: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ScreeningRunOut(BaseModel):
    id: str
    run_date: str
    status: str
    trigger: str
    params: Optional[Any]
    summary: Optional[Any]
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ScreeningRunDetailOut(ScreeningRunOut):
    candidates: List[ScreeningCandidateOut] = []
