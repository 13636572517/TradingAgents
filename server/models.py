# server/models.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, JSON
from server.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticker       = Column(String(20), nullable=False)
    ticker_name  = Column(String(100))
    trade_date   = Column(String(10), nullable=False)   # YYYY-MM-DD
    analysts     = Column(JSON, nullable=False)          # e.g. ["fundamentals","sentiment"]
    depth        = Column(Integer, default=1)            # 1=fast 2=standard 3=deep
    status       = Column(String(20), default="pending") # pending|running|complete|failed
    stage        = Column(String(30), default="pending") # analysts|debate|risk|decision|complete
    result       = Column(JSON)                          # all analyst reports + final decision
    decision     = Column(String(10))                    # BUY|HOLD|SELL
    error        = Column(Text)
    llm_config   = Column(JSON)                          # snapshot of LLM settings at submit time
    created_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    seen         = Column(Boolean, default=True)         # False triggers sidebar badge


class AppSettings(Base):
    """Single-row application settings table. Row id is always 1."""
    __tablename__ = "app_settings"

    id           = Column(Integer, primary_key=True, default=1)
    provider     = Column(String(30), default="qwen-cn")
    api_key      = Column(Text)                          # stored as-is; never sent to frontend
    deep_model   = Column(String(100), default="qwen3.6-plus")
    quick_model  = Column(String(100), default="qwen3.6-flash")
    backend_url  = Column(Text)                          # optional proxy / custom endpoint
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
