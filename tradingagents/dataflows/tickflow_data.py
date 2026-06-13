"""TickFlow data provider for A-share, HK, and US markets.

TickFlow (https://tickflow.org) is a RESTful market-data service covering
A-shares (沪深京), ETFs, indices, US and HK markets. Unlike East Money's public
endpoints it is authenticated and not IP-rate-limited per-scrape, which makes it
a stable data source for server-side batch jobs such as the stock screener.

Auth: every request carries an ``x-api-key`` header.
Configure via the ``TICKFLOW_API_KEY`` environment variable.

Ticker format conventions (Yahoo Finance style → TickFlow format):
  A-share Shanghai: 600519.SS → 600519.SH
  A-share Shenzhen: 000001.SZ → 000001.SZ
  HK stocks:      0700.HK   → 00700.HK
  US stocks:      AAPL      → AAPL.US

Docs: https://docs.tickflow.org/zh-Hans
"""
from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime
from typing import Annotated, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tickflow.org/v1"
_TIMEOUT = 30


# ── Auth & session ─────────────────────────────────────────────────────────────

def _api_key() -> str:
    """Read API key dynamically so .env changes take effect without restart."""
    return os.getenv("TICKFLOW_API_KEY", "").strip()


_SESSION = None
_SESSION_LOCK = __import__("threading").Lock()


def _session():
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            s = requests.Session()
            s.headers.update({"x-api-key": _api_key()})
            s.trust_env = False  # bypass system proxy
            _SESSION = s
        else:
            # Refresh API key on each call
            _SESSION.headers["x-api-key"] = _api_key()
        return _SESSION


class TickFlowError(Exception):
    """Raised when TickFlow API fails — triggers vendor fallback."""
    pass


# ── Ticker conversion ──────────────────────────────────────────────────────────

def _to_tf_code(ticker: str) -> str:
    """Convert Yahoo Finance ticker to TickFlow format.

    600519.SS → 600519.SH   (Shanghai: .SS → .SH)
    000001.SZ → 000001.SZ   (Shenzhen: unchanged)
    513180.SZ → 513180.SH   (auto-correct: Shanghai ETF mis-labelled as SZ)
    0700.HK   → 00700.HK    (HK: pad to 5 digits)
    AAPL      → AAPL.US     (US: append .US)
    """
    from .stockstats_utils import fix_cn_exchange
    t = fix_cn_exchange(ticker).upper().strip()
    if t.endswith(".SS"):
        return t[:-3] + ".SH"
    if t.endswith(".HK"):
        code = t[:-3].zfill(5)
        return f"{code}.HK"
    if t.endswith(".SZ"):
        return t  # .SZ stays as-is
    # US stock (no suffix)
    return f"{t}.US"


def _from_tf_code(tf_symbol: str) -> str:
    """Convert TickFlow symbol back to Yahoo Finance format."""
    parts = tf_symbol.split(".")
    if len(parts) != 2:
        return tf_symbol
    code, exchange = parts
    if exchange == "SH":
        return f"{code}.SS"
    if exchange == "SZ":
        return f"{code}.SZ"
    if exchange == "HK":
        return f"{code.lstrip('0')}.HK" if code.lstrip('0') else f"{code}.HK"
    if exchange == "US":
        return code  # US: no suffix
    return tf_symbol


# ── Generic request helper ─────────────────────────────────────────────────────

_MAX_RETRIES = 4


