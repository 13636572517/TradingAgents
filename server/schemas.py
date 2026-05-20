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

    model_config = {"from_attributes": True}


class AnalysisListOut(BaseModel):
    items: List[AnalysisOut]
    total: int


class NotificationCount(BaseModel):
    unseen: int
