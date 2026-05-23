# K线图弹窗 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每份分析报告右上角添加"📈 K线图"按钮，点击后打开全屏模态弹窗，展示 ECharts 蜡烛图/折线图 + MA + 成交量 + MACD/KDJ/RSI，数据源从 AkShare 降级到 BaoStock / JoinQuant / yfinance。

**Architecture:** FastAPI 新增 `/api/kline/{ticker}` 端点（`server/routers/kline.py`），按市场依次尝试各数据源，返回标准化 OHLCV JSON。前端新增 `useKLineData` hook + `KLineModal` 组件，使用 `echarts-for-react` 渲染三联图（主图/成交量/副指标），在 `Report.tsx` 顶栏添加触发按钮。

**Tech Stack:** FastAPI, AkShare, BaoStock, JoinQuant, yfinance, pandas（后端）；React 19, TypeScript, ECharts 5, echarts-for-react, Tailwind CSS（前端）

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 创建 | `server/routers/kline.py` | FastAPI 路由 + 多源降级数据引擎 |
| 创建 | `tests/test_kline_router.py` | 后端路由单元测试 |
| 修改 | `server/main.py` | 注册 kline 路由 |
| 修改 | `web/src/types.ts` | 新增 KLineBar, KLineResponse 类型 |
| 修改 | `web/src/api/client.ts` | 新增 `getKLine` 方法 |
| 创建 | `web/src/hooks/useKLineData.ts` | 数据拉取 + 内存缓存 hook |
| 创建 | `web/src/components/KLineModal.tsx` | 全屏弹窗 + ECharts 三联图 |
| 修改 | `web/src/pages/Report.tsx` | 顶部状态栏添加按钮 + Modal 状态 |

---

## Task 1: 后端 kline 路由（数据引擎）

**Files:**
- Create: `server/routers/kline.py`

- [ ] **Step 1: 创建路由文件**

