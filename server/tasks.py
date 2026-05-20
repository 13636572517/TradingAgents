# server/tasks.py  (STUB — replaced in Task 3)
import logging
logger = logging.getLogger(__name__)

class _NoOpTask:
    """Stub task that no-ops .delay() when Celery isn't configured."""
    def delay(self, *args, **kwargs):
        logger.info("run_analysis.delay called (stub) with args=%s", args)

run_analysis = _NoOpTask()
