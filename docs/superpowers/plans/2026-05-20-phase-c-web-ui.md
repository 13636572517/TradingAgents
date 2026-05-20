# Phase C — Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap TradingAgents in a FastAPI + React web application so non-technical team members can submit analyses, watch progress, and read reports in a browser.

**Architecture:** FastAPI backend serves a REST API and SSE stream. Celery workers (backed by Redis) run long analysis tasks asynchronously. SQLAlchemy persists analysis records to SQLite (local) or MySQL (ECS). React + Vite frontend communicates via Axios and receives live progress via Server-Sent Events.

**Tech Stack:** Python 3.10+, FastAPI, Celery, SQLAlchemy, Redis, React 18, TypeScript, Vite, Axios, react-router-dom, react-markdown, Tailwind CSS

**Prerequisite:** Phase B plan must be complete before running end-to-end tests with CN tickers.

---

## File Map

### Backend (`server/`)

| Action | Path | Responsibility |
|---|---|---|
| Create | `server/__init__.py` | Package marker |
| Create | `server/database.py` | SQLAlchemy engine + SessionLocal + Base |
| Create | `server/models.py` | Analysis ORM model |
| Create | `server/schemas.py` | Pydantic request/response shapes |
| Create | `server/celery_app.py` | Celery instance + config |
| Create | `server/tasks.py` | `run_analysis` Celery task |
| Create | `server/events.py` | SSE progress-stream helpers |
| Create | `server/routers/__init__.py` | Package marker |
| Create | `server/routers/analyses.py` | `/api/analyses` CRUD |
| Create | `server/routers/notifications.py` | `/api/notifications` |
| Create | `server/main.py` | FastAPI app, CORS, router mounts |
| Create | `tests/test_server_analyses.py` | API endpoint tests |

### Frontend (`web/`)

| Action | Path | Responsibility |
|---|---|---|
| Create | `web/` | Vite + React + TypeScript scaffold |
| Create | `web/src/api/client.ts` | Axios instance + all API calls |
| Create | `web/src/types.ts` | Shared TypeScript types |
| Create | `web/src/components/Sidebar.tsx` | Fixed sidebar + notification badge |
| Create | `web/src/components/ProgressTimeline.tsx` | 4-stage timeline with SSE |
| Create | `web/src/components/ReportBanner.tsx` | Sticky BUY/HOLD/SELL banner |
| Create | `web/src/components/ReportTabs.tsx` | Tab switcher for report sections |
| Create | `web/src/pages/NewAnalysis.tsx` | Submission form |
| Create | `web/src/pages/History.tsx` | Analysis list |
| Create | `web/src/pages/Report.tsx` | Full report view |
| Create | `web/src/App.tsx` | Root + react-router routes |
| Create | `web/src/main.tsx` | Entry point |

### Infrastructure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `docker-compose.yml` | Add redis, server, celery, web services |
| Create | `.env.example` | All required env vars documented |

---

## Task 1: Backend scaffold — database, models, schemas

**Files:**
- Create: `server/__init__.py`
- Create: `server/database.py`
- Create: `server/models.py`
- Create: `server/schemas.py`
- Create: `tests/test_server_analyses.py` (skeleton)

- [ ] **Step 1: Install backend dependencies**

```bash
pip install fastapi uvicorn[standard] celery sqlalchemy pymysql cryptography httpx pytest-asyncio
```

- [ ] **Step 2: Create package marker**

```python
# server/__init__.py
```

- [ ] **Step 3: Create `server/database.py`**

```python
# server/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradingagents.db")

# SQLite needs check_same_thread=False; MySQL does not need it
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session and closes it on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Call once on startup."""
    from server import models  # noqa: F401 — ensure models are registered
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 4: Create `server/models.py`**

```python
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
```

- [ ] **Step 5: Create `server/schemas.py`**

```python
# server/schemas.py
from __future__ import annotations
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel


class AnalysisCreate(BaseModel):
    ticker: str
    trade_date: str          # YYYY-MM-DD
    analysts: List[str]      # ["fundamentals", "sentiment", "news", "market"]
    depth: int = 1           # 1=fast 2=standard 3=deep


class AnalysisOut(BaseModel):
    id: str
    ticker: str
    ticker_name: Optional[str]
    trade_date: str
    analysts: List[str]
    depth: int
    status: str
    stage: str
    result: Optional[Any]
    decision: Optional[str]
    error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    seen: bool

    model_config = {"from_attributes": True}


class AnalysisListOut(BaseModel):
    items: List[AnalysisOut]
    total: int


class NotificationCount(BaseModel):
    unseen: int
```

- [ ] **Step 6: Write test skeleton**

```python
# tests/test_server_analyses.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.main import app

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite://"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 7: Commit**

```bash
git add server/ tests/test_server_analyses.py
git commit -m "feat(server): add database, models, and schemas for Analysis"
```

---

## Task 2: Analysis CRUD endpoints + FastAPI app

**Files:**
- Create: `server/routers/__init__.py`
- Create: `server/routers/analyses.py`
- Create: `server/routers/notifications.py`
- Create: `server/main.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_server_analyses.py`:

