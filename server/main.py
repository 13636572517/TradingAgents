# server/main.py
import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from server.database import init_db
from server.routers.analyses import router as analyses_router
from server.routers.notifications import router as notifications_router
from server.routers.settings import router as settings_router
from server.routers.search import router as search_router
from server.routers.stats import router as stats_router
from server.routers.kline import router as kline_router
from server.routers.auth import router as auth_router
from server.routers.admin import router as admin_router
from server.routers.strategies import router as strategies_router
from server.routers.pricing import router as pricing_router
from server.routers.ticker_settings import router as ticker_settings_router
from server.routers.screener import router as screener_router
from server.auth import get_current_user

app = FastAPI(title="TradingAgents Web API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://47.103.133.232:8080",
        "https://trading.yusuan.xyz",
        "http://trading.yusuan.xyz",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization"],
)

_auth_dep = [Depends(get_current_user)]

app.include_router(auth_router)                              # public — no auth
app.include_router(admin_router)                             # admin-only (auth inside router)
app.include_router(analyses_router,      dependencies=_auth_dep)
app.include_router(notifications_router, dependencies=_auth_dep)
app.include_router(settings_router,      dependencies=_auth_dep)
app.include_router(search_router,        dependencies=_auth_dep)
app.include_router(stats_router,         dependencies=_auth_dep)
app.include_router(kline_router,         dependencies=_auth_dep)
app.include_router(strategies_router,    dependencies=_auth_dep)
app.include_router(pricing_router,       dependencies=_auth_dep)
app.include_router(ticker_settings_router, dependencies=_auth_dep)
app.include_router(screener_router,      dependencies=_auth_dep)


@app.on_event("startup")
def on_startup():
    init_db()
    # Re-hydrate API keys from the DB into the process env so clients can
    # authenticate after a restart.
    try:
        from server.database import SessionLocal
        from server.models import AppSettings
        with SessionLocal() as _db:
            _s = _db.get(AppSettings, 1)
            if _s and _s.tickflow_api_key:
                os.environ["TICKFLOW_API_KEY"] = _s.tickflow_api_key
            # Re-hydrate LLM API key based on saved provider
            if _s and _s.api_key and _s.provider:
                _PROVIDER_ENV = {
                    "qwen":       "DASHSCOPE_API_KEY",
                    "qwen-cn":    "DASHSCOPE_CN_API_KEY",
                    "openai":     "OPENAI_API_KEY",
                    "anthropic":  "ANTHROPIC_API_KEY",
                    "deepseek":   "DEEPSEEK_API_KEY",
                    "glm":        "ZHIPU_API_KEY",
                    "glm-cn":     "ZHIPU_CN_API_KEY",
                    "google":     "GOOGLE_API_KEY",
                    "xai":        "XAI_API_KEY",
                    "minimax":    "MINIMAX_API_KEY",
                    "minimax-cn": "MINIMAX_API_KEY",
                }
                _env_var = _PROVIDER_ENV.get(_s.provider)
                if _env_var:
                    os.environ[_env_var] = _s.api_key
    except Exception:
        pass  # non-critical; key can still be set via the settings UI
    # Pre-warm the stock search cache in a background thread so the first
    # search request returns instantly instead of waiting 8+ seconds.
    import threading
    def _warmup():
        try:
            from server.routers.search import _load_securities
            _load_securities()
        except Exception:
            pass  # non-critical, search still works on first request
    threading.Thread(target=_warmup, daemon=True).start()


# Serve React build in production (web/dist must exist)
_dist = Path(__file__).parent.parent / "web" / "dist"
if _dist.exists():
    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles

    # SPA catch-all: paths with no file extension get index.html (client-side routing).
    # Paths with an extension (*.png, *.js, *.css …) are handled by StaticFiles below.
    # This must be registered BEFORE the StaticFiles mount so FastAPI sees it first.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> Response:
        from fastapi import HTTPException
        last_segment = full_path.split("/")[-1]
        if "." in last_segment:
            candidate = _dist / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            raise HTTPException(status_code=404)
        return FileResponse(str(_dist / "index.html"))

    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
