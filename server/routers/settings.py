# server/routers/settings.py
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import AppSettings
from server.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _get_or_create(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    row = _get_or_create(db)
    return SettingsOut(
        provider=row.provider or "qwen-cn",
        deep_model=row.deep_model or "qwen3.6-plus",
        quick_model=row.quick_model or "qwen3.6-flash",
        backend_url=row.backend_url,
        has_api_key=bool(row.api_key),
    )


@router.post("", response_model=SettingsOut)
def save_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    row = _get_or_create(db)
    row.provider = payload.provider
    row.deep_model = payload.deep_model
    row.quick_model = payload.quick_model
    row.backend_url = payload.backend_url or None
    row.updated_at = datetime.utcnow()
    if payload.api_key:          # only update key if a new one was provided
        row.api_key = payload.api_key
    db.commit()
    db.refresh(row)
    return SettingsOut(
        provider=row.provider,
        deep_model=row.deep_model,
        quick_model=row.quick_model,
        backend_url=row.backend_url,
        has_api_key=bool(row.api_key),
    )