def _request(method: str, path: str, *, params: dict = None, json_body: dict = None):
    """Issue a TickFlow request with retry on 429 / transient network errors.

    Raises TickFlowError on auth failure, non-retryable status, or after the
    retry budget is exhausted. 429 and network errors back off exponentially —
    this lets the whole-market screener fan out hundreds of batch calls without a
    single rate-limit blip aborting the run.
    """
    key = _api_key()
    if not key:
        raise TickFlowError(
            "TICKFLOW_API_KEY not set. "
            "Get an API key at tickflow.org and add TICKFLOW_API_KEY=xxx to .env"
        )
    url = f"{BASE_URL}/{path.lstrip('/')}"
    last: Optional[TickFlowError] = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = _session().request(method, url, params=params, json=json_body,
                                   timeout=_TIMEOUT)
        except requests.RequestException as e:
            last = TickFlowError(f"TickFlow request failed: {e}")
            time.sleep(min(8.0, 1.0 * 2 ** attempt) + random.uniform(0.2, 0.8))
            continue
        if r.status_code in (401, 403):
            raise TickFlowError(f"TickFlow API key invalid/forbidden "
                                f"(HTTP {r.status_code}): {r.text[:120]}")
        if r.status_code == 429:
            last = TickFlowError("TickFlow rate limited (HTTP 429)")
            time.sleep(min(10.0, 1.5 * 2 ** attempt) + random.uniform(0.3, 1.0))
            continue
        if r.status_code != 200:
            raise TickFlowError(f"TickFlow HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise TickFlowError(f"TickFlow bad JSON response: {e}") from e
    raise last or TickFlowError("TickFlow request failed (retries exhausted)")


def _get(path: str, params: dict = None):
    """GET request to TickFlow API (retried). Raises TickFlowError on failure."""
    return _request("GET", path, params=params)


def _ts_to_date(ts_ms: int) -> str:
    """Convert millisecond timestamp to YYYY-MM-DD."""
    return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


# ── Price / OHLCV ──────────────────────────────────────────────────────────────

def get_tf_stock_data(
    symbol: Annotated[str, "ticker in Yahoo Finance format, e.g. 600519.SS"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get A-share daily OHLCV data from TickFlow (前复权, forward-adjusted)."""
    try:
        import pandas as pd
    except ImportError:
        raise TickFlowError("pandas is required for TickFlow data")

    tf_code = _to_tf_code(symbol)
    # Convert dates to millisecond timestamps
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000) + 86399999

    resp = _get("klines", {
        "symbol": tf_code,
        "period": "1d",
        "start_time": start_ts,
        "end_time": end_ts,
        "adjust": "forward",
    })

    data = resp.get("data", {})
    if not data:
        return f"No data for {symbol} between {start_date} and {end_date}"

    # TickFlow returns arrays: timestamp, open, high, low, close, volume, amount
    rows = []
    for i, ts in enumerate(data.get("timestamp", [])):
        date_str = _ts_to_date(ts)
        if date_str < start_date or date_str > end_date:
            continue
        rows.append({
            "Date": date_str,
            "Open": data["open"][i] if i < len(data.get("open", [])) else None,
            "High": data["high"][i] if i < len(data.get("high", [])) else None,
            "Low": data["low"][i] if i < len(data.get("low", [])) else None,
            "Close": data["close"][i] if i < len(data.get("close", [])) else None,
            "Volume": data["volume"][i] if i < len(data.get("volume", [])) else None,
            "Turnover(CNY)": data["amount"][i] if i < len(data.get("amount", [])) else None,
            "PrevClose": data["prev_close"][i] if i < len(data.get("prev_close", [])) else None,
        })

    if not rows:
        return f"No data for {symbol} between {start_date} and {end_date}"

    df = pd.DataFrame(rows)
    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Source: TickFlow | Currency: CNY | Adjusted: 前复权 (forward)\n"
        f"# Records: {len(df)} | Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv(index=False)


# ── Technical indicators (stockstats on TickFlow OHLCV) ───────────────────────

def get_tf_indicators(
    symbol: Annotated[str, "ticker in Yahoo Finance format"],
    indicator: Annotated[str, "technical indicator e.g. rsi, close_50_sma, macd"],
    curr_date: Annotated[str, "current trading date YYYY-MM-DD"],
    look_back_days: Annotated[int, "calendar days to look back"] = 60,
) -> str:
    """Compute technical indicators via TickFlow OHLCV + stockstats."""
    try:
        import pandas as pd
        from stockstats import wrap
        from dateutil.relativedelta import relativedelta as rdelta
    except ImportError as e:
        raise TickFlowError(f"Missing dependency: {e}")

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - rdelta(years=1)  # need ~1 year for slow indicators
    tf_code = _to_tf_code(symbol)

    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(curr_dt.timestamp() * 1000) + 86399999

    resp = _get("klines", {
        "symbol": tf_code,
        "period": "1d",
        "start_time": start_ts,
        "end_time": end_ts,
        "adjust": "forward",
    })

    data = resp.get("data", {})
    if not data or not data.get("timestamp"):
        raise TickFlowError(f"No OHLCV data for {symbol}")

    rows = []
    for i, ts in enumerate(data["timestamp"]):
        date_str = _ts_to_date(ts)
        if date_str > curr_date:
            continue
        rows.append({
            "date": pd.to_datetime(date_str),
            "open": float(data.get("open", [])[i] or 0),
            "high": float(data.get("high", [])[i] or 0),
            "low": float(data.get("low", [])[i] or 0),
            "close": float(data.get("close", [])[i] or 0),
            "volume": float(data.get("volume", [])[i] or 0),
        })

    if not rows:
        raise TickFlowError(f"No OHLCV data for {symbol} up to {curr_date}")

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["Date"] = df["date"].dt.strftime("%Y-%m-%d")

    stock = wrap(df)
    stock[indicator]

    result_dict = {
        row["Date"]: ("N/A" if pd.isna(row.get(indicator)) else str(round(float(row[indicator]), 4)))
        for _, row in stock.iterrows()
    }

    before = curr_dt - rdelta(days=look_back_days)
    lines, d = [], curr_dt
    while d >= before:
        ds = d.strftime("%Y-%m-%d")
        lines.append(f"{ds}: {result_dict.get(ds, 'N/A: Not a trading day')}")
        d -= rdelta(days=1)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
    )


# ── Fundamentals (real-time quote snapshot) ────────────────────────────────────

def get_tf_fundamentals(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Get current valuation snapshot from TickFlow real-time quote.

    Includes PE/PB/market cap from the quote ``ext`` object.
    """
    tf_code = _to_tf_code(ticker)
    resp = _post("quotes", {"symbols": [tf_code]})
    data = resp.get("data", [])
    if not data:
        raise TickFlowError(f"No quote data for {ticker}")

    item = data[0]
    ext = item.get("ext") or {}
    lines = [
        f"# Market Snapshot for {ticker.upper()} (TickFlow)",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"Latest Close:  {item.get('last_price', 'N/A')}",
        f"Previous Close:{item.get('prev_close', 'N/A')}",
        f"Open:          {item.get('open', 'N/A')}",
        f"High:          {item.get('high', 'N/A')}",
        f"Low:           {item.get('low', 'N/A')}",
        f"Volume:        {item.get('volume', 'N/A')}",
        f"Turnover:      {item.get('amount', 'N/A')}",
        f"Change %:      {ext.get('change_pct', 'N/A')}",
        f"Amplitude:     {ext.get('amplitude', 'N/A')}",
        f"Turnover Rate: {ext.get('turnover_rate', 'N/A')}",
    ]

    # Try to add PE/PB from financial metrics endpoint
    try:
        metrics_resp = _get("financials/metrics", {"symbols": tf_code, "latest": "true"})
        mdata = metrics_resp.get("data", {}).get(tf_code, [])
        if mdata:
            m = mdata[0]
            lines += [
                "",
                "# Latest Financial Metrics",
                f"ROE:           {m.get('roe', 'N/A')}",
                f"ROA:           {m.get('roa', 'N/A')}",
                f"Net Margin:    {m.get('net_margin', 'N/A')}",
                f"Gross Margin:  {m.get('gross_margin', 'N/A')}",
                f"EPS Basic:     {m.get('eps_basic', 'N/A')}",
                f"BPS:           {m.get('bps', 'N/A')}",
                f"Revenue YoY:   {m.get('revenue_yoy', 'N/A')}",
                f"Net Income YoY:{m.get('net_income_yoy', 'N/A')}",
            ]
    except Exception as e:
        logger.debug("TickFlow financials/metrics failed for %s: %s", ticker, e)

    return "\n".join(lines)


# ── Balance Sheet ──────────────────────────────────────────────────────────────

def get_tf_balance_sheet(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    """Get balance sheet (资产负债表) from TickFlow."""
    try:
        import pandas as pd
    except ImportError:
        raise TickFlowError("pandas is required")

    tf_code = _to_tf_code(ticker)
    params = {"symbols": tf_code}
    if curr_date:
        # Query up to the given date
        params["end_date"] = curr_date
        params["latest"] = "true"
    else:
        params["latest"] = "true"

    resp = _get("financials/balance-sheet", params)
    items = resp.get("data", {}).get(tf_code, [])
    if not items:
        raise TickFlowError(f"No balance sheet data for {ticker}")

    df = pd.DataFrame(items)
    header = (
        f"# Balance Sheet (资产负债表) for {ticker.upper()}\n"
        f"# Source: TickFlow | Records: {len(df)}\n\n"
    )
    return header + df.to_csv(index=False)


# ── Income Statement ───────────────────────────────────────────────────────────

def get_tf_income_statement(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    """Get income statement (利润表) from TickFlow."""
    try:
        import pandas as pd
    except ImportError:
        raise TickFlowError("pandas is required")

    tf_code = _to_tf_code(ticker)
    params = {"symbols": tf_code}
    if curr_date:
        params["end_date"] = curr_date
        params["latest"] = "true"
    else:
        params["latest"] = "true"

    resp = _get("financials/income", params)
    items = resp.get("data", {}).get(tf_code, [])
    if not items:
        raise TickFlowError(f"No income statement data for {ticker}")

    df = pd.DataFrame(items)
    header = (
        f"# Income Statement (利润表) for {ticker.upper()}\n"
        f"# Source: TickFlow | Records: {len(df)}\n\n"
    )
    return header + df.to_csv(index=False)


# ── Cash Flow Statement ────────────────────────────────────────────────────────

def get_tf_cashflow(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    """Get cash flow statement (现金流量表) from TickFlow."""
    try:
        import pandas as pd
    except ImportError:
        raise TickFlowError("pandas is required")

    tf_code = _to_tf_code(ticker)
    params = {"symbols": tf_code}
    if curr_date:
        params["end_date"] = curr_date
        params["latest"] = "true"
    else:
        params["latest"] = "true"

    resp = _get("financials/cash-flow", params)
    items = resp.get("data", {}).get(tf_code, [])
    if not items:
        raise TickFlowError(f"No cash flow data for {ticker}")

    df = pd.DataFrame(items)
    header = (
        f"# Cash Flow Statement (现金流量表) for {ticker.upper()}\n"
        f"# Source: TickFlow | Records: {len(df)}\n\n"
    )
    return header + df.to_csv(index=False)


# ── Stock detail aggregator (single-call payload for the detail page) ─────────

def get_tf_stock_detail(ticker: str, kline_days: int = 90,
                        history_quarters: int = 8) -> dict:
    """Aggregate everything a single-stock detail page needs from TickFlow.

    Returns a structured dict (not a CSV-ish string like the analyst-facing
    getters above) so the frontend can render it without re-parsing:

        {
          quote:       {last_price, prev_close, open, high, low, volume, amount,
                        change_pct, amplitude, turnover_rate, name, code, symbol},
          metrics:     [ {period_end, roe, roa, net_margin, gross_margin,
                          eps_basic, bps, revenue_yoy, net_income_yoy, ...}, ...],
          balance:     [ latest 4 records, newest first ],
          income:      [ latest 4 records, newest first ],
          cashflow:    [ latest 4 records, newest first ],
          klines:      [ {date, open, high, low, close, volume, amount}, ...],
          errors:      [ "section: reason", ... ]  # only non-fatal section errors
        }

    Each section is wrapped in its own try/except so a single TickFlow blip
    on one endpoint doesn't blank out the whole detail page.
    """
    tf_code = _to_tf_code(ticker)
    out: dict = {
        "ticker": ticker.upper(),
        "tf_code": tf_code,
        "errors": [],
    }

    # 1) Real-time quote
    try:
        resp = _post("quotes", {"symbols": [tf_code]})
        items = resp.get("data") or []
        if items:
            it = items[0]
            ext = it.get("ext") or {}
            out["quote"] = {
                "symbol": it.get("symbol"),
                "code": tf_code.split(".")[0],
                "name": ext.get("name"),
                "last_price": it.get("last_price"),
                "prev_close": it.get("prev_close"),
                "open":       it.get("open"),
                "high":       it.get("high"),
                "low":        it.get("low"),
                "volume":     it.get("volume"),
                "amount":     it.get("amount"),
                "change_pct":   ext.get("change_pct"),
                "amplitude":    ext.get("amplitude"),
                "turnover_rate": ext.get("turnover_rate"),
                "total_mktcap":  ext.get("total_mktcap") or ext.get("mktcap"),
                "float_mktcap":  ext.get("float_mktcap"),
                "pe":  ext.get("pe"),
                "pb":  ext.get("pb"),
            }
        else:
            out["errors"].append("quote: empty")
    except Exception as e:
        out["errors"].append(f"quote: {e}")

    # 2) Financial metrics history (recent N quarters)
    try:
        start = (datetime.now() - __import__("datetime").timedelta(
            days=int(history_quarters * 95))).strftime("%Y%m%d")
        resp = _get("financials/metrics", {"symbols": tf_code, "start_date": start})
        recs = (resp.get("data") or {}).get(tf_code, []) or []
        recs = sorted(recs, key=lambda r: r.get("period_end") or "", reverse=True)
        out["metrics"] = recs[:history_quarters]
    except Exception as e:
        out["errors"].append(f"metrics: {e}")
        out["metrics"] = []

    # 3-5) Three statements (latest 4 periods each)
    for sname, path in (("balance",  "financials/balance-sheet"),
                        ("income",   "financials/income"),
                        ("cashflow", "financials/cash-flow")):
        try:
            start = (datetime.now() - __import__("datetime").timedelta(
                days=int(history_quarters * 95))).strftime("%Y%m%d")
            resp = _get(path, {"symbols": tf_code, "start_date": start})
            recs = (resp.get("data") or {}).get(tf_code, []) or []
            recs = sorted(recs, key=lambda r: r.get("period_end") or "", reverse=True)
            out[sname] = recs[:4]
        except Exception as e:
            out["errors"].append(f"{sname}: {e}")
            out[sname] = []

    # 6) Recent K-lines
    try:
        end_dt = datetime.now()
        start_dt = end_dt - __import__("datetime").timedelta(days=int(kline_days * 1.6))
        resp = _get("klines", {
            "symbol": tf_code, "period": "1d",
            "start_time": int(start_dt.timestamp() * 1000),
            "end_time":   int(end_dt.timestamp() * 1000) + 86399999,
            "adjust": "forward",
        })
        data = resp.get("data") or {}
        bars = []
        for i, ts in enumerate(data.get("timestamp", [])):
            bars.append({
                "date": _ts_to_date(ts),
                "open": data.get("open", [None])[i] if i < len(data.get("open", [])) else None,
                "high": data.get("high", [None])[i] if i < len(data.get("high", [])) else None,
                "low":  data.get("low",  [None])[i] if i < len(data.get("low",  [])) else None,
                "close": data.get("close", [None])[i] if i < len(data.get("close", [])) else None,
                "volume": data.get("volume", [None])[i] if i < len(data.get("volume", [])) else None,
                "amount": data.get("amount", [None])[i] if i < len(data.get("amount", [])) else None,
            })
        # Keep only the most recent N trading days
        out["klines"] = bars[-kline_days:] if bars else []
    except Exception as e:
        out["errors"].append(f"klines: {e}")
        out["klines"] = []

    return out


# ── Connection test ────────────────────────────────────────────────────────────

def test_tf_connection(api_key: Optional[str] = None) -> dict:
    """Probe TickFlow connectivity.

    Returns: {connected: bool, latency_ms?: int, universe_count?: int, error?: str}
    """
    key = (api_key or _api_key()).strip()
    if not key:
        return {"connected": False, "error": "未配置 TickFlow API Key"}

    try:
        import httpx
    except ImportError:
        return {"connected": False, "error": "httpx 未安装"}

    start = time.time()
    try:
        with httpx.Client(trust_env=False, timeout=12) as client:
            resp = client.get(f"{BASE_URL}/universes", headers={"x-api-key": key})
        latency_ms = int((time.time() - start) * 1000)
    except Exception as exc:
        return {"connected": False, "error": f"网络请求失败: {exc}"[:200]}

    if resp.status_code == 401 or resp.status_code == 403:
        return {"connected": False, "latency_ms": latency_ms,
                "error": "API Key 无效或无权限 (HTTP %d)" % resp.status_code}
    if resp.status_code == 429:
        return {"connected": True, "latency_ms": latency_ms,
                "error": "请求频率受限 (HTTP 429)，但 Key 有效"}
    if resp.status_code != 200:
        return {"connected": False, "latency_ms": latency_ms,
                "error": "HTTP %d: %s" % (resp.status_code, resp.text[:120])}

    try:
        data = resp.json().get("data", [])
        count = len(data) if isinstance(data, list) else None
    except Exception:
        count = None

    return {"connected": True, "latency_ms": latency_ms, "universe_count": count}


# Alias for settings.py import compatibility
test_tickflow_connection = test_tf_connection


# ── Batch helpers for sector_data.py ───────────────────────────────────────────
#
# NOTE on symbol formats: ``tf_instruments`` and ``tf_financials_valuation`` take
# TickFlow-format symbols (e.g. "600519.SH"), matching the
# ``tf_universe_symbols()`` output used for whole-market snapshots. The
# single-ticker helpers above (``tf_batch_quotes``, ``tf_batch_klines``, etc.)
# take Yahoo Finance format (e.g. "600519.SS") and convert internally via
# ``_to_tf_code``. Do not mix the two — passing Yahoo-format symbols to the
# functions below will silently mis-key results.

def _post(path: str, body: dict):
    """POST request to TickFlow API (retried). Raises TickFlowError on failure."""
    return _request("POST", path, json_body=body)


# TickFlow Expert batch limits (按标的查询): financials 100/req, instruments ≥200/req.
_FIN_BATCH = 100
_INSTR_BATCH = 200


def tf_instruments(tf_symbols: list[str]) -> dict:
    """Batch instrument metadata. Returns {6-digit code: {total_shares, float_shares, name}}.

    ``tf_symbols`` are TickFlow-format symbols (e.g. "600519.SH"). Tolerant of
    partial failure: a batch that errors after retries is logged and skipped so a
    single transient blip doesn't sink the whole whole-market enrichment.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(tf_symbols), _INSTR_BATCH):
        chunk = tf_symbols[i:i + _INSTR_BATCH]
        try:
            resp = _post("instruments", {"symbols": chunk})
        except TickFlowError as e:
            logger.warning("tf_instruments: batch %d skipped (%s)", i // _INSTR_BATCH, e)
            continue
        for item in resp.get("data", []) or []:
            # Key by the symbol's 6-digit prefix — TickFlow's ``code`` field is not
            # reliably unique across the universe (collapses ~5500 → ~2900).
            six = item.get("symbol", "").split(".")[0].zfill(6)
            if not six.isdigit():
                continue
            ext = item.get("ext") or {}
            out[six] = {
                "total_shares": ext.get("total_shares"),
                "float_shares": ext.get("float_shares"),
                "name": item.get("name", ""),
            }
    return out


def _eps_ttm(records: list[dict]) -> Optional[float]:
    """Compute trailing-twelve-month EPS from a series of cumulative-YTD reports.

    Chinese quarterly EPS is cumulative within the fiscal year, so:
      TTM = latest_YTD + prior_full_year − prior_year_same_period_YTD
    Falls back to the most recent annual (FY) EPS, then to annualising the latest
    YTD figure, then None. ``records`` is any unordered list of period dicts with
    ``period_end`` (YYYY-MM-DD) and ``eps_basic``.
    """
    recs = [r for r in records if r.get("period_end") and r.get("eps_basic") is not None]
    if not recs:
        return None
    recs.sort(key=lambda r: r["period_end"])
    latest = recs[-1]
    pe = str(latest["period_end"])
    try:
        year, month = int(pe[:4]), int(pe[5:7])
        eps_latest = float(latest["eps_basic"])
    except (ValueError, TypeError):
        return None

    by_period = {str(r["period_end"]): float(r["eps_basic"]) for r in recs}
    if month == 12:                       # latest report is a full year
        return eps_latest
    prior_fy = by_period.get(f"{year - 1}-12-31")
    prior_same = by_period.get(f"{year - 1}-{pe[5:10]}")
    if prior_fy is not None and prior_same is not None:
        return eps_latest + prior_fy - prior_same
    # Fall back to the most recent available full-year EPS (static), else annualise.
    fy = [r for r in recs if str(r["period_end"]).endswith("-12-31")]
    if fy:
        return float(fy[-1]["eps_basic"])
    quarter = {3: 1, 6: 2, 9: 3}.get(month)
    return eps_latest * (4.0 / quarter) if quarter else None


def tf_financials_valuation(tf_symbols: list[str], start_year: int = None) -> dict:
    """Batch financials sufficient to value each stock: latest BPS/ROE + TTM EPS.

    Returns {6-digit code: {bps, roe, eps_ttm, period_end}}. ``tf_symbols`` are
    TickFlow-format symbols. Fetches the last ~5 reporting periods (via
    ``start_date``) so a true rolling EPS can be computed — see :func:`_eps_ttm`.
    Tolerant of partial batch failure.
    """
    if start_year is None:
        start_year = datetime.now().year - 1
    start_date = f"{start_year}0101"
    out: dict[str, dict] = {}
    for i in range(0, len(tf_symbols), _FIN_BATCH):
        chunk = tf_symbols[i:i + _FIN_BATCH]
        try:
            resp = _get("financials/metrics",
                        {"symbols": ",".join(chunk), "start_date": start_date})
        except TickFlowError as e:
            logger.warning("tf_financials_valuation: batch %d skipped (%s)",
                           i // _FIN_BATCH, e)
            continue
        for sym, records in (resp.get("data") or {}).items():
            if not records:
                continue
            recs = sorted(records, key=lambda r: r.get("period_end") or "")
            latest = recs[-1]
            six = sym.split(".")[0].zfill(6)
            out[six] = {
                "bps": latest.get("bps"),
                "roe": latest.get("roe"),
                "eps_ttm": _eps_ttm(records),
                "period_end": latest.get("period_end"),
            }
    return out


def tf_batch_quotes(symbols: list[str]) -> dict:
    """Batch real-time quotes for multiple tickers (Yahoo Finance format).

    **Warning**: TickFlow limits `symbols` to 5 per request. For whole-market
    snapshots use :func:`tf_universe_quotes` instead.
    """
    if not symbols:
        return {}
    tf_codes = [_to_tf_code(s) for s in symbols]
    resp = _post("quotes", {"symbols": tf_codes})
    out: dict[str, dict] = {}
    for item in resp.get("data", []):
        sym = item.get("symbol", "")
        yf_code = _from_tf_code(sym)
        six = yf_code.split(".")[0]  # 6-digit code
        ext = item.get("ext") or {}
        out[six] = {
            "code": six,
            "name": ext.get("name", ""),
            "price": item.get("last_price"),
            "pct_change": ext.get("change_pct"),
            "amount": item.get("amount"),
            "volume": item.get("volume"),
            "turnover": ext.get("turnover_rate"),
            "prev_close": item.get("prev_close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
        }
    return out


def tf_batch_klines(symbols: list[str], period: str = "1d",
                    count: int = 100, adjust: str = "forward") -> dict:
    """Batch K-line data for multiple tickers.

    Returns dict keyed by 6-digit code with OHLCV arrays.
    """
    if not symbols:
        return {}
    tf_codes = ",".join([_to_tf_code(s) for s in symbols])
    resp = _get("klines/batch", {
        "symbols": tf_codes,
        "period": period,
        "count": count,
        "adjust": adjust,
    })
    out: dict[str, dict] = {}
    for tf_sym, kdata in resp.get("data", {}).items():
        six = _from_tf_code(tf_sym).split(".")[0]
        out[six] = kdata
    return out


def tf_universes() -> list[dict]:
    """List all available universes (标的池).

    Returns list of {id, name, region, category, symbol_count, description}.
    """
    resp = _get("universes")
    return resp.get("data", [])


def tf_universe_symbols(universe_ids: list[str]) -> list[str]:
    """Fetch symbols from multiple TickFlow universes in a **single quotes request**.

    Much faster than calling ``tf_universe_detail`` per-fragment. Uses
    ``POST /v1/quotes`` with ``universes`` param — TickFlow returns all
    symbols across the specified universes with current quotes attached.

    Parameters
    ----------
    universe_ids : list[str]
        TickFlow universe IDs, e.g. ``["CN_Equity_SW1_480401", "CN_Equity_SW1_480501"]``.

    Returns
    -------
    list[str]
        Unique TickFlow-format symbols (e.g. ``["600519.SH", "000001.SZ", ...]``).
    """
    if not universe_ids:
        return []
    resp = _post("quotes", {"universes": universe_ids})
    symbols = []
    seen = set()
    for item in resp.get("data", []) or []:
        sym = item.get("symbol", "")
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    return symbols