```python
# server/routers/kline.py
"""K线 OHLCV 数据端点。按市场依次尝试多个数据源，返回标准化 JSON。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kline", tags=["kline"])

_RANGE_DAYS = {"1M": 45, "3M": 130, "6M": 260, "1Y": 375, "2Y": 750}


def _date_range(range_str: str) -> tuple[str, str]:
    days = _RANGE_DAYS.get(range_str, 375)
    end = datetime.today()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# ── Ticker helpers ─────────────────────────────────────────────────────────────

def _short_code(ticker: str) -> str:
    """600519.SS → 600519"""
    return ticker.upper().rsplit(".", 1)[0]


def _bs_code(ticker: str) -> str:
    """600519.SS → sh.600519,  000001.SZ → sz.000001"""
    t = ticker.upper()
    if t.endswith(".SS"):
        return "sh." + t[:-3]
    if t.endswith(".SZ"):
        return "sz." + t[:-3]
    return t


def _hk_code(ticker: str) -> str:
    """0700.HK → 00700 (5-digit for AkShare)"""
    return ticker.upper().replace(".HK", "").zfill(5)


def _jq_code(ticker: str) -> str:
    """600519.SS → 600519.XSHG,  000001.SZ → 000001.XSHE"""
    t = ticker.upper()
    if t.endswith(".SS"):
        return t[:-3] + ".XSHG"
    if t.endswith(".SZ"):
        return t[:-3] + ".XSHE"
    return t


def _is_etf(ticker: str) -> bool:
    t = ticker.upper()
    code = t.rsplit(".", 1)[0]
    if not code.isdigit() or len(code) != 6:
        return False
    p3 = code[:3]
    if t.endswith(".SZ") and p3 == "159":
        return True
    if t.endswith(".SS") and (code[:2] in ("51", "52") or p3 == "588"):
        return True
    return False


# ── Data normalizer ────────────────────────────────────────────────────────────

def _normalize(df: pd.DataFrame, col_map: dict) -> list[dict]:
    """Rename columns, drop NaN rows, return sorted list of dicts."""
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    needed = {"Date", "Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(df.columns):
        return []
    df = df[list(needed)].dropna()
    df = df.sort_values("Date")
    result = []
    for _, row in df.iterrows():
        try:
            result.append({
                "date":   str(row["Date"])[:10],
                "open":   round(float(row["Open"]),  4),
                "high":   round(float(row["High"]),  4),
                "low":    round(float(row["Low"]),   4),
                "close":  round(float(row["Close"]), 4),
                "volume": int(float(row["Volume"])),
            })
        except (ValueError, TypeError):
            continue
    return result


# ── Source: AkShare A-share / ETF ─────────────────────────────────────────────

def _fetch_akshare_a(ticker: str, start: str, end: str) -> list[dict]:
    import akshare as ak
    s_date = start.replace("-", "")
    e_date = end.replace("-", "")
    if _is_etf(ticker):
        df = ak.fund_etf_hist_em(
            symbol=_short_code(ticker), period="daily", adjust="qfq"
        )
        col_map = {"日期": "Date", "开盘": "Open", "最高": "High",
                   "最低": "Low", "收盘": "Close", "成交量": "Volume"}
        rows = _normalize(df, col_map)
        # Filter to date range (fund_etf_hist_em returns all history)
        return [r for r in rows if start <= r["date"] <= end]
    else:
        df = ak.stock_zh_a_hist(
            symbol=_short_code(ticker), period="daily",
            start_date=s_date, end_date=e_date, adjust="qfq",
        )
        col_map = {"日期": "Date", "开盘": "Open", "最高": "High",
                   "最低": "Low", "收盘": "Close", "成交量": "Volume"}
        return _normalize(df, col_map)


# ── Source: AkShare HK ────────────────────────────────────────────────────────

def _fetch_akshare_hk(ticker: str, start: str, end: str) -> list[dict]:
    import akshare as ak
    df = ak.stock_hk_hist(
        symbol=_hk_code(ticker), period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""),
        adjust="qfq",
    )
    col_map = {"日期": "Date", "开盘": "Open", "最高": "High",
               "最低": "Low", "收盘": "Close", "成交量": "Volume"}
    return _normalize(df, col_map)


# ── Source: AkShare US ────────────────────────────────────────────────────────

def _fetch_akshare_us(ticker: str, start: str, end: str) -> list[dict]:
    import akshare as ak
    df = ak.stock_us_hist(
        symbol=ticker.upper().replace(".US", ""), period="daily",
        start_date=start, end_date=end, adjust="qfq",
    )
    col_map = {"日期": "Date", "Date": "Date",
               "开盘": "Open",  "Open": "Open",
               "最高": "High",  "High": "High",
               "最低": "Low",   "Low": "Low",
               "收盘": "Close", "Close": "Close",
               "成交量": "Volume", "Volume": "Volume"}
    return _normalize(df, col_map)


# ── Source: BaoStock ──────────────────────────────────────────────────────────

def _fetch_baostock(ticker: str, start: str, end: str) -> list[dict]:
    from tradingagents.dataflows.baostock_data import _bs_session
    with _bs_session() as bs:
        rs = bs.query_history_k_data_plus(
            _bs_code(ticker),
            "date,open,high,low,close,volume",
            start_date=start, end_date=end,
            frequency="d", adjustflag="2",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
    if not rows:
        raise ValueError(f"BaoStock: no data for {ticker}")
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df = df.replace("", float("nan"))
    return _normalize(df, {})


# ── Source: JoinQuant ─────────────────────────────────────────────────────────

def _fetch_joinquant(ticker: str, start: str, end: str) -> list[dict]:
    from tradingagents.dataflows.jq_data import _JQ_LOCK, _ensure_auth
    import jqdatasdk as jq
    with _JQ_LOCK:
        _ensure_auth()
        df = jq.get_price(
            _jq_code(ticker), start_date=start, end_date=end,
            frequency="daily",
            fields=["open", "high", "low", "close", "volume"],
            fq="pre",
        )
    if df is None or df.empty:
        raise ValueError(f"JoinQuant: no data for {ticker}")
    df = df.reset_index().rename(columns={
        "index": "Date", "open": "Open", "high": "High",
        "low": "Low", "close": "Close", "volume": "Volume",
    })
    return _normalize(df, {})


# ── Source: yfinance ──────────────────────────────────────────────────────────

def _fetch_yfinance(ticker: str, start: str, end: str) -> list[dict]:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"yfinance: no data for {ticker}")
    df = df.reset_index()
    # yfinance may return MultiIndex columns when downloading single ticker
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return _normalize(df, {"Date": "Date", "Open": "Open", "High": "High",
                            "Low": "Low", "Close": "Close", "Volume": "Volume"})


# ── Fallback orchestrator ──────────────────────────────────────────────────────

def _fetch_with_fallback(ticker: str, start: str, end: str) -> tuple[list[dict], Optional[str]]:
    t = ticker.upper()
    is_a = t.endswith(".SS") or t.endswith(".SZ")
    is_hk = t.endswith(".HK")

    if is_a:
        chain = [
            ("AkShare",    _fetch_akshare_a),
            ("BaoStock",   _fetch_baostock),
            ("JoinQuant",  _fetch_joinquant),
            ("yfinance",   _fetch_yfinance),
        ]
    elif is_hk:
        chain = [
            ("AkShare-HK", _fetch_akshare_hk),
            ("yfinance",   _fetch_yfinance),
        ]
    else:  # US / other
        chain = [
            ("yfinance",   _fetch_yfinance),
            ("AkShare-US", _fetch_akshare_us),
        ]

    last_err = "所有数据源均不可用"
    for source, fn in chain:
        try:
            rows = fn(ticker, start, end)
            if rows:
                logger.info("kline: %s fetched %d bars from %s", ticker, len(rows), source)
                return rows, None
        except Exception as e:
            logger.warning("kline: %s failed from %s: %s", ticker, source, e)
            last_err = f"{source}: {e}"

    return [], last_err


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/{ticker}")
def get_kline(ticker: str, range: str = "1Y"):
    """Return OHLCV bars for ticker. Tries multiple data sources with graceful fallback."""
    if range not in _RANGE_DAYS:
        range = "1Y"
    start, end = _date_range(range)
    data, error = _fetch_with_fallback(ticker, start, end)
    return JSONResponse(
        content={"ticker": ticker, "range": range, "data": data, "error": error},
        headers={"Cache-Control": "public, max-age=3600"},
    )
```

