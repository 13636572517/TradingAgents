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
    created_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    seen         = Column(Boolean, default=True)         # False triggers sidebar badge
