# server/routers/notifications.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.database import get_db
from server.models import Analysis, User
from server.routers.analyses import _visible_filter
from server.schemas import NotificationCount

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/count", response_model=NotificationCount)
def get_notification_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    flt = _visible_filter(current_user)
    unseen = db.query(Analysis).filter(flt, Analysis.seen == False).count()
    return NotificationCount(unseen=unseen)


@router.post("/read", status_code=204)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    flt = _visible_filter(current_user)
    ids = [r.id for r in db.query(Analysis.id).filter(flt, Analysis.seen == False).all()]
    if ids:
        db.query(Analysis).filter(Analysis.id.in_(ids)).update({"seen": True}, synchronize_session=False)
        db.commit()