- [ ] **Step 2: 验证文件语法**

```bash
cd /path/to/TradingAgents
python -c "import ast, sys; ast.parse(open('server/routers/kline.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add server/routers/kline.py
git commit -m "feat: add kline router with multi-source fallback chain"
```

---

## Task 2: 注册路由 + 后端测试

**Files:**
- Modify: `server/main.py`
- Create: `tests/test_kline_router.py`

- [ ] **Step 1: 编写测试（先让它失败）**

```python
# tests/test_kline_router.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)

SAMPLE_DATA = [
    {"date": "2025-01-02", "open": 7.50, "high": 7.65,
     "low": 7.45, "close": 7.60, "volume": 1234567},
    {"date": "2025-01-03", "open": 7.60, "high": 7.80,
     "low": 7.55, "close": 7.75, "volume": 9876543},
]


@pytest.mark.unit
@patch("server.routers.kline._fetch_with_fallback", return_value=(SAMPLE_DATA, None))
def test_kline_success(mock_fetch):
    resp = client.get("/api/kline/601985.SS?range=1M")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "601985.SS"
    assert body["range"] == "1M"
    assert len(body["data"]) == 2
    assert body["error"] is None
    first = body["data"][0]
    assert set(first.keys()) == {"date", "open", "high", "low", "close", "volume"}


@pytest.mark.unit
@patch("server.routers.kline._fetch_with_fallback", return_value=([], "所有数据源均不可用"))
def test_kline_all_sources_fail(mock_fetch):
    resp = client.get("/api/kline/INVALID.XX")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["error"] == "所有数据源均不可用"


@pytest.mark.unit
@patch("server.routers.kline._fetch_with_fallback", return_value=(SAMPLE_DATA, None))
def test_kline_invalid_range_defaults_to_1y(mock_fetch):
    resp = client.get("/api/kline/601985.SS?range=INVALID")
    assert resp.status_code == 200
    assert resp.json()["range"] == "1Y"


@pytest.mark.unit
def test_kline_cache_header():
    with patch("server.routers.kline._fetch_with_fallback", return_value=(SAMPLE_DATA, None)):
        resp = client.get("/api/kline/601985.SS")
    assert "max-age=3600" in resp.headers.get("cache-control", "")


@pytest.mark.unit
def test_short_code():
    from server.routers.kline import _short_code, _bs_code, _hk_code, _jq_code
    assert _short_code("600519.SS") == "600519"
    assert _bs_code("600519.SS") == "sh.600519"
    assert _bs_code("000001.SZ") == "sz.000001"
    assert _hk_code("0700.HK") == "00700"
    assert _jq_code("600519.SS") == "600519.XSHG"
    assert _jq_code("000001.SZ") == "000001.XSHE"


@pytest.mark.unit
def test_is_etf():
    from server.routers.kline import _is_etf
    assert _is_etf("159158.SZ") is True
    assert _is_etf("510050.SS") is True
    assert _is_etf("601985.SS") is False
    assert _is_etf("AAPL") is False
```

- [ ] **Step 2: 运行测试（确认失败，因为路由未注册）**

```bash
pytest tests/test_kline_router.py -v
```

Expected: `ImportError` 或 `404`（路由尚未注册）

- [ ] **Step 3: 注册路由到 main.py**

在 `server/main.py` 第 5-11 行的 import 区块中添加：

```python
from server.routers.kline import router as kline_router
```

在 `app.include_router(stats_router)` 后添加：

```python
app.include_router(kline_router)
```

完整 main.py import + include 区域如下：

```python
from server.routers.analyses import router as analyses_router
from server.routers.notifications import router as notifications_router
from server.routers.settings import router as settings_router
from server.routers.search import router as search_router
from server.routers.stats import router as stats_router
from server.routers.kline import router as kline_router

# ...

app.include_router(analyses_router)
app.include_router(notifications_router)
app.include_router(settings_router)
app.include_router(search_router)
app.include_router(stats_router)
app.include_router(kline_router)
```

- [ ] **Step 4: 运行测试（确认通过）**

```bash
pytest tests/test_kline_router.py -v
```

Expected: 全部 PASS（5 个测试）

- [ ] **Step 5: Commit**

