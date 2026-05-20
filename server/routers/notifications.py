# server/routers/notifications.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis
from server.schemas import NotificationCount

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/count", response_model=NotificationCount)
def get_notification_count(db: Session = Depends(get_db)):
    unseen = db.query(Analysis).filter(Analysis.seen == False).count()
    return NotificationCount(unseen=unseen)


@router.post("/read", status_code=204)
def mark_all_read(db: Session = Depends(get_db)):
    db.query(Analysis).filter(Analysis.seen == False).update({"seen": True})
    db.commit()
