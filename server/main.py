# server/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from server.database import init_db
from server.routers.analyses import router as analyses_router
from server.routers.notifications import router as notifications_router
from server.routers.settings import router as settings_router

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
app.include_router(settings_router)


@app.on_event("startup")
def on_startup():
    init_db()


# Serve React build in production (web/dist must exist)
_dist = Path(__file__).parent.parent / "web" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