```bash
git add server/main.py tests/test_kline_router.py
git commit -m "feat: register kline router and add unit tests"
```

---

## Task 3: 前端依赖 + 类型 + API 方法

**Files:**
- Modify: `web/package.json`（通过 npm install）
- Modify: `web/src/types.ts`
- Modify: `web/src/api/client.ts`

- [ ] **Step 1: 安装 ECharts**

```bash
cd web
npm install echarts echarts-for-react
```

Expected: package.json `dependencies` 中新增 `"echarts"` 和 `"echarts-for-react"`

- [ ] **Step 2: 验证安装**

```bash
node -e "require('./node_modules/echarts-for-react')" && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: 添加 TypeScript 类型到 types.ts**

在 `web/src/types.ts` 末尾追加：

```typescript
export interface KLineBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface KLineResponse {
  ticker: string
  range: string
  data: KLineBar[]
  error: string | null
}
```

- [ ] **Step 4: 添加 API 方法到 client.ts**

在 `web/src/api/client.ts` 的 `api` 对象中，在 `searchStocks` 方法后添加：

```typescript
  getKLine: (ticker: string, range = "1Y") =>
    http
      .get<KLineResponse>(`/kline/${encodeURIComponent(ticker)}`, { params: { range } })
      .then((r) => r.data),
```

同时在文件顶部的 import 行添加 `KLineResponse`：

```typescript
import type { Analysis, AnalysisListResponse, ProgressEvent, Settings,
  SettingsUpdate, ModelsResponse, Provider, TestResult, AggregateStats,
  KLineResponse } from "../types"
```

- [ ] **Step 5: 验证 TypeScript 编译**

```bash
cd web
npx tsc --noEmit
```

Expected: 无错误输出

- [ ] **Step 6: Commit**

```bash
cd ..
git add web/package.json web/package-lock.json web/src/types.ts web/src/api/client.ts
git commit -m "feat: add echarts dependency and kline API types"
```

---

## Task 4: useKLineData Hook

**Files:**
- Create: `web/src/hooks/useKLineData.ts`

- [ ] **Step 1: 创建 hook 文件**

```typescript
// web/src/hooks/useKLineData.ts
import { useState, useEffect, useRef } from "react"
import { api } from "../api/client"
import type { KLineBar } from "../types"

type TimeRange = "1M" | "3M" | "6M" | "1Y" | "2Y"

interface KLineState {
  data: KLineBar[]
  loading: boolean
  error: string | null
}

// Module-level cache: key = "TICKER-RANGE", value = KLineBar[]
const _cache = new Map<string, KLineBar[]>()

export function useKLineData(ticker: string, range: TimeRange): KLineState {
  const [state, setState] = useState<KLineState>({ data: [], loading: true, error: null })
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!ticker) return

    const cacheKey = `${ticker}-${range}`
    const cached = _cache.get(cacheKey)

    if (cached) {
      setState({ data: cached, loading: false, error: null })
      return
    }

    // Cancel any in-flight request for the previous range
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setState((s) => ({ ...s, loading: true, error: null }))

    api
      .getKLine(ticker, range)
      .then((resp) => {
        if (controller.signal.aborted) return
        if (resp.error && resp.data.length === 0) {
          setState({ data: [], loading: false, error: resp.error })
        } else {
          _cache.set(cacheKey, resp.data)
          setState({ data: resp.data, loading: false, error: resp.error })
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        setState({ data: [], loading: false, error: String(err) })
      })

    return () => controller.abort()
  }, [ticker, range])

  return state
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

```bash
cd web
npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 3: Commit**

```bash
cd ..
git add web/src/hooks/useKLineData.ts
git commit -m "feat: add useKLineData hook with in-memory cache and AbortController"
```

---

## Task 5: KLineModal 组件

**Files:**
- Create: `web/src/components/KLineModal.tsx`

- [ ] **Step 1: 创建指标计算工具函数（组件文件顶部）**

```typescript
// web/src/components/KLineModal.tsx
import { useEffect, useMemo, useState } from "react"
import ReactECharts from "echarts-for-react"
import { useKLineData } from "../hooks/useKLineData"
import type { KLineBar } from "../types"

type ChartType    = "candlestick" | "line"
type TimeRange    = "1M" | "3M" | "6M" | "1Y" | "2Y"
type SubIndicator = "MACD" | "KDJ" | "RSI"

// ── Indicator math ─────────────────────────────────────────────────────────────

function calcMA(closes: number[], n: number): (number | "-")[] {
  return closes.map((_, i) => {
    if (i < n - 1) return "-"
    const sum = closes.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0)
    return +(sum / n).toFixed(4)
  })
}

function calcEMA(vals: number[], n: number): number[] {
  const k = 2 / (n + 1)
  return vals.reduce<number[]>((acc, v, i) => {
    acc.push(i === 0 ? v : v * k + acc[i - 1] * (1 - k))
    return acc
  }, [])
}

