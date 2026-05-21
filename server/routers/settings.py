# server/routers/settings.py
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import AppSettings
from server.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Provider → env var for API key (mirrors tasks.py)
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


def _get_or_create(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# ── GET /api/settings ──────────────────────────────────────────────────────────

@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    row = _get_or_create(db)
    return SettingsOut(
        provider=row.provider or "qwen-cn",
        deep_model=row.deep_model or "qwen3.6-plus",
        quick_model=row.quick_model or "qwen3.6-flash",
        backend_url=row.backend_url,
        has_api_key=bool(row.api_key),
    )


# ── POST /api/settings ─────────────────────────────────────────────────────────

@router.post("", response_model=SettingsOut)
def save_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    row = _get_or_create(db)
    row.provider = payload.provider
    row.deep_model = payload.deep_model
    row.quick_model = payload.quick_model
    row.backend_url = payload.backend_url or None
    row.updated_at = datetime.utcnow()
    if payload.api_key:
        row.api_key = payload.api_key
    db.commit()
    db.refresh(row)
    return SettingsOut(
        provider=row.provider,
        deep_model=row.deep_model,
        quick_model=row.quick_model,
        backend_url=row.backend_url,
        has_api_key=bool(row.api_key),
    )


# ── GET /api/settings/models?provider=qwen-cn ─────────────────────────────────

class ModelOption(BaseModel):
    label: str
    value: str

class ModelsResponse(BaseModel):
    quick: List[ModelOption]
    deep: List[ModelOption]


@router.get("/models", response_model=ModelsResponse)
def get_models(provider: str = "qwen-cn"):
    """Return model catalog for a given provider from the built-in model_catalog."""
    from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
    options = MODEL_OPTIONS.get(provider.lower(), {})
    return ModelsResponse(
        quick=[ModelOption(label=lbl, value=val) for lbl, val in options.get("quick", [])],
        deep=[ModelOption(label=lbl, value=val) for lbl, val in options.get("deep", [])],
    )


@router.get("/providers")
def get_providers():
    """Return all supported providers."""
    return [
        {"value": "qwen-cn",    "label": "阿里 通义千问（国内）",    "api_key_label": "DashScope API Key（国内账号）"},
        {"value": "qwen",       "label": "阿里 通义千问（国际）",    "api_key_label": "DashScope API Key（国际账号）"},
        {"value": "openai",     "label": "OpenAI",                    "api_key_label": "OpenAI API Key"},
        {"value": "anthropic",  "label": "Anthropic (Claude)",        "api_key_label": "Anthropic API Key"},
        {"value": "deepseek",   "label": "DeepSeek",                 "api_key_label": "DeepSeek API Key"},
        {"value": "google",     "label": "Google (Gemini)",           "api_key_label": "Google API Key"},
        {"value": "xai",        "label": "xAI (Grok)",               "api_key_label": "xAI API Key"},
        {"value": "glm-cn",     "label": "智谱 GLM（国内）",          "api_key_label": "智谱 API Key（国内）"},
        {"value": "glm",        "label": "智谱 GLM（国际）",          "api_key_label": "智谱 API Key（国际）"},
        {"value": "minimax-cn", "label": "MiniMax（国内）",           "api_key_label": "MiniMax API Key"},
    ]


# ── POST /api/settings/test ────────────────────────────────────────────────────

class TestResult(BaseModel):
    success: bool
    latency_ms: Optional[int] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    response_preview: Optional[str] = None
    error: Optional[str] = None


@router.post("/test", response_model=TestResult)
def test_connection(db: Session = Depends(get_db)):
    """Test LLM connectivity using current saved settings.

    Uses the quick_model to keep latency low. Sets the API key env var
    temporarily so the LangChain client can authenticate.
    """
    row = _get_or_create(db)

    if not row.api_key:
        return TestResult(success=False, error="未配置 API Key，请先保存配置")

    provider = row.provider or "qwen-cn"
    model = row.quick_model or "qwen3.6-flash"

    # Inject API key into environment for the duration of this call
    env_var = _PROVIDER_ENV.get(provider)
    if env_var:
        os.environ[env_var] = row.api_key

    try:
        import httpx
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        # Resolve base URL (custom or provider default)
        if row.backend_url:
            base_url = row.backend_url
        else:
            from tradingagents.llm_clients.openai_client import _PROVIDER_BASE_URL
            base_url = _PROVIDER_BASE_URL.get(provider)

        # Use trust_env=False to bypass system SOCKS/HTTP proxies that
        # may not have the required packages installed
        http_client = httpx.Client(trust_env=False)

        llm = ChatOpenAI(
            model=model,
            api_key=row.api_key,
            base_url=base_url,
            http_client=http_client,
            max_tokens=10,
        )

        start = time.time()
        response = llm.invoke([HumanMessage(content="Reply OK only.")])
        latency_ms = int((time.time() - start) * 1000)
        http_client.close()

        content = str(getattr(response, "content", response))[:120]
        return TestResult(
            success=True,
            latency_ms=latency_ms,
            model=model,
            provider=provider,
            response_preview=content,
        )

    except Exception as exc:
        return TestResult(success=False, error=str(exc)[:300])


# ── GET /api/settings/futu-status ─────────────────────────────────────────────

@router.get("/futu-status")
def futu_status():
    """Check if Futu OpenD is running and reachable."""
    from tradingagents.dataflows.futu_data import test_futu_connection
    result = test_futu_connection()
    return result


@router.get("/jq-status")
def jq_status():
    """Check JoinQuant API connectivity and remaining queries."""
    from tradingagents.dataflows.jq_data import test_jq_connection
    return test_jq_connection()
