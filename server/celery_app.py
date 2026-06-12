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


# ── Re-hydrate DB-stored API keys into process environment ─────────────────────

def _hydrate_db_keys():
    """Load TickFlow (and future) API keys from DB into env vars.

    Celery workers run in a separate process from the uvicorn server,
    so they don't inherit the server's startup event. We hydrate keys
    here so screening tasks can authenticate with TickFlow.
    """
    if "TICKFLOW_API_KEY" in os.environ and os.environ["TICKFLOW_API_KEY"]:
        return  # already set (e.g. via docker-compose env_file)
    try:
        from server.database import SessionLocal
        from server.models import AppSettings
        with SessionLocal() as db:
            row = db.get(AppSettings, 1)
            if row and row.tickflow_api_key:
                os.environ["TICKFLOW_API_KEY"] = row.tickflow_api_key
    except Exception:
        pass  # non-critical; screening will degrade to akshare/joinquant


_hydrate_db_keys()


# Daily A-share screening after market close (Mon-Fri 16:00 CST).
# Requires a Celery beat process: `celery -A server.celery_app beat`.
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    "daily-stock-screening": {
        "task": "server.tasks.scheduled_daily_screening",
        "schedule": crontab(hour=16, minute=0, day_of_week="1-5"),
    },
}