function calcMACD(closes: number[]) {
  const dif = calcEMA(closes, 12).map((v, i) => +(v - calcEMA(closes, 26)[i]).toFixed(4))
  const dea = calcEMA(dif, 9).map((v) => +v.toFixed(4))
  const hist = dif.map((v, i) => +((v - dea[i]) * 2).toFixed(4))
  return { dif, dea, hist }
}

function calcKDJ(highs: number[], lows: number[], closes: number[]) {
  const k: number[] = [], d: number[] = [], j: number[] = []
  closes.forEach((c, i) => {
    const hh = Math.max(...highs.slice(Math.max(0, i - 8), i + 1))
    const ll = Math.min(...lows.slice(Math.max(0, i - 8), i + 1))
    const rsv = hh === ll ? 50 : ((c - ll) / (hh - ll)) * 100
    const pk = k[i - 1] ?? 50
    const pd = d[i - 1] ?? 50
    const ki = +(pk * (2 / 3) + rsv * (1 / 3)).toFixed(2)
    const di = +(pd * (2 / 3) + ki * (1 / 3)).toFixed(2)
    k.push(ki); d.push(di); j.push(+(3 * ki - 2 * di).toFixed(2))
  })
  return { k, d, j }
}

function calcRSI(closes: number[], n: number): (number | "-")[] {
  const out: (number | "-")[] = Array(n - 1).fill("-")
  for (let i = n - 1; i < closes.length; i++) {
    let gains = 0, losses = 0
    for (let s = i - n + 2; s <= i; s++) {
      const diff = closes[s] - closes[s - 1]
      if (diff > 0) gains += diff; else losses -= diff
    }
    const rs = losses === 0 ? Infinity : gains / losses
    out.push(+(100 - 100 / (1 + rs)).toFixed(2))
  }
  return out
}

function calcBoll(closes: number[], n = 20, mult = 2) {
  const upper: (number | "-")[] = []
  const mid: (number | "-")[] = []
  const lower: (number | "-")[] = []
  closes.forEach((_, i) => {
    if (i < n - 1) { upper.push("-"); mid.push("-"); lower.push("-"); return }
    const sl = closes.slice(i - n + 1, i + 1)
    const ma = sl.reduce((a, b) => a + b, 0) / n
    const std = Math.sqrt(sl.reduce((a, b) => a + (b - ma) ** 2, 0) / n)
    upper.push(+(ma + mult * std).toFixed(4))
    mid.push(+ma.toFixed(4))
    lower.push(+(ma - mult * std).toFixed(4))
  })
  return { upper, mid, lower }
}
```

- [ ] **Step 2: 创建 ECharts option 构建函数**

在同一文件中紧接上方代码追加：

```typescript
// ── ECharts option builder ─────────────────────────────────────────────────────