```python
def test_create_analysis_returns_201(client):
    resp = client.post("/api/analyses", json={
        "ticker": "600519.SS",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals", "sentiment"],
        "depth": 1,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "600519.SS"
    assert data["status"] == "pending"
    assert "id" in data


def test_list_analyses_empty(client):
    resp = client.get("/api/analyses")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


def test_list_analyses_returns_created(client):
    client.post("/api/analyses", json={
        "ticker": "AAPL",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals"],
        "depth": 1,
    })
    resp = client.get("/api/analyses")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["ticker"] == "AAPL"


def test_get_analysis_by_id(client):
    create_resp = client.post("/api/analyses", json={
        "ticker": "NVDA",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals"],
        "depth": 1,
    })
    analysis_id = create_resp.json()["id"]
    resp = client.get(f"/api/analyses/{analysis_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == analysis_id


def test_get_analysis_not_found(client):
    resp = client.get("/api/analyses/nonexistent-id")
    assert resp.status_code == 404


def test_delete_analysis(client):
    create_resp = client.post("/api/analyses", json={
        "ticker": "TSLA",
        "trade_date": "2024-05-10",
        "analysts": ["fundamentals"],
        "depth": 1,
    })
    analysis_id = create_resp.json()["id"]
    del_resp = client.delete(f"/api/analyses/{analysis_id}")
    assert del_resp.status_code == 204
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 404


def test_notification_count_zero_when_all_seen(client):
    resp = client.get("/api/notifications/count")
    assert resp.status_code == 200
    assert resp.json()["unseen"] == 0
```

- [ ] **Step 2: Run tests — expect fail**

```bash
python -m pytest tests/test_server_analyses.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'app' from 'server.main'`

- [ ] **Step 3: Create `server/routers/__init__.py`**

```python
# server/routers/__init__.py
```

- [ ] **Step 4: Create `server/routers/analyses.py`**

```python
# server/routers/analyses.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import Analysis
from server.schemas import AnalysisCreate, AnalysisOut, AnalysisListOut

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisOut, status_code=201)
def create_analysis(
    payload: AnalysisCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    record = Analysis(
        ticker=payload.ticker.upper(),
        trade_date=payload.trade_date,
        analysts=payload.analysts,
        depth=payload.depth,
        status="pending",
        stage="pending",
        seen=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Dispatch the Celery task after committing so the ID exists in DB
    from server.tasks import run_analysis
    run_analysis.delay(record.id)

    return record


@router.get("", response_model=AnalysisListOut)
def list_analyses(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    total = db.query(Analysis).count()
    items = (
        db.query(Analysis)
        .order_by(Analysis.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return AnalysisListOut(items=items, total=total)


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return record


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete(record)
    db.commit()
```

- [ ] **Step 5: Create `server/routers/notifications.py`**

```python
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
```

- [ ] **Step 6: Create `server/main.py`**

```python
# server/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from server.database import init_db
from server.routers.analyses import router as analyses_router
from server.routers.notifications import router as notifications_router

app = FastAPI(title="TradingAgents Web API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyses_router)
app.include_router(notifications_router)


@app.on_event("startup")
def on_startup():
    init_db()


# Serve React build in production (web/dist must exist)
_dist = Path(__file__).parent.parent / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
```

- [ ] **Step 7: Run tests — expect pass**

```bash
python -m pytest tests/test_server_analyses.py -v
```

Expected: all 8 tests PASS (Celery task is imported but `.delay()` does nothing in test env)

- [ ] **Step 8: Commit**

```bash
git add server/routers/ server/main.py
git commit -m "feat(server): add Analysis CRUD endpoints and FastAPI app"
```

---

## Task 3: Celery app + `run_analysis` task with progress updates

**Files:**
- Create: `server/celery_app.py`
- Create: `server/tasks.py`

- [ ] **Step 1: Create `server/celery_app.py`**

```python
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
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
```

- [ ] **Step 2: Create `server/tasks.py`**

