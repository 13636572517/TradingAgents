# server/celery_app.py
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "tradingagents",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["server.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Daily A-share screening after market close (Mon-Fri 16:00 CST).
# Requires a Celery beat process: `celery -A server.celery_app beat`.
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    "daily-stock-screening": {
        "task": "server.tasks.scheduled_daily_screening",
        "schedule": crontab(hour=16, minute=0, day_of_week="1-5"),
    },
}