function buildOption(
  data: KLineBar[],
  chartType: ChartType,
  subIndicator: SubIndicator,
  showBoll: boolean,
  tradeDate: string,
) {
  const dates  = data.map((d) => d.date)
  const opens  = data.map((d) => d.open)
  const highs  = data.map((d) => d.high)
  const lows   = data.map((d) => d.low)
  const closes = data.map((d) => d.close)
  const vols   = data.map((d) => d.volume)

  // Candlestick format: [open, close, low, high]
  const candleData = data.map((d) => [d.open, d.close, d.low, d.high])

  const ma5  = calcMA(closes, 5)
  const ma10 = calcMA(closes, 10)
  const ma20 = calcMA(closes, 20)
  const ma60 = calcMA(closes, 60)

  const boll = showBoll ? calcBoll(closes) : null

  let subSeries: object[] = []
  if (subIndicator === "MACD") {
    const { dif, dea, hist } = calcMACD(closes)
    subSeries = [
      { name: "MACD", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: hist,
        itemStyle: { color: (p: any) => p.value >= 0 ? "#ef4444" : "#4ade80" } },
      { name: "DIF",  type: "line", xAxisIndex: 2, yAxisIndex: 2, data: dif,
        lineStyle: { color: "#4aaeff", width: 1 }, symbol: "none" },
      { name: "DEA",  type: "line", xAxisIndex: 2, yAxisIndex: 2, data: dea,
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
    ]
  } else if (subIndicator === "KDJ") {
    const { k, d, j } = calcKDJ(highs, lows, closes)
    subSeries = [
      { name: "K", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: k,
        lineStyle: { color: "#4aaeff", width: 1 }, symbol: "none" },
      { name: "D", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: d,
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
      { name: "J", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: j,
        lineStyle: { color: "#a78bfa", width: 1 }, symbol: "none" },
    ]
  } else {
    // RSI
    subSeries = [
      { name: "RSI6",  type: "line", xAxisIndex: 2, yAxisIndex: 2, data: calcRSI(closes, 6),
        lineStyle: { color: "#4aaeff", width: 1 }, symbol: "none" },
      { name: "RSI12", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: calcRSI(closes, 12),
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
      { name: "RSI24", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: calcRSI(closes, 24),
        lineStyle: { color: "#a78bfa", width: 1 }, symbol: "none" },
    ]
  }

  const mainSeries = chartType === "candlestick"
    ? {
        name: "K线", type: "candlestick", xAxisIndex: 0, yAxisIndex: 0, data: candleData,
        itemStyle: { color: "#ef4444", color0: "#4ade80", borderColor: "#ef4444", borderColor0: "#4ade80" },
        markLine: {
          symbol: "none",
          data: [{ xAxis: tradeDate }],
          lineStyle: { color: "#facc15", type: "dashed", width: 1.5 },
          label: { formatter: "分析日", color: "#facc15", position: "insideStartTop", fontSize: 10 },
        },
      }
    : {
        name: "收盘价", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: closes,
        lineStyle: { color: "#4aaeff", width: 1.5 }, symbol: "none",
        markLine: {
          symbol: "none",
          data: [{ xAxis: tradeDate }],
          lineStyle: { color: "#facc15", type: "dashed", width: 1.5 },
          label: { formatter: "分析日", color: "#facc15", position: "insideStartTop", fontSize: 10 },
        },
      }

  const bollSeries = boll
    ? [
        { name: "BOLL上", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: boll.upper,
          lineStyle: { color: "#888", width: 1 }, symbol: "none" },
        { name: "BOLL中", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: boll.mid,
          lineStyle: { color: "#aaa", width: 1, type: "dashed" }, symbol: "none" },
        { name: "BOLL下", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: boll.lower,
          lineStyle: { color: "#888", width: 1 }, symbol: "none" },
      ]
    : []

  const axisStyle = { axisLine: { lineStyle: { color: "#2a2a3a" } },
                      splitLine: { lineStyle: { color: "#1e1e2e" } },
                      axisLabel: { color: "#666", fontSize: 10 } }

  return {
    backgroundColor: "#0d0d17",
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" },
               backgroundColor: "#1e1e2e", borderColor: "#2a2a3a",
               textStyle: { color: "#ccc", fontSize: 11 } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: {
      top: 4, left: "center",
      data: ["MA5", "MA10", "MA20", "MA60"],
      textStyle: { color: "#888", fontSize: 10 },
      itemWidth: 12, itemHeight: 8,
    },
    grid: [
      { left: "6%", right: "1%", top: "6%",  height: "55%" },
      { left: "6%", right: "1%", top: "64%", height: "10%" },
      { left: "6%", right: "1%", top: "77%", height: "18%" },
    ],
    xAxis: [
      { type: "category", data: dates, gridIndex: 0, ...axisStyle, axisLabel: { show: false } },
      { type: "category", data: dates, gridIndex: 1, ...axisStyle, axisLabel: { show: false } },
      { type: "category", data: dates, gridIndex: 2, ...axisStyle },
    ],
    yAxis: [
      { gridIndex: 0, scale: true, ...axisStyle },
      { gridIndex: 1, ...axisStyle },
      { gridIndex: 2, scale: true, ...axisStyle },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1, 2], start: 50, end: 100 },
      { type: "slider", xAxisIndex: [0, 1, 2], bottom: 4, height: 16,
        borderColor: "#2a2a3a", textStyle: { color: "#555" },
        fillerColor: "rgba(74,172,255,0.08)", handleStyle: { color: "#4aaeff" } },
    ],
    series: [
      mainSeries,
      ...bollSeries,
      { name: "MA5",  type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma5,
        lineStyle: { color: "#facc15", width: 1 }, symbol: "none" },
      { name: "MA10", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma10,
        lineStyle: { color: "#f97316", width: 1 }, symbol: "none" },
      { name: "MA20", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma20,
        lineStyle: { color: "#a78bfa", width: 1 }, symbol: "none" },
      { name: "MA60", type: "line", xAxisIndex: 0, yAxisIndex: 0, data: ma60,
        lineStyle: { color: "#34d399", width: 1 }, symbol: "none" },
      { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: vols,
        itemStyle: { color: (p: any) => {
          const bar = data[p.dataIndex]
          return bar.close >= bar.open ? "#ef4444" : "#4ade80"
        }}},
      ...subSeries,
    ],
  }
}
```

- [ ] **Step 3: 创建 KLineModal 组件**

在同一文件中紧接上方追加：

```typescript
// ── Skeleton loader ────────────────────────────────────────────────────────────

function ChartSkeleton() {
  return (
    <div className="flex-1 flex flex-col gap-2 p-4 animate-pulse">
      <div className="bg-white/5 rounded h-[58%]" />
      <div className="bg-white/5 rounded h-[12%]" />
      <div className="bg-white/5 rounded h-[20%]" />
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

interface KLineModalProps {
  ticker: string
  tradeDate: string
  decision?: string | null
  onClose: () => void
}

const RANGES: TimeRange[] = ["1M", "3M", "6M", "1Y", "2Y"]
const SUB_INDICATORS: SubIndicator[] = ["MACD", "KDJ", "RSI"]

export function KLineModal({ ticker, tradeDate, decision, onClose }: KLineModalProps) {
  const [chartType, setChartType] = useState<ChartType>("candlestick")
  const [range, setRange]         = useState<TimeRange>("1Y")
  const [subInd, setSubInd]       = useState<SubIndicator>("MACD")
  const [showBoll, setShowBoll]   = useState(false)

  const { data, loading, error } = useKLineData(ticker, range)

  // ESC to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  const option = useMemo(
    () => (data.length > 0 ? buildOption(data, chartType, subInd, showBoll, tradeDate) : null),
    [data, chartType, subInd, showBoll, tradeDate],
  )

  const decisionColors: Record<string, string> = {
    BUY:  "text-green-400 bg-green-400/10 border-green-400/30",
    SELL: "text-red-400 bg-red-400/10 border-red-400/30",
    HOLD: "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0d0d17]">
      {/* ── Header ── */}
      <div className="bg-[#111827] border-b border-[#2a2a3a] px-4 py-2 flex flex-wrap items-center gap-2 shrink-0">
        {/* Left: ticker + decision */}
        <span className="font-bold text-white text-sm">{ticker}</span>
        {decision && (
          <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${decisionColors[decision] ?? ""}`}>
            {decision}
          </span>
        )}

        {/* Chart type toggle */}
        <div className="flex rounded overflow-hidden border border-[#2a2a3a] ml-2">
          {(["candlestick", "line"] as ChartType[]).map((ct) => (
            <button
              key={ct}
              onClick={() => setChartType(ct)}
              className={`text-xs px-2.5 py-1 transition-colors ${
                chartType === ct ? "bg-accent/20 text-accent" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {ct === "candlestick" ? "K线" : "折线"}
            </button>
          ))}
        </div>

        {/* Time range tabs */}
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`text-xs px-2.5 py-1 rounded transition-colors ${
                range === r
                  ? "bg-accent/20 text-accent border border-accent/30"
                  : "text-gray-500 hover:text-gray-300 border border-transparent"
              }`}
            >
              {r}
            </button>
          ))}
        </div>

        {/* Sub-indicator + BOLL toggle */}
        <div className="flex gap-1 ml-auto">
          {SUB_INDICATORS.map((s) => (
            <button
              key={s}
              onClick={() => setSubInd(s)}
              className={`text-xs px-2 py-1 rounded border transition-colors ${
                subInd === s
                  ? "border-accent/40 text-accent bg-accent/10"
                  : "border-[#2a2a3a] text-gray-500 hover:text-gray-300"
              }`}
            >
              {s}
            </button>
          ))}
          <button
            onClick={() => setShowBoll((b) => !b)}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              showBoll
                ? "border-accent/40 text-accent bg-accent/10"
                : "border-[#2a2a3a] text-gray-500 hover:text-gray-300"
            }`}
          >
            BOLL
          </button>
        </div>

        {/* Close */}
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-white transition-colors text-lg px-1 shrink-0"
          aria-label="关闭"
        >
          ✕
        </button>
      </div>

      {/* ── Chart area ── */}
      <div className="flex-1 overflow-hidden">
        {loading && <ChartSkeleton />}

        {!loading && error && (
          <div className="flex items-center justify-center h-full text-gray-500 text-sm">
            <div className="text-center">
              <p className="text-2xl mb-3">📭</p>
              <p>暂无K线数据</p>
              <p className="text-xs text-gray-600 mt-1">{error}</p>
            </div>
          </div>
        )}

        {!loading && !error && option && (
          <ReactECharts
            option={option}
            style={{ width: "100%", height: "100%" }}
            notMerge={true}
            lazyUpdate={false}
          />
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 验证 TypeScript 编译**

```bash
cd web
npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 5: Commit**

