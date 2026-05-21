# server/events.py
import asyncio
import json
from typing import AsyncGenerator

from server.database import SessionLocal
from server.models import Analysis

_STAGE_PROGRESS = {
    "pending":  0,
    "analysts": 20,
    "debate":   55,
    "risk":     75,
    "decision": 90,
    "complete": 100,
}

_STAGE_LABEL = {
    "pending":  "等待开始…",
    "analysts": "分析师团队运行中…",
    "debate":   "多空辩论进行中…",
    "risk":     "风险评估进行中…",
    "decision": "最终决策生成中…",
    "complete": "分析完成",
}


async def analysis_event_stream(analysis_id: str) -> AsyncGenerator[str, None]:
    """Yield SSE events on every stage OR stage_detail change (2-second polling)."""
    last_stage = None
    last_detail = None

    for _ in range(900):  # max 30 min
        db = SessionLocal()
        try:
            record = db.get(Analysis, analysis_id)
            if not record:
                yield _sse({"error": "not found"})
                return

            stage = record.stage
            detail = record.stage_detail or ""

            # Emit on any change — stage transition OR detail update
            if stage != last_stage or detail != last_detail:
                last_stage = stage
                last_detail = detail
                payload = {
                    "stage":    stage,
                    "label":    _STAGE_LABEL.get(stage, stage),
                    "detail":   detail,
                    "progress": _STAGE_PROGRESS.get(stage, 0),
                    "status":   record.status,
                    "refresh":  True,   # tell frontend to re-fetch analysis data
                }
                if stage == "complete":
                    payload["decision"] = record.decision
                yield _sse(payload)

            if record.status in ("complete", "failed"):
                # Send a final event so the client knows to stop
                if record.status == "failed":
                    yield _sse({
                        "stage": "failed",
                        "label": "分析失败",
                        "detail": record.stage_detail or record.error or "未知错误",
                        "progress": 0,
                        "status": "failed",
                    })
                return
        finally:
            db.close()

        await asyncio.sleep(2)

    yield _sse({"error": "timeout", "status": "failed"})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
