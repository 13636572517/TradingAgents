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
        max_api_calls=row.max_api_calls if row.max_api_calls is not None else 60,
        input_cost_per_million=row.input_cost_per_million or 0.0,
        output_cost_per_million=row.output_cost_per_million or 0.0,
    )


# ── POST /api/settings ─────────────────────────────────────────────────────────

@router.post("", response_model=SettingsOut)
def save_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    row = _get_or_create(db)
    row.provider = payload.provider
    row.deep_model = payload.deep_model
    row.quick_model = payload.quick_model
    row.backend_url = payload.backend_url or None
    row.max_api_calls = max(10, min(payload.max_api_calls, 1000))
    row.input_cost_per_million = payload.input_cost_per_million
    row.output_cost_per_million = payload.output_cost_per_million
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
        max_api_calls=row.max_api_calls,
        input_cost_per_million=row.input_cost_per_million or 0.0,
        output_cost_per_million=row.output_cost_per_million or 0.0,
    )


# ── GET /api/settings/models?provider=qwen-cn ─────────────────────────────────

class ModelOption(BaseModel):
    label: str
    value: str

class ModelsResponse(BaseModel):
    quick: List[ModelOption]
    deep: List[ModelOption]


_DASHSCOPE_BASE = {
    "qwen-cn": "https://dashscope.aliyuncs.com",
    "qwen":    "https://dashscope-intl.aliyuncs.com",
}

# Non-text capability keywords — models with these in the name are excluded
_EXCLUDE_CAPS = [
    "tts", "asr", "vl", "image", "realtime", "omni", "speech",
    "embedding", "embed", "ocr", "translate", "livetranslate",
    "s2s", "audio", "video", "wan", "vision",
]

# Model ID prefixes / exact IDs known to include a free-tier quota on DashScope.
# Source: https://help.aliyun.com/zh/model-studio/getting-started/first-api-call-to-qwen
_FREE_TIER_PREFIXES = [
    "qwen-long", "qwen-turbo", "qwen-plus", "qwen-max",
    "qwen3-", "qwen2.5-", "qwen2-", "qwen1.5-",
    "deepseek-r1", "deepseek-v3",
    "qwq-", "qvq-",
]


class LiveModelItem(BaseModel):
    id: str
    free_tier: bool    # True = known DashScope free-tier quota exists


class LiveModelsResponse(BaseModel):
    models: List[LiveModelItem]
    source: str        # "live" or "static" (fallback)


@router.get("/live-models", response_model=LiveModelsResponse)
def get_live_models(db: Session = Depends(get_db)):
    """Fetch text-only models from DashScope /models endpoint using saved API key."""
    row = _get_or_create(db)
    if not row.api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="请先配置并保存 API Key")

    provider = row.provider or "qwen-cn"
    base = _DASHSCOPE_BASE.get(provider)
    if not base:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' 不支持实时模型列表")

    try:
        import httpx
        with httpx.Client(trust_env=False, timeout=12) as client:
            resp = client.get(
                f"{base}/compatible-mode/v1/models",
                headers={"Authorization": f"Bearer {row.api_key}"},
            )
            resp.raise_for_status()
        raw: List[str] = [m["id"] for m in resp.json().get("data", [])]
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=f"无法获取模型列表: {exc}")

    def _is_text(model_id: str) -> bool:
        low = model_id.lower()
        return not any(kw in low for kw in _EXCLUDE_CAPS)

    def _is_free(model_id: str) -> bool:
        low = model_id.lower()
        return any(low.startswith(p) or low == p.rstrip("-") for p in _FREE_TIER_PREFIXES)

    items = [
        LiveModelItem(id=m, free_tier=_is_free(m))
        for m in sorted(raw)
        if _is_text(m)
    ]
    return LiveModelsResponse(models=items, source="live")


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
    from tradingagents.dataflows.jq_data import test_jq_connection
    return test_jq_connection()


@router.get("/mairui-status")
def mairui_status():
    """Check MaiRui API connectivity."""
    from tradingagents.dataflows.mairui_data import test_mairui_connection
    return test_mairui_connection()