```bash
cd ..
git add web/src/components/KLineModal.tsx web/src/hooks/useKLineData.ts
git commit -m "feat: add KLineModal component with ECharts triple-pane chart"
```

---

## Task 6: 在 Report.tsx 添加按钮

**Files:**
- Modify: `web/src/pages/Report.tsx`

- [ ] **Step 1: 添加 import**

在 `web/src/pages/Report.tsx` 顶部 import 区（第 1-7 行之后）添加：

```typescript
import { KLineModal } from "../components/KLineModal"
```

- [ ] **Step 2: 在 AnalysisWorkspace 中添加状态**

在 `AnalysisWorkspace` 函数体内，紧接 `const [stopping, setStopping] = useState(false)` 后添加：

```typescript
const [showKLine, setShowKLine] = useState(false)
```

- [ ] **Step 3: 在顶部状态栏添加按钮**

在顶部状态栏 `div`（`className="bg-surface border-b..."`）中，找到 `{isRunning && !stopping && (` 这段停止按钮代码，在它**之前**插入 K线图按钮：

```tsx
{/* K线图按钮 — 始终显示 */}
<button
  onClick={() => setShowKLine(true)}
  className="ml-auto shrink-0 text-xs px-3 py-1 rounded border border-accent/40 text-accent hover:bg-accent/10 transition-colors"
>
  📈 K线图
</button>
```