```python
# server/tasks.py
import logging
from datetime import datetime

from server.celery_app import celery_app
from server.database import SessionLocal
from server.models import Analysis

logger = logging.getLogger(__name__)

# Map LangGraph node names to UI stage labels
_NODE_TO_STAGE = {
    "Research Manager": "debate",
    "Trader": "risk",
    "Portfolio Manager": "decision",
}


def _set_stage(db, record: Analysis, stage: str):
    record.stage = stage
    db.commit()


@celery_app.task(bind=True, name="server.tasks.run_analysis")
def run_analysis(self, analysis_id: str):
    """Run TradingAgentsGraph.propagate() for the given analysis record.

    Progress is written to Analysis.stage so the SSE endpoint can stream it.
    Node names from LangGraph are mapped to the 4 UI stages:
      analysts → debate → risk → decision → complete
    """
    db = SessionLocal()
    try:
        record = db.get(Analysis, analysis_id)
        if not record:
            logger.error("run_analysis: analysis %s not found", analysis_id)
            return

        record.status = "running"
        record.stage = "analysts"
        db.commit()

        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config["output_language"] = "Chinese"
        config["max_debate_rounds"] = record.depth
        config["max_risk_discuss_rounds"] = record.depth
        config["debug"] = False
        # Disable checkpointing inside Celery to keep tasks stateless
        config["checkpoint_enabled"] = False

        ta = TradingAgentsGraph(debug=True, config=config)

        # Stream the graph to capture per-node progress
        from tradingagents.graph.propagation import create_initial_state
        from tradingagents.graph.analyst_execution import build_analyst_execution_plan

        init_state = ta.propagator.create_initial_state(
            record.ticker, record.trade_date, asset_type="stock", past_context=""
        )
        args = ta.propagator.get_graph_args()

        final_state = {}
        for chunk in ta.graph.stream(init_state, **args):
            final_state.update(chunk)
            # Identify which node just completed and update stage
            for node_name, new_stage in _NODE_TO_STAGE.items():
                if node_name in chunk:
                    _set_stage(db, record, new_stage)
                    break

        decision_str = ta.process_signal(final_state.get("final_trade_decision", ""))
        decision = _extract_decision_label(decision_str)

        record.status = "complete"
        record.stage = "complete"
        record.decision = decision
        record.result = {
            "market_report": final_state.get("market_report"),
            "sentiment_report": final_state.get("sentiment_report"),
            "news_report": final_state.get("news_report"),
            "fundamentals_report": final_state.get("fundamentals_report"),
            "investment_plan": final_state.get("investment_plan"),
            "trader_investment_plan": final_state.get("trader_investment_plan"),
            "final_trade_decision": final_state.get("final_trade_decision"),
        }
        record.completed_at = datetime.utcnow()
        record.seen = False   # triggers sidebar notification badge
        db.commit()

    except Exception as exc:
        logger.exception("run_analysis failed for %s", analysis_id)
        record = db.get(Analysis, analysis_id)
        if record:
            record.status = "failed"
            record.error = str(exc)
            record.seen = False
            db.commit()
        raise
    finally:
        db.close()


def _extract_decision_label(decision_str: str) -> str:
    """Extract BUY, HOLD, or SELL from the process_signal output string."""
    upper = (decision_str or "").upper()
    for label in ("BUY", "SELL", "HOLD"):
        if label in upper:
            return label
    return "HOLD"
```

- [ ] **Step 3: Write a unit test for `_extract_decision_label`**

Add to `tests/test_server_analyses.py`:

```python
def test_extract_decision_label_buy():
    from server.tasks import _extract_decision_label
    assert _extract_decision_label("Strong BUY recommendation") == "BUY"


def test_extract_decision_label_sell():
    from server.tasks import _extract_decision_label
    assert _extract_decision_label("SELL — elevated risk") == "SELL"


def test_extract_decision_label_fallback():
    from server.tasks import _extract_decision_label
    assert _extract_decision_label("unclear signal") == "HOLD"
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_server_analyses.py -v
```

