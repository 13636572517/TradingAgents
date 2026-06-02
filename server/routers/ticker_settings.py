# server/routers/ticker_settings.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from server.database import get_db
from server.auth import get_current_user
from server.models import TickerSettings, User

router = APIRouter(prefix="/api/ticker-settings", tags=["ticker-settings"])


class TickerSettingsOut(BaseModel):
    ticker: str
    cost_price: Optional[float]

    class Config:
        from_attributes = True


class TickerSettingsIn(BaseModel):
    cost_price: Optional[float]


@router.get("/{ticker}", response_model=TickerSettingsOut)
def get_ticker_settings(
    ticker: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(TickerSettings).filter(
        TickerSettings.owner_id == current_user.id,
        TickerSettings.ticker == ticker,
    ).first()
    return TickerSettingsOut(ticker=ticker, cost_price=row.cost_price if row else None)


@router.put("/{ticker}", response_model=TickerSettingsOut)
def set_ticker_settings(
    ticker: str,
    payload: TickerSettingsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(TickerSettings).filter(
        TickerSettings.owner_id == current_user.id,
        TickerSettings.ticker == ticker,
    ).first()
    if row:
        row.cost_price = payload.cost_price
    else:
        row = TickerSettings(owner_id=current_user.id, ticker=ticker, cost_price=payload.cost_price)
        db.add(row)
    db.commit()
    return TickerSettingsOut(ticker=ticker, cost_price=row.cost_price)