注意：原来停止按钮的 `ml-auto` 改为无 `ml-auto`（K线图按钮接管了 `ml-auto`），整段按钮区变为：

```tsx
{/* K线图按钮 */}
<button
  onClick={() => setShowKLine(true)}
  className="ml-auto shrink-0 text-xs px-3 py-1 rounded border border-accent/40 text-accent hover:bg-accent/10 transition-colors"
>
  📈 K线图
</button>
{isRunning && !stopping && (
  <button
    onClick={handleStop}
    className="shrink-0 text-xs px-3 py-1 rounded border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-colors"
  >
    ■ 停止分析
  </button>
)}
{stopping && (
  <span className="text-xs text-gray-500">停止中…</span>
)}
```

- [ ] **Step 4: 在 return 中挂载 Modal**

在 `AnalysisWorkspace` 的 `return` 语句中，`</div>` 最外层闭合标签前添加：

```tsx
{showKLine && (
  <KLineModal
    ticker={analysis.ticker}
    tradeDate={analysis.trade_date}
    decision={analysis.decision}
    onClose={() => setShowKLine(false)}
  />
)}
```

完整 return 结构变为：

```tsx
return (
  <div className="flex flex-col h-screen">
    {/* Top status bar */}
    <div className="bg-surface border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
      {/* ...existing content... */}
      {/* K线图按钮 */}
      <button onClick={() => setShowKLine(true)} className="ml-auto shrink-0 text-xs px-3 py-1 rounded border border-accent/40 text-accent hover:bg-accent/10 transition-colors">
        📈 K线图
      </button>
      {isRunning && !stopping && (
        <button onClick={handleStop} className="shrink-0 text-xs px-3 py-1 rounded border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-colors">
          ■ 停止分析
        </button>
      )}
      {stopping && <span className="text-xs text-gray-500">停止中…</span>}
    </div>

    <div className="flex flex-1 overflow-hidden">
      {/* ...existing left + right panels... */}
    </div>

    {showKLine && (
      <KLineModal
        ticker={analysis.ticker}
        tradeDate={analysis.trade_date}
        decision={analysis.decision}
        onClose={() => setShowKLine(false)}
      />
    )}
  </div>
)
```

- [ ] **Step 5: 验证 TypeScript 编译**

```bash
cd web
npx tsc --noEmit
```

Expected: 无错误

- [ ] **Step 6: 启动开发服务器并手动验证**

```bash
# Terminal 1: backend
uvicorn server.main:app --reload

# Terminal 2: frontend
cd web && npm run dev
```

打开 `http://localhost:5173`，进入任意分析报告：
- 确认顶部状态栏右侧出现 **📈 K线图** 按钮
- 点击后全屏弹窗打开，显示骨架屏（加载中）
- 数据加载完成后出现 ECharts 三联图（主图 + 成交量 + MACD）
- 切换 1M/3M/6M/1Y/2Y 范围 — 图表更新（第一次需要请求，后续从缓存读取）
- 切换 K线/折线 — 主图图表类型切换
- 点击 MACD/KDJ/RSI — 副图切换
- 点击 BOLL — 主图叠加布林带
- 分析日期处有黄色虚线标记
- 按 ESC 或点击 ✕ — 弹窗关闭
- 对于无效 ticker（如 "FAKE.ZZ"）— 弹窗显示"暂无K线数据"提示

- [ ] **Step 7: Commit**

```bash
cd ..
git add web/src/pages/Report.tsx
git commit -m "feat: add K线图 button to report toolbar, opens KLineModal"
```

---

## 自查清单（执行前检查）

- [ ] `server/routers/kline.py` 中所有数据源函数对应的 import 均被 try/except 包裹（避免缺包导致整个后端崩溃）
- [ ] `_fetch_baostock` 依赖 `_bs_session` 上下文管理器，确认已从 `baostock_data` 导入
- [ ] `_fetch_joinquant` 依赖 `_JQ_LOCK` 和 `_ensure_auth`，确认已从 `jq_data` 导入
- [ ] `echarts-for-react` 的 `ReactECharts` 默认导出正确（`import ReactECharts from 'echarts-for-react'`）
- [ ] `KLineModal` 使用 `fixed inset-0 z-50` 确保覆盖整个视口
- [ ] `ml-auto` 从停止按钮移到 K线图按钮，避免布局错乱