Expected: all tests PASS (including 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add server/celery_app.py server/tasks.py tests/test_server_analyses.py
git commit -m "feat(server): add Celery app and run_analysis task with LangGraph progress streaming"
```

---

## Task 4: SSE progress stream endpoint

**Files:**
- Create: `server/events.py`
- Modify: `server/routers/analyses.py`

- [ ] **Step 1: Create `server/events.py`**

```python
# server/events.py
import asyncio
import json
from typing import AsyncGenerator

from sqlalchemy.orm import Session

from server.database import SessionLocal
from server.models import Analysis

_STAGE_PROGRESS = {
    "pending":  0,
    "analysts": 25,
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
    """Yield SSE-formatted progress events until the analysis completes or fails."""
    last_stage = None

    for _ in range(600):  # max ~20 minutes at 2-second polling
        db: Session = SessionLocal()
        try:
            record = db.get(Analysis, analysis_id)
            if not record:
                yield _sse({"error": "not found"})
                return

            stage = record.stage
            if stage != last_stage:
                last_stage = stage
                payload = {
                    "stage": stage,
                    "label": _STAGE_LABEL.get(stage, stage),
                    "progress": _STAGE_PROGRESS.get(stage, 0),
                    "status": record.status,
                }
                if stage == "complete":
                    payload["decision"] = record.decision
                yield _sse(payload)

            if record.status in ("complete", "failed"):
                return
        finally:
            db.close()

        await asyncio.sleep(2)

    yield _sse({"error": "timeout"})


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
```

- [ ] **Step 2: Add SSE endpoint to `server/routers/analyses.py`**

Add this import at the top:

```python
from fastapi.responses import StreamingResponse
from server.events import analysis_event_stream
```

Add this endpoint to the router:

```python
@router.get("/{analysis_id}/stream")
async def stream_analysis_progress(analysis_id: str, db: Session = Depends(get_db)):
    record = db.get(Analysis, analysis_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return StreamingResponse(
        analysis_event_stream(analysis_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disables Nginx buffering
        },
    )
```

- [ ] **Step 3: Commit**

```bash
git add server/events.py server/routers/analyses.py
git commit -m "feat(server): add SSE progress stream endpoint for analysis polling"
```

---

## Task 5: Docker Compose + `.env.example`

**Files:**
- Modify: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Replace `docker-compose.yml`**

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  server:
    build: .
    command: uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - tradingagents_data:/home/appuser/.tradingagents
      - .:/app
    depends_on:
      - redis

  celery:
    build: .
    command: celery -A server.celery_app worker --loglevel=info --concurrency=2
    env_file:
      - .env
    volumes:
      - tradingagents_data:/home/appuser/.tradingagents
      - .:/app
    depends_on:
      - redis

  web:
    image: node:20-alpine
    working_dir: /app/web
    command: sh -c "npm install && npm run dev -- --host"
    ports:
      - "5173:5173"
    volumes:
      - .:/app
    depends_on:
      - server

  # Legacy CLI service preserved
  tradingagents:
    build: .
    env_file:
      - .env
    volumes:
      - tradingagents_data:/home/appuser/.tradingagents
    tty: true
    stdin_open: true
    profiles:
      - cli

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    profiles:
      - ollama

volumes:
  tradingagents_data:
  ollama_data:
  redis_data:
```

- [ ] **Step 2: Create `.env.example`**

```bash
# .env.example — copy to .env and fill in your values

# ── LLM Provider ────────────────────────────────────────
TRADINGAGENTS_LLM_PROVIDER=anthropic
TRADINGAGENTS_DEEP_THINK_LLM=claude-sonnet-4-6
TRADINGAGENTS_QUICK_THINK_LLM=claude-haiku-4-5-20251001

# ── API Keys (set the one matching your provider) ───────
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GOOGLE_API_KEY=AIza...

# ── Database ────────────────────────────────────────────
# Local SQLite (default — leave commented out)
# DATABASE_URL=sqlite:///./tradingagents.db

# ECS MySQL — uncomment and fill in for cloud deployment
# DATABASE_URL=mysql+pymysql://user:password@localhost:3306/tradingagents

# ── Redis ───────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Alpha Vantage (optional) ────────────────────────────
# ALPHAVANTAGE_API_KEY=your_key_here
```

- [ ] **Step 3: Start services and verify server boots**

```bash
# Start redis + server + celery (no web yet)
docker compose up redis server celery -d

# Check server health
curl http://localhost:8000/api/analyses
```

Expected: `{"items":[],"total":0}`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore: update docker-compose with server/celery/redis/web services and add .env.example"
```

---

## Task 6: React scaffold + API client + shared types

**Files:**
- Create: `web/` (entire Vite scaffold)
- Create: `web/src/api/client.ts`
- Create: `web/src/types.ts`

- [ ] **Step 1: Scaffold React app**

```bash
cd /Users/michael/tradingagents/TradingAgents
npm create vite@latest web -- --template react-ts
cd web
npm install axios react-router-dom react-markdown
npm install -D tailwindcss postcss autoprefixer @types/node
npx tailwindcss init -p
```

- [ ] **Step 2: Configure Tailwind — replace `web/tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0d1117",
        surface: "#161b22",
        border: "#30363d",
        accent: "#00bfff",
        buy: "#22c55e",
        sell: "#ef4444",
        hold: "#fbbf24",
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 3: Replace `web/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  background-color: #0d1117;
  color: #cdd6f4;
  font-family: "Inter", system-ui, sans-serif;
}
```

- [ ] **Step 4: Configure Vite proxy — replace `web/vite.config.ts`**

```ts
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
})
```

- [ ] **Step 5: Create `web/src/types.ts`**

```ts
// web/src/types.ts
export interface Analysis {
  id: string
  ticker: string
  ticker_name: string | null
  trade_date: string
  analysts: string[]
  depth: number
  status: "pending" | "running" | "complete" | "failed"
  stage: string
  result: AnalysisResult | null
  decision: "BUY" | "HOLD" | "SELL" | null
  error: string | null
  created_at: string
  completed_at: string | null
  seen: boolean
}

export interface AnalysisResult {
  market_report: string | null
  sentiment_report: string | null
  news_report: string | null
  fundamentals_report: string | null
  investment_plan: string | null
  trader_investment_plan: string | null
  final_trade_decision: string | null
}

export interface AnalysisListResponse {
  items: Analysis[]
  total: number
}

export interface ProgressEvent {
  stage: string
  label: string
  progress: number
  status: string
  decision?: string
  error?: string
}
```

- [ ] **Step 6: Create `web/src/api/client.ts`**

```ts
// web/src/api/client.ts
import axios from "axios"
import type { Analysis, AnalysisListResponse } from "../types"

const http = axios.create({ baseURL: "/api" })

export const api = {
  createAnalysis: (payload: {
    ticker: string
    trade_date: string
    analysts: string[]
    depth: number
  }) => http.post<Analysis>("/analyses", payload).then((r) => r.data),

  listAnalyses: (skip = 0, limit = 50) =>
    http.get<AnalysisListResponse>("/analyses", { params: { skip, limit } }).then((r) => r.data),

  getAnalysis: (id: string) =>
    http.get<Analysis>(`/analyses/${id}`).then((r) => r.data),

  deleteAnalysis: (id: string) =>
    http.delete(`/analyses/${id}`),

  getNotificationCount: () =>
    http.get<{ unseen: number }>("/notifications/count").then((r) => r.data),

  markAllRead: () =>
    http.post("/notifications/read"),
}

export function openProgressStream(
  analysisId: string,
  onEvent: (event: import("../types").ProgressEvent) => void,
  onDone: () => void,
): EventSource {
  const es = new EventSource(`/api/analyses/${analysisId}/stream`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data) as import("../types").ProgressEvent
    onEvent(data)
    if (data.status === "complete" || data.status === "failed" || data.error) {
      es.close()
      onDone()
    }
  }
  es.onerror = () => {
    es.close()
    onDone()
  }
  return es
}
```

- [ ] **Step 7: Commit**

```bash
cd /Users/michael/tradingagents/TradingAgents
git add web/
git commit -m "feat(web): scaffold React+Vite app with Tailwind, API client, and TypeScript types"
```

---

## Task 7: Sidebar + App layout

**Files:**
- Create: `web/src/components/Sidebar.tsx`
- Create: `web/src/App.tsx`
- Modify: `web/src/main.tsx`

- [ ] **Step 1: Create `web/src/components/Sidebar.tsx`**

```tsx
// web/src/components/Sidebar.tsx
import { useEffect, useState } from "react"
import { NavLink, useNavigate } from "react-router-dom"
import { api } from "../api/client"

const NAV = [
  { to: "/new", icon: "＋", label: "新建分析" },
  { to: "/history", icon: "📋", label: "历史报告" },
  { to: "/settings", icon: "⚙️", label: "设置" },
]

export default function Sidebar() {
  const [unseen, setUnseen] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    const refresh = () => api.getNotificationCount().then((r) => setUnseen(r.unseen))
    refresh()
    const id = setInterval(refresh, 10_000)
    return () => clearInterval(id)
  }, [])

  const handleHistoryClick = async () => {
    if (unseen > 0) await api.markAllRead()
    setUnseen(0)
    navigate("/history")
  }

  return (
    <aside className="w-14 bg-surface border-r border-border flex flex-col items-center py-4 gap-6 shrink-0">
      <div className="w-8 h-8 rounded bg-accent/20 flex items-center justify-center text-accent font-bold text-sm">
        TA
      </div>
      {NAV.map((item) =>
        item.to === "/history" ? (
          <button
            key={item.to}
            onClick={handleHistoryClick}
            className="relative w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 text-gray-400 hover:text-accent transition-colors text-lg"
            title={item.label}
          >
            {item.icon}
            {unseen > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
                {unseen > 9 ? "9+" : unseen}
              </span>
            )}
          </button>
        ) : (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `w-10 h-10 flex items-center justify-center rounded hover:bg-accent/10 transition-colors text-lg ${
                isActive ? "text-accent bg-accent/10" : "text-gray-400 hover:text-accent"
              }`
            }
            title={item.label}
          >
            {item.icon}
          </NavLink>
        )
      )}
    </aside>
  )
}
```

- [ ] **Step 2: Create `web/src/App.tsx`**

```tsx
// web/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import Sidebar from "./components/Sidebar"
import NewAnalysis from "./pages/NewAnalysis"
import History from "./pages/History"
import Report from "./pages/Report"

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-bg">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/new" replace />} />
            <Route path="/new" element={<NewAnalysis />} />
            <Route path="/history" element={<History />} />
            <Route path="/report/:id" element={<Report />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
```

- [ ] **Step 3: Replace `web/src/main.tsx`**

```tsx
// web/src/main.tsx
import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import "./index.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 4: Commit**

```bash
git add web/src/
git commit -m "feat(web): add Sidebar with notification badge and App routing layout"
```

---

## Task 8: New Analysis page

**Files:**
- Create: `web/src/pages/NewAnalysis.tsx`

- [ ] **Step 1: Create `web/src/pages/NewAnalysis.tsx`**

```tsx
// web/src/pages/NewAnalysis.tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"

const ANALYSTS = [
  { key: "fundamentals", label: "基本面", emoji: "📊" },
  { key: "sentiment", label: "情绪", emoji: "💬" },
  { key: "news", label: "新闻", emoji: "📰" },
  { key: "market", label: "技术", emoji: "📈" },
]

const DEPTH = [
  { value: 1, label: "快速", desc: "约3分钟" },
  { value: 2, label: "标准", desc: "约7分钟" },
  { value: 3, label: "深度", desc: "约15分钟" },
]

export default function NewAnalysis() {
  const navigate = useNavigate()
  const [ticker, setTicker] = useState("")
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().slice(0, 10))
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>(
    ANALYSTS.map((a) => a.key)
  )
  const [depth, setDepth] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const toggleAnalyst = (key: string) => {
    setSelectedAnalysts((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ticker.trim()) return setError("请输入股票代码")
    if (selectedAnalysts.length === 0) return setError("至少选择一个分析师")
    setError("")
    setLoading(true)
    try {
      const analysis = await api.createAnalysis({
        ticker: ticker.trim().toUpperCase(),
        trade_date: tradeDate,
        analysts: selectedAnalysts,
        depth,
      })
      navigate(`/report/${analysis.id}`)
    } catch (err: any) {
      setError(err?.response?.data?.detail || "提交失败，请重试")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-lg mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold text-white mb-8">新建分析</h1>
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Ticker */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">股票代码</label>
          <input
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            placeholder="例如：600519.SS / 0700.HK / NVDA"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
          />
        </div>

        {/* Date */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">分析日期</label>
          <input
            type="date"
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            value={tradeDate}
            onChange={(e) => setTradeDate(e.target.value)}
          />
        </div>

        {/* Analysts */}
        <div>
          <label className="block text-sm text-gray-400 mb-2">包含分析师</label>
          <div className="flex gap-2 flex-wrap">
            {ANALYSTS.map((a) => (
              <button
                key={a.key}
                type="button"
                onClick={() => toggleAnalyst(a.key)}
                className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                  selectedAnalysts.includes(a.key)
                    ? "bg-accent/20 border-accent text-accent"
                    : "bg-surface border-border text-gray-400 hover:border-gray-500"
                }`}
              >
                {a.emoji} {a.label}
              </button>
            ))}
          </div>
        </div>

        {/* Depth */}
        <div>
          <label className="block text-sm text-gray-400 mb-2">研究深度</label>
          <div className="flex gap-2">
            {DEPTH.map((d) => (
              <button
                key={d.value}
                type="button"
                onClick={() => setDepth(d.value)}
                className={`flex-1 py-2 rounded-md text-sm border transition-colors ${
                  depth === d.value
                    ? "bg-accent/20 border-accent text-accent"
                    : "bg-surface border-border text-gray-400 hover:border-gray-500"
                }`}
              >
                <div className="font-medium">{d.label}</div>
                <div className="text-xs opacity-60">{d.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-accent text-black font-bold py-2.5 rounded-md hover:bg-accent/80 disabled:opacity-50 transition-colors"
        >
          {loading ? "提交中…" : "开始分析 →"}
        </button>
      </form>
    </div>
  )
}
```

- [ ] **Step 2: Start dev server and verify form renders**

```bash
cd /Users/michael/tradingagents/TradingAgents/web
npm run dev
```

Open `http://localhost:5173/new` — should see the form with ticker input, date, analyst checkboxes, and depth selector.

- [ ] **Step 3: Commit**

```bash
cd /Users/michael/tradingagents/TradingAgents
git add web/src/pages/NewAnalysis.tsx
git commit -m "feat(web): add New Analysis submission form"
```

---

## Task 9: History page

**Files:**
- Create: `web/src/pages/History.tsx`

- [ ] **Step 1: Create `web/src/pages/History.tsx`**

```tsx
// web/src/pages/History.tsx
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { Analysis } from "../types"

const DECISION_COLOR: Record<string, string> = {
  BUY: "text-buy border-buy bg-buy/10",
  SELL: "text-sell border-sell bg-sell/10",
  HOLD: "text-hold border-hold bg-hold/10",
}

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  running: "分析中…",
  complete: "完成",
  failed: "失败",
}

export default function History() {
  const navigate = useNavigate()
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listAnalyses().then((r) => {
      setAnalyses(r.items)
      setLoading(false)
    })
  }, [])

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>

  if (analyses.length === 0)
    return (
      <div className="p-10 text-center text-gray-400">
        <p className="text-lg mb-2">暂无分析记录</p>
        <button
          onClick={() => navigate("/new")}
          className="text-accent hover:underline text-sm"
        >
          新建第一个分析 →
        </button>
      </div>
    )

  return (
    <div className="px-6 py-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">历史报告</h1>
      <div className="space-y-3">
        {analyses.map((a) => (
          <div
            key={a.id}
            onClick={() => navigate(`/report/${a.id}`)}
            className="bg-surface border border-border rounded-lg p-4 cursor-pointer hover:border-accent/50 transition-colors flex items-center justify-between"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white">{a.ticker}</span>
                {a.ticker_name && (
                  <span className="text-sm text-gray-400">{a.ticker_name}</span>
                )}
                {!a.seen && (
                  <span className="w-2 h-2 bg-accent rounded-full" />
                )}
              </div>
              <div className="text-sm text-gray-400 mt-0.5">
                {a.trade_date} · 深度 {a.depth} · {a.analysts.length} 位分析师
              </div>
            </div>
            <div className="text-right shrink-0">
              {a.decision ? (
                <span
                  className={`inline-block px-2 py-0.5 rounded border text-sm font-bold ${
                    DECISION_COLOR[a.decision] ?? "text-gray-400"
                  }`}
                >
                  {a.decision}
                </span>
              ) : (
                <span className="text-sm text-gray-500">
                  {STATUS_LABEL[a.status] ?? a.status}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Navigate to `http://localhost:5173/history` — should show an empty state with "新建第一个分析 →" link.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/History.tsx
git commit -m "feat(web): add History page with analysis list and decision badges"
```

---

## Task 10: Progress timeline + Report page

**Files:**
- Create: `web/src/components/ProgressTimeline.tsx`
- Create: `web/src/components/ReportBanner.tsx`
- Create: `web/src/components/ReportTabs.tsx`
- Create: `web/src/pages/Report.tsx`

- [ ] **Step 1: Create `web/src/components/ProgressTimeline.tsx`**

```tsx
// web/src/components/ProgressTimeline.tsx
const STAGES = [
  { key: "analysts", label: "分析师团队", sub: "基本面 · 情绪 · 新闻 · 技术" },
  { key: "debate", label: "多空辩论", sub: "多方 vs 空方研究员" },
  { key: "risk", label: "风险评估", sub: "激进 · 中性 · 保守分析师" },
  { key: "decision", label: "最终决策", sub: "组合经理综合判断" },
]

const ORDER = ["analysts", "debate", "risk", "decision", "complete"]

function stageIndex(stage: string) {
  return ORDER.indexOf(stage)
}

interface Props {
  stage: string
  status: string
}

export default function ProgressTimeline({ stage, status }: Props) {
  const currentIdx = stageIndex(stage)

  return (
    <div className="max-w-md mx-auto py-16 px-6">
      <div className="text-center mb-10">
        <div className="text-4xl mb-3">📊</div>
        <h2 className="text-xl font-bold text-white">分析进行中</h2>
        <p className="text-gray-400 text-sm mt-1">完成后可离开此页，稍后回来查看</p>
      </div>

      <div className="space-y-0">
        {STAGES.map((s, i) => {
          const done = stageIndex(stage) > i || status === "complete"
          const active = stage === s.key && status === "running"

          return (
            <div key={s.key} className="flex gap-4">
              {/* connector column */}
              <div className="flex flex-col items-center">
                <div
                  className={`w-3 h-3 rounded-full mt-1 shrink-0 transition-colors ${
                    done
                      ? "bg-buy"
                      : active
                      ? "bg-accent animate-pulse"
                      : "bg-border"
                  }`}
                />
                {i < STAGES.length - 1 && (
                  <div className={`w-px flex-1 my-1 ${done ? "bg-buy/40" : "bg-border"}`} />
                )}
              </div>
              {/* label */}
              <div className={`pb-6 ${done || active ? "text-white" : "text-gray-500"}`}>
                <div className="font-medium text-sm">{s.label}</div>
                <div className="text-xs opacity-60">{s.sub}</div>
              </div>
            </div>
          )
        })}
      </div>

      {status === "failed" && (
        <p className="text-red-400 text-center text-sm mt-4">分析失败，请重试</p>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create `web/src/components/ReportBanner.tsx`**

```tsx
// web/src/components/ReportBanner.tsx
interface Props {
  ticker: string
  tickerName: string | null
  tradeDate: string
  decision: string
  depth: number
  analystCount: number
}

const DECISION_STYLE: Record<string, string> = {
  BUY: "text-buy border-buy bg-buy/10",
  SELL: "text-sell border-sell bg-sell/10",
  HOLD: "text-hold border-hold bg-hold/10",
}

export default function ReportBanner({
  ticker, tickerName, tradeDate, decision, depth, analystCount,
}: Props) {
  return (
    <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur border-b border-border px-6 py-3 flex items-center justify-between">
      <div>
        <div className="flex items-center gap-3">
          <span
            className={`text-lg font-bold px-3 py-0.5 rounded border ${
              DECISION_STYLE[decision] ?? "text-gray-400 border-border"
            }`}
          >
            {decision}
          </span>
          <span className="font-semibold text-white">{ticker}</span>
          {tickerName && <span className="text-gray-400 text-sm">{tickerName}</span>}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          {tradeDate} · 研究深度 {depth} · {analystCount} 位分析师
        </div>
      </div>
      <button
        onClick={() => window.print()}
        className="text-sm text-gray-400 hover:text-accent border border-border rounded-md px-3 py-1 hover:border-accent transition-colors"
      >
        导出
      </button>
    </div>
  )
}
```

- [ ] **Step 3: Create `web/src/components/ReportTabs.tsx`**

```tsx
// web/src/components/ReportTabs.tsx
import { useState } from "react"
import ReactMarkdown from "react-markdown"
import type { AnalysisResult } from "../types"

const TABS = [
  { key: "fundamentals_report", label: "基本面" },
  { key: "sentiment_report", label: "情绪" },
  { key: "news_report", label: "新闻" },
  { key: "market_report", label: "技术" },
  { key: "investment_plan", label: "投研总结" },
  { key: "trader_investment_plan", label: "交易建议" },
  { key: "final_trade_decision", label: "最终决策" },
]

const ANALYST_TAB_MAP: Record<string, string> = {
  fundamentals: "fundamentals_report",
  sentiment: "sentiment_report",
  news: "news_report",
  market: "market_report",
}

interface Props {
  result: AnalysisResult
  analysts: string[]
}

export default function ReportTabs({ result, analysts }: Props) {
  const availableTabs = TABS.filter((t) => {
    const analystKey = Object.entries(ANALYST_TAB_MAP).find(([, v]) => v === t.key)?.[0]
    if (analystKey) return analysts.includes(analystKey)
    return true
  })

  const [active, setActive] = useState(availableTabs[0]?.key ?? "")
  const content = result[active as keyof AnalysisResult] ?? "*暂无内容*"

  return (
    <div>
      {/* Tab bar */}
      <div className="flex border-b border-border overflow-x-auto">
        {availableTabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            className={`px-4 py-2.5 text-sm whitespace-nowrap border-b-2 transition-colors ${
              active === t.key
                ? "border-accent text-accent"
                : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-6 prose prose-invert prose-sm max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Create `web/src/pages/Report.tsx`**

```tsx
// web/src/pages/Report.tsx
import { useEffect, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { api, openProgressStream } from "../api/client"
import type { Analysis, ProgressEvent } from "../types"
import ProgressTimeline from "../components/ProgressTimeline"
import ReportBanner from "../components/ReportBanner"
import ReportTabs from "../components/ReportTabs"

export default function Report() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    api.getAnalysis(id).then((a) => {
      setAnalysis(a)
      setLoading(false)

      if (a.status === "complete" || a.status === "failed") return

      // Open SSE stream for in-progress analyses
      const es = openProgressStream(
        id,
        (event) => {
          setProgress(event)
        },
        () => {
          // Re-fetch final state when stream closes
          api.getAnalysis(id).then(setAnalysis)
        }
      )
      return () => es.close()
    })
  }, [id])

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>
  if (!analysis) return <div className="p-10 text-red-400">未找到该分析</div>

  const displayStatus = progress?.status ?? analysis.status
  const displayStage = progress?.stage ?? analysis.stage

  // Show timeline while in progress
  if (displayStatus === "running" || displayStatus === "pending") {
    return (
      <ProgressTimeline
        stage={displayStage}
        status={displayStatus}
      />
    )
  }

  // Show error state
  if (displayStatus === "failed") {
    return (
      <div className="p-10 text-center">
        <p className="text-red-400 text-lg mb-2">分析失败</p>
        <p className="text-gray-400 text-sm mb-4">{analysis.error ?? "未知错误"}</p>
        <button
          onClick={() => navigate("/new")}
          className="text-accent hover:underline text-sm"
        >
          重新分析 →
        </button>
      </div>
    )
  }

  // Complete — show report
  if (!analysis.result || !analysis.decision) {
    return <div className="p-10 text-gray-400">报告数据缺失</div>
  }

  return (
    <div>
      <ReportBanner
        ticker={analysis.ticker}
        tickerName={analysis.ticker_name}
        tradeDate={analysis.trade_date}
        decision={analysis.decision}
        depth={analysis.depth}
        analystCount={analysis.analysts.length}
      />
      <ReportTabs result={analysis.result} analysts={analysis.analysts} />
    </div>
  )
}
```

- [ ] **Step 5: Install react-markdown**

```bash
cd /Users/michael/tradingagents/TradingAgents/web
npm install react-markdown
```

- [ ] **Step 6: Commit**

```bash
cd /Users/michael/tradingagents/TradingAgents
git add web/src/components/ web/src/pages/Report.tsx
git commit -m "feat(web): add Report page with ProgressTimeline, ReportBanner, and ReportTabs"
```

---

## Task 11: End-to-end smoke test

- [ ] **Step 1: Start all services**

```bash
# Terminal 1 — Redis
docker compose up redis -d

# Terminal 2 — FastAPI server
DATABASE_URL=sqlite:///./tradingagents.db REDIS_URL=redis://localhost:6379/0 \
  uvicorn server.main:app --reload --port 8000

# Terminal 3 — Celery worker
DATABASE_URL=sqlite:///./tradingagents.db REDIS_URL=redis://localhost:6379/0 \
  celery -A server.celery_app worker --loglevel=info --concurrency=1

# Terminal 4 — React dev server
cd web && npm run dev
```

- [ ] **Step 2: Submit an analysis**

Open `http://localhost:5173/new`, enter:
- Ticker: `600519.SS` (or any valid ticker if AkShare not yet installed)
- Date: `2024-05-10`
- All analysts checked
- Depth: Standard

Click **开始分析** — should redirect to `/report/<id>` and show the 4-stage timeline.

- [ ] **Step 3: Verify progress updates**

Watch the timeline advance through stages. After completion, verify:
- Report page shows the BUY/HOLD/SELL banner
- Tabs contain analyst report text
- History page shows the analysis with decision badge

- [ ] **Step 4: Run backend test suite**

```bash
python -m pytest tests/test_server_analyses.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: complete Phase C Web UI — FastAPI + Celery + React end-to-end"
```
