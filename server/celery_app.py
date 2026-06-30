# server/celery_app.py
import os
from celery import Celery

# Apply httpx patch BEFORE any httpx imports to handle non-ASCII headers gracefully
from server.httpx_patch import _patched_normalize_header_value  # noqa: F401

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


# ── Reap zombie 'running' rows left over from a previous worker crash ──────────
#
# Celery workers can be SIGKILLed mid-task (deploys, OOM, container restarts).
# Any ScreeningRun / Analysis row pinned at status='running' before the kill is
# now orphaned — no worker will ever complete it. We sweep on worker_ready so
# the frontend's polling UI doesn't show a permanent "进行中…" spinner.
#
# Threshold: older than 30 minutes. A real in-flight task on another worker
# would normally finish within that window; anything older is almost certainly
# a leftover.

from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def _reap_zombie_runs(**_kwargs):
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    try:
        from server.database import SessionLocal
        from server.models import ScreeningRun, Analysis
        with SessionLocal() as db:
            n_screen = (
                db.query(ScreeningRun)
                .filter(ScreeningRun.status == "running",
                        ScreeningRun.created_at < cutoff)
                .update({
                    ScreeningRun.status: "failed",
                    ScreeningRun.error: "Worker 重启导致任务中断，请重新发起。",
                    ScreeningRun.completed_at: datetime.utcnow(),
                }, synchronize_session=False)
            )
            n_anal = (
                db.query(Analysis)
                .filter(Analysis.status == "running",
                        Analysis.created_at < cutoff)
                .update({
                    Analysis.status: "failed",
                    Analysis.error: "Worker 重启导致任务中断，请重新发起。",
                }, synchronize_session=False)
            )
            db.commit()
            if n_screen or n_anal:
                import logging
                logging.getLogger(__name__).warning(
                    "reaped %d zombie screening runs, %d zombie analyses",
                    n_screen, n_anal,
                )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("zombie-run sweep failed")


# Daily A-share screening after market close (Mon-Fri 16:00 CST).
# Requires a Celery beat process: `celery -A server.celery_app beat`.
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    "daily-stock-screening": {
        "task": "server.tasks.scheduled_daily_screening",
        "schedule": crontab(hour=16, minute=0, day_of_week="1-5"),
    },
    # Warm the OHLCV/financials cache overnight so tomorrow's screener run and
    # detail-page views don't pay synchronous TickFlow round-trips.
    "nightly-cache-backfill": {
        "task": "server.tasks.nightly_cache_backfill",
        "schedule": crontab(hour=2, minute=0, day_of_week="1-5"),
    },
}
