# server/models.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
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
    stage_detail = Column(Text)                          # human-readable current activity
    usage          = Column(JSON)                        # {quick:{calls,tokens_in,...}, deep:{...}, total_cost_cny}
    celery_task_id = Column(Text)                        # Celery task ID for revoke/stop
    created_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    seen         = Column(Boolean, default=True)         # False triggers sidebar badge
    owner_id     = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)


class AnalysisShare(Base):
    """Tracks which users a report has been shared with."""
    __tablename__ = "analysis_shares"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id         = Column(String(36), ForeignKey('analyses.id', ondelete='CASCADE'), nullable=False, index=True)
    shared_with_user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at          = Column(DateTime, default=datetime.utcnow)


class AppSettings(Base):
    """Single-row application settings table. Row id is always 1."""
    __tablename__ = "app_settings"

    id              = Column(Integer, primary_key=True, default=1)
    provider        = Column(String(30), default="qwen-cn")
    api_key         = Column(Text)                          # stored as-is; never sent to frontend
    deep_model      = Column(String(100), default="qwen3.6-plus")
    quick_model     = Column(String(100), default="qwen3.6-flash")
    backend_url     = Column(Text)                          # optional proxy / custom endpoint
    max_api_calls   = Column(Integer, default=60)           # per-run API call limit guard
    # Cost per 1M tokens (CNY) — user-configurable, used for cost estimation
    input_cost_per_million  = Column(Float, default=0.0)    # CNY per 1M input tokens
    output_cost_per_million = Column(Float, default=0.0)    # CNY per 1M output tokens
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisStrategy(Base):
    """One strategy record per completed analysis (extracted from final_trade_decision)."""
    __tablename__ = "analysis_strategies"

    id              = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id     = Column(String(36), ForeignKey('analyses.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    ticker          = Column(String(20),  nullable=False, index=True)
    ticker_name     = Column(String(100))
    trade_date      = Column(String(10))               # YYYY-MM-DD
    direction       = Column(String(10))               # BUY / HOLD / SELL
    entry_price     = Column(Float)                    # closing price on trade_date
    stop_loss       = Column(Float)
    target_price    = Column(Float)
    position_size   = Column(String(50))               # e.g. "20-30%"
    time_horizon    = Column(String(100))              # e.g. "1-3个月"
    current_price   = Column(Float)
    price_updated_at = Column(DateTime)
    status          = Column(String(20), default="active")  # active / expired / closed
    # AI extraction metadata
    extraction_method  = Column(String(10), default="regex")   # regex / ai
    confidence         = Column(String(10))                    # high / medium / low
    stop_loss_basis    = Column(String(50))                    # 绝对价格/百分比换算/均线支撑/…
    target_price_basis = Column(String(50))
    extraction_note    = Column(Text)                          # AI explanation
    created_at      = Column(DateTime,   default=datetime.utcnow)
    closed_at       = Column(DateTime)


class ModelPricing(Base):
    """Per-model tiered pricing imported from provider pricing table (e.g. Alibaba Cloud Bailian)."""
    __tablename__ = "model_pricing"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    model_id   = Column(String(100), nullable=False, unique=True, index=True)
    region     = Column(String(20), default="cn")
    tiers      = Column(JSON, nullable=False)
    # tiers format (sorted by max_k asc, last entry has max_k=null = unlimited):
    # [{"max_k": 32, "input_price": 2.5, "output_price": 10.0}, ...]
    # max_k unit: thousands of tokens (32 → 32K)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    """认证用户。密码以 bcrypt 哈希存储，不可逆。"""
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    username         = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password  = Column(String(255), nullable=False)
    is_active        = Column(Boolean, default=True, nullable=False)
    is_admin         = Column(Boolean, default=False, nullable=False, server_default="0")
    created_at       = Column(DateTime, default=datetime.utcnow)
