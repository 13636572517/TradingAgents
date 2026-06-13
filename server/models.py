# server/models.py
import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from server.database import Base


class TickerSettings(Base):
    __tablename__ = "ticker_settings"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    owner_id   = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    ticker     = Column(String(20), nullable=False)
    cost_price = Column(Float, nullable=True)    # user's manual entry price
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    tickflow_api_key = Column(Text)                         # TickFlow market-data API key (x-api-key)
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


class SectorSnapshot(Base):
    """Daily valuation snapshot of one industry board — builds a self-time-series
    so we can compute historical PE/PB percentiles over time."""
    __tablename__ = "sector_snapshots"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    date         = Column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    board_name   = Column(String(50), nullable=False, index=True)
    board_code   = Column(String(20))
    pe           = Column(Float)        # median dynamic PE of constituents
    pb           = Column(Float)        # median PB of constituents
    total_mktcap = Column(Float)        # board total market cap (CNY)
    pct_change   = Column(Float)        # board daily % change
    turnover     = Column(Float)        # board turnover rate
    member_count = Column(Integer)
    created_at   = Column(DateTime, default=datetime.utcnow)


class StockOHLCV(Base):
    """Daily OHLCV cache. Historical bars are immutable, so we upsert by
    (symbol, date, adjust) and incrementally fetch only (max_cached_date, today]
    instead of refetching whole histories on every analysis."""
    __tablename__ = "stock_ohlcv"

    symbol   = Column(String(20), primary_key=True)   # TickFlow format, e.g. 600519.SH
    date     = Column(String(10), primary_key=True)   # YYYY-MM-DD
    adjust   = Column(String(10), primary_key=True, default="forward")  # forward / none
    open     = Column(Float)
    high     = Column(Float)
    low      = Column(Float)
    close    = Column(Float)
    volume   = Column(Float)
    amount   = Column(Float)
    prev_close = Column(Float)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class StockFinancials(Base):
    """Quarterly financial statement cache. A given (symbol, period_end,
    statement) is reported once and never restated, so we only fetch periods
    after the latest cached one and append."""
    __tablename__ = "stock_financials"

    symbol     = Column(String(20), primary_key=True)   # TickFlow format
    period_end = Column(String(10), primary_key=True)   # YYYY-MM-DD fiscal quarter end
    statement  = Column(String(20), primary_key=True)   # balance | income | cashflow | metrics
    data       = Column(JSON)                           # full record from TickFlow as-is
    fetched_at = Column(DateTime, default=datetime.utcnow)


class Instrument(Base):
    """Share-structure metadata (total/float shares, name) per A-share code.

    Changes only on placements, buybacks, or renames — fetched from TickFlow
    ``POST /v1/instruments`` and refreshed only when stale (see
    ``cache_store.get_stale_instrument_codes``)."""
    __tablename__ = "instruments"

    symbol       = Column(String(6), primary_key=True)   # 6-digit A-share code
    name         = Column(String(100))
    total_shares = Column(Float)
    float_shares = Column(Float)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IndustryBoard(Base):
    """Shenwan industry board definitions (SW1/SW2), discovered from TickFlow
    ``/v1/universes``. Reclassified roughly once a year."""
    __tablename__ = "industry_boards"

    level        = Column(Integer, primary_key=True)   # 1 = SW1, 2 = SW2
    name         = Column(String(50), primary_key=True)
    universe_ids = Column(JSON)         # list of TickFlow universe ids that make up this board
    symbol_count = Column(Integer)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BoardConstituent(Base):
    """Constituent stock codes for a Shenwan board (one row per board)."""
    __tablename__ = "board_constituents"

    level      = Column(Integer, primary_key=True)
    board_name = Column(String(50), primary_key=True)
    codes      = Column(JSON)          # list of 6-digit codes
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScreeningRun(Base):
    """One execution of the stock-screening pipeline."""
    __tablename__ = "screening_runs"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_date    = Column(String(10), nullable=False, index=True)    # YYYY-MM-DD
    status      = Column(String(20), default="running")             # running|complete|failed
    trigger     = Column(String(20), default="manual")              # manual|scheduled
    params      = Column(JSON)          # screening parameters snapshot
    summary     = Column(JSON)          # {boards_scanned, undervalued_count, candidate_count, ...}
    error       = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    owner_id    = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)


class ScreeningCandidate(Base):
    """A leading stock picked from an undervalued sector during a screening run."""
    __tablename__ = "screening_candidates"

    id              = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id          = Column(String(36), ForeignKey('screening_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    board_name      = Column(String(50), nullable=False)
    board_level     = Column(Integer, default=1)            # 1=SW1一级, 2=SW2二级
    board_pe_pct    = Column(Float)     # board PE percentile (0-100)
    board_pb_pct    = Column(Float)     # board PB percentile (0-100)
    board_valuation_method = Column(String(20))  # historical|cross_section
    code            = Column(String(6))            # 6-digit A-share code
    ticker          = Column(String(20), nullable=False)   # YF format e.g. 600519.SS
    ticker_name     = Column(String(100))
    price           = Column(Float)     # 现价
    pct_change      = Column(Float)     # 涨跌幅 %
    total_mktcap    = Column(Float)
    pe              = Column(Float)
    pb              = Column(Float)
    roe             = Column(Float)
    amount          = Column(Float)     # 成交额 (liquidity)
    net_inflow      = Column(Float)     # 主力净流入
    net_profit_yoy  = Column(Float)     # 净利润同比增速 (%)
    debt_ratio      = Column(Float)     # 资产负债率 (%)
    gross_margin    = Column(Float)     # 毛利率 (%)
    ocf_to_revenue  = Column(Float)     # 经营现金流/营收 (%)
    eps_ttm         = Column(Float)     # 滚动每股收益 (Graham Number 计算用)
    bps             = Column(Float)     # 每股净资产 (Graham Number 计算用)
    rank_in_board   = Column(Integer)   # 1 = top leader
    score           = Column(Float)     # composite leader score (0-100)
    reason          = Column(Text)      # human-readable selection rationale
    analysis_id     = Column(String(36), ForeignKey('analyses.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at      = Column(DateTime, default=datetime.utcnow)


class User(Base):
    """认证用户。密码以 bcrypt 哈希存储，不可逆。"""
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    username         = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password  = Column(String(255), nullable=False)
    is_active        = Column(Boolean, default=True, nullable=False)
    is_admin         = Column(Boolean, default=False, nullable=False, server_default="0")
    created_at       = Column(DateTime, default=datetime.utcnow)
