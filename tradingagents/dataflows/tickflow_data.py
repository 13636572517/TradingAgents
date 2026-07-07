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
from datetime import datetime, timedelta
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

def _parse_kline_arrays(data: dict, start_date: Optional[str] = None,
                         end_date: Optional[str] = None) -> list[dict]:
    """Convert a TickFlow kline ``data`` object (parallel arrays keyed by
    ``timestamp``/``open``/.../``prev_close``) into a list of bar dicts,
    optionally filtered to ``[start_date, end_date]``."""
    if not data or not data.get("timestamp"):
        return []
    bars = []
    for i, ts in enumerate(data["timestamp"]):
        date_str = _ts_to_date(ts)
        if start_date and date_str < start_date:
            continue
        if end_date and date_str > end_date:
            continue
        bars.append({
            "date": date_str,
            "open": data["open"][i] if i < len(data.get("open", [])) else None,
            "high": data["high"][i] if i < len(data.get("high", [])) else None,
            "low": data["low"][i] if i < len(data.get("low", [])) else None,
            "close": data["close"][i] if i < len(data.get("close", [])) else None,
            "volume": data["volume"][i] if i < len(data.get("volume", [])) else None,
            "amount": data["amount"][i] if i < len(data.get("amount", [])) else None,
            "prev_close": data["prev_close"][i] if i < len(data.get("prev_close", [])) else None,
        })
    return bars


def _fetch_klines_raw(tf_code: str, start_date: str, end_date: str,
                       adjust: str = "forward") -> list[dict]:
    """Pull raw OHLCV bars from TickFlow for [start_date, end_date]. No cache."""
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000) + 86399999
    resp = _get("klines", {
        "symbol": tf_code, "period": "1d",
        "start_time": start_ts, "end_time": end_ts, "adjust": adjust,
    })
    return _parse_kline_arrays(resp.get("data", {}), start_date, end_date)


def _load_ohlcv_cached(tf_code: str, start_date: str, end_date: str,
                        adjust: str = "forward") -> list[dict]:
    """Return bars for [start_date, end_date], reading from the local cache and
    only hitting TickFlow for the gaps we don't have yet.

    Historical bars never change, so once fetched they're cached forever. A
    symbol's cache can have gaps on *both* ends relative to what's requested:

      - forward gap:  (cached_max, end_date] — e.g. today's bar hasn't landed yet.
      - backward gap: [start_date, cached_min) — e.g. the symbol was first
        warmed by a short range (nightly backfill pulls 5 days) and a later
        call asks for a much wider history (1Y/2Y chart).

    Both gaps are fetched and merged into the cache before reading back the
    requested range.
    """
    from . import cache_store

    cached_min = cache_store.get_min_ohlcv_date(tf_code, adjust)
    cached_max = cache_store.get_max_ohlcv_date(tf_code, adjust)

    if cached_min is None or cached_max is None:
        gaps = [(start_date, end_date)]
    else:
        gaps = []
        if start_date < cached_min:
            prev = (datetime.strptime(cached_min, "%Y-%m-%d")
                    - timedelta(days=1)).strftime("%Y-%m-%d")
            gaps.append((start_date, min(prev, end_date)))
        if cached_max < end_date:
            nxt = (datetime.strptime(cached_max, "%Y-%m-%d")
                   + timedelta(days=1)).strftime("%Y-%m-%d")
            gaps.append((max(nxt, start_date), end_date))

    for fetch_start, fetch_end in gaps:
        if fetch_start > fetch_end:
            continue
        # TickFlow's klines endpoint caps each response at ~100 bars (returns
        # the most recent ones within the requested window), so wide gaps
        # (e.g. a 2Y chart on a cold cache) need multiple paginated calls,
        # walking backwards from fetch_end until fetch_start is covered.
        remaining_end = fetch_end
        for _ in range(20):
            try:
                fresh = _fetch_klines_raw(tf_code, fetch_start, remaining_end, adjust)
            except TickFlowError as e:
                logger.warning("ohlcv gap fetch failed for %s (%s..%s): %s",
                               tf_code, fetch_start, remaining_end, e)
                break
            if not fresh:
                break
            cache_store.upsert_ohlcv(tf_code, fresh, adjust)
            min_date = min(b["date"] for b in fresh)
            if min_date <= fetch_start:
                break
            remaining_end = (datetime.strptime(min_date, "%Y-%m-%d")
                             - timedelta(days=1)).strftime("%Y-%m-%d")
            if remaining_end < fetch_start:
                break

    return cache_store.get_ohlcv_range(tf_code, start_date, end_date, adjust)


def get_tf_stock_data(
    symbol: Annotated[str, "ticker in Yahoo Finance format, e.g. 600519.SS"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get A-share daily OHLCV data from TickFlow (前复权, forward-adjusted).

    Reads from a persistent local cache first and only fetches the gap from
    TickFlow — see :func:`_load_ohlcv_cached`.
    """
    try:
        import pandas as pd
    except ImportError:
        raise TickFlowError("pandas is required for TickFlow data")

    tf_code = _to_tf_code(symbol)
    bars = _load_ohlcv_cached(tf_code, start_date, end_date, adjust="forward")

    if not bars:
        return f"No data for {symbol} between {start_date} and {end_date}"

    rows = [{
        "Date": b["date"],
        "Open": b.get("open"), "High": b.get("high"), "Low": b.get("low"),
        "Close": b.get("close"), "Volume": b.get("volume"),
        "Turnover(CNY)": b.get("amount"), "PrevClose": b.get("prev_close"),
    } for b in bars]
    df = pd.DataFrame(rows)
    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Source: TickFlow (cached) | Currency: CNY | Adjusted: 前复权 (forward)\n"
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

    bars = _load_ohlcv_cached(tf_code,
                              start_dt.strftime("%Y-%m-%d"), curr_date,
                              adjust="forward")
    rows = [{
        "date": pd.to_datetime(b["date"]),
        "open": float(b.get("open") or 0),
        "high": float(b.get("high") or 0),
        "low":  float(b.get("low")  or 0),
        "close": float(b.get("close") or 0),
        "volume": float(b.get("volume") or 0),
    } for b in bars]

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


# ── Financial statements (balance / income / cashflow) — cached + incremental ─

_STATEMENT_PATHS = {
    "balance": "financials/balance-sheet",
    "income":  "financials/income",
    "cashflow": "financials/cash-flow",
    "metrics": "financials/metrics",
}


def _load_statement_cached(tf_code: str, statement: str,
                            curr_date: Optional[str] = None) -> list[dict]:
    """Return all known statement records for this symbol, using the cache.

    Fetches from TickFlow only periods after the latest cached one, since a
    given quarterly report is immutable once filed. ``curr_date`` (optional)
    caps the upper bound to avoid look-ahead leakage in backtesting.
    """
    from . import cache_store

    cached_max = cache_store.get_max_period_end(tf_code, statement)
    path = _STATEMENT_PATHS.get(statement)
    if path is None:
        raise TickFlowError(f"unknown statement type: {statement}")

    # If we have nothing yet, default to a wide window (last ~2 years of reports).
    fetch_after = cached_max
    needs_fetch = True
    if cached_max and curr_date and cached_max >= curr_date:
        # Nothing newer than curr_date could be reported anyway.
        needs_fetch = False

    if needs_fetch:
        params = {"symbols": tf_code}
        if fetch_after:
            # ``start_date`` filters to reports filed after this date. We pass
            # the day AFTER our latest cached period so we don't refetch it.
            nxt = (datetime.strptime(fetch_after, "%Y-%m-%d")
                   + timedelta(days=1)).strftime("%Y%m%d")
            params["start_date"] = nxt
        else:
            # Cold cache: pull from ~2 years ago to seed a reasonable history.
            params["start_date"] = (
                datetime.now() - timedelta(days=730)
            ).strftime("%Y%m%d")
        try:
            resp = _get(path, params)
            items = resp.get("data", {}).get(tf_code, []) or []
            if items:
                cache_store.upsert_financials(tf_code, statement, items)
        except TickFlowError as e:
            logger.warning("financials delta fetch failed for %s/%s: %s",
                           tf_code, statement, e)

    end_period = curr_date  # may be None
    return cache_store.get_financials(tf_code, statement, end_period=end_period)


def _render_statement(records: list[dict], ticker: str, title: str) -> str:
    import pandas as pd
    if not records:
        raise TickFlowError(f"No {title} data for {ticker}")
    # Sort newest first to match the prior shape callers expected.
    records = sorted(records, key=lambda r: r.get("period_end") or "", reverse=True)
    df = pd.DataFrame(records)
    header = (
        f"# {title} for {ticker.upper()}\n"
        f"# Source: TickFlow (cached) | Records: {len(df)}\n\n"
    )
    return header + df.to_csv(index=False)


def get_tf_balance_sheet(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    """Get balance sheet (资产负债表) — cached, incremental fetch."""
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        raise TickFlowError("pandas is required")
    tf_code = _to_tf_code(ticker)
    records = _load_statement_cached(tf_code, "balance", curr_date)
    return _render_statement(records, ticker, "Balance Sheet (资产负债表)")


def get_tf_income_statement(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    """Get income statement (利润表) — cached, incremental fetch."""
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        raise TickFlowError("pandas is required")
    tf_code = _to_tf_code(ticker)
    records = _load_statement_cached(tf_code, "income", curr_date)
    return _render_statement(records, ticker, "Income Statement (利润表)")


def get_tf_cashflow(
    ticker: Annotated[str, "ticker in Yahoo Finance format"],
    freq: str = "quarterly",
    curr_date: str = None,
) -> str:
    """Get cash flow statement (现金流量表) — cached, incremental fetch."""
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        raise TickFlowError("pandas is required")
    tf_code = _to_tf_code(ticker)
    records = _load_statement_cached(tf_code, "cashflow", curr_date)
    return _render_statement(records, ticker, "Cash Flow Statement (现金流量表)")


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
            price = it.get("last_price")

            # TickFlow's quote payload doesn't carry pe/pb/mktcap directly —
            # derive them the same way the screener's whole-market snapshot
            # does, from shares outstanding (instruments) and BPS/EPS-TTM
            # (financials), both of which are cheap thanks to the cache.
            six = tf_code.split(".")[0].zfill(6)
            pe = pb = total_mktcap = float_mktcap = None
            try:
                instr = tf_instruments([tf_code]).get(six) or {}
                fin = tf_financials_valuation([tf_code]).get(six) or {}
                tshare = instr.get("total_shares")
                fshare = instr.get("float_shares")
                bps = fin.get("bps")
                eps_ttm = fin.get("eps_ttm")
                if price and eps_ttm and eps_ttm > 0:
                    pe = round(price / eps_ttm, 2)
                if price and bps and bps > 0:
                    pb = round(price / bps, 4)
                if price and tshare:
                    total_mktcap = price * tshare
                if price and fshare:
                    float_mktcap = price * fshare
            except Exception as e:
                out["errors"].append(f"valuation: {e}")

            out["quote"] = {
                "symbol": it.get("symbol"),
                "code": tf_code.split(".")[0],
                "name": ext.get("name"),
                "last_price": price,
                "prev_close": it.get("prev_close"),
                "open":       it.get("open"),
                "high":       it.get("high"),
                "low":        it.get("low"),
                "volume":     it.get("volume"),
                "amount":     it.get("amount"),
                "change_pct":   ext.get("change_pct"),
                "amplitude":    ext.get("amplitude"),
                "turnover_rate": ext.get("turnover_rate"),
                "total_mktcap":  total_mktcap,
                "float_mktcap":  float_mktcap,
                "pe":  pe,
                "pb":  pb,
            }
        else:
            out["errors"].append("quote: empty")
    except Exception as e:
        out["errors"].append(f"quote: {e}")

    # 2) Financial metrics history (recent N quarters)
    try:
        start = (datetime.now() - timedelta(
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
            start = (datetime.now() - timedelta(
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
        start_dt = end_dt - timedelta(days=int(kline_days * 1.6))
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


# ── Circuit breaker / health cache ─────────────────────────────────────────────

_tf_health_cache: dict = {"ok": None, "checked_at": 0.0, "error": ""}
_TF_HEALTH_CACHE_TTL = 300  # 5 minutes


def tickflow_available(force_refresh: bool = False) -> tuple[bool, str]:
    """Check whether TickFlow API is currently reachable.

    Uses a 5-minute cache to avoid hammering the API on every task/subtask.
    Returns (is_available: bool, reason: str).

    Call this BEFORE any heavy TickFlow-dependent task (nightly_cache_backfill,
    full_market_backfill, run_screening_task) to short-circuit early and avoid
    flooding a dead endpoint with retries.
    """
    now = time.time()
    if not force_refresh and _tf_health_cache["checked_at"] > 0:
        age = now - _tf_health_cache["checked_at"]
        if age < _TF_HEALTH_CACHE_TTL:
            return _tf_health_cache["ok"], _tf_health_cache["error"] or "cached"

    result = test_tf_connection()
    _tf_health_cache["checked_at"] = now
    _tf_health_cache["ok"] = result.get("connected", False)
    _tf_health_cache["error"] = result.get("error", "")

    if _tf_health_cache["ok"]:
        return True, f"ok (latency={result.get('latency_ms', '?')}ms)"
    return False, _tf_health_cache["error"]


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

# TickFlow Expert 日线K线-批量查询 limit: 120/min, 200 symbols/req.
_KLINE_BATCH = 200


# Share counts/names change only on placements, buybacks, or renames — once
# cached, a code is considered fresh for this many days before TickFlow is
# queried again.
_INSTR_STALE_DAYS = 30


def tf_instruments(tf_symbols: list[str]) -> dict:
    """Batch instrument metadata. Returns {6-digit code: {total_shares, float_shares, name}}.

    ``tf_symbols`` are TickFlow-format symbols (e.g. "600519.SH"). Cache strategy:
    results are persisted permanently in the DB and only re-fetched for codes
    missing or older than ``_INSTR_STALE_DAYS``, so a hot cache turns the usual
    ~28 batches (whole market) into zero TickFlow calls. Tolerant of partial
    failure: a batch that errors after retries is logged and skipped so a single
    transient blip doesn't sink the whole enrichment.
    """
    from . import cache_store

    six_by_sym: dict[str, str] = {}
    for sym in tf_symbols:
        six = sym.split(".")[0].zfill(6)
        if six.isdigit():
            six_by_sym[six] = sym

    codes = list(six_by_sym.keys())
    stale = cache_store.get_stale_instrument_codes(codes, _INSTR_STALE_DAYS)

    fetched: dict[str, dict] = {}
    if stale:
        to_fetch = [six_by_sym[c] for c in stale]
        for i in range(0, len(to_fetch), _INSTR_BATCH):
            chunk = to_fetch[i:i + _INSTR_BATCH]
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
                fetched[six] = {
                    "total_shares": ext.get("total_shares"),
                    "float_shares": ext.get("float_shares"),
                    "name": item.get("name", ""),
                }
        if fetched:
            cache_store.upsert_instruments(fetched)
        logger.info("tf_instruments: %d/%d codes refreshed from TickFlow (%.0f%% cache hit)",
                     len(stale), len(codes), 100 * (1 - len(stale) / max(len(codes), 1)))

    out = cache_store.get_instruments(codes)
    # DB unavailable (standalone SDK) or row not yet visible: fall back to the
    # freshly fetched data for any code missing from the cache read.
    for code, v in fetched.items():
        out.setdefault(code, v)
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

    Returns {6-digit code: {bps, roe, eps_ttm, period_end, net_profit_yoy,
    debt_ratio, gross_margin, ocf_to_revenue}}. ``tf_symbols`` are TickFlow-format
    symbols.

    Cache strategy: financial reports are immutable, so we only call TickFlow
    for symbols whose latest cached ``metrics`` period is more than 80 days
    old (≈ one reporting interval). For symbols already up-to-date, we read
    the cached records straight from DB. On a hot cache this drops the typical
    screener run from ~56 batches to a handful, since most reports haven't
    changed since yesterday.
    """
    from . import cache_store

    if not tf_symbols:
        return {}
    if start_year is None:
        start_year = datetime.now().year - 1
    start_date_default = f"{start_year}0101"

    # 1. Find which symbols need a fresh pull.
    max_by_sym = cache_store.get_max_period_end_batch(tf_symbols, "metrics")
    today = datetime.now().date()
    stale_threshold_days = 80  # roughly one fiscal quarter
    to_refresh: list[str] = []
    for s in tf_symbols:
        last = max_by_sym.get(s)
        if not last:
            to_refresh.append(s)
            continue
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d").date()
        except ValueError:
            to_refresh.append(s)
            continue
        if (today - last_dt).days > stale_threshold_days:
            to_refresh.append(s)

    logger.info("tf_financials_valuation: %d symbols, %d need refresh (%.0f%% cache hit)",
                len(tf_symbols), len(to_refresh),
                100 * (1 - len(to_refresh) / max(len(tf_symbols), 1)))

    # 2. Fetch and persist only the stale symbols.
    for i in range(0, len(to_refresh), _FIN_BATCH):
        chunk = to_refresh[i:i + _FIN_BATCH]
        try:
            resp = _get("financials/metrics",
                        {"symbols": ",".join(chunk), "start_date": start_date_default})
        except TickFlowError as e:
            logger.warning("tf_financials_valuation: batch %d skipped (%s)",
                           i // _FIN_BATCH, e)
            continue
        for sym, records in (resp.get("data") or {}).items():
            if records:
                cache_store.upsert_financials(sym, "metrics", records)

    # 3. Read everything from cache and build the {six: {…}} map.
    cached = cache_store.get_financials_batch(tf_symbols, "metrics")
    out: dict[str, dict] = {}
    for sym, records in cached.items():
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
            # percent-scale (e.g. 89.76 == 89.76%), straight from TickFlow metrics
            "net_profit_yoy": latest.get("net_income_yoy"),
            "debt_ratio": latest.get("debt_to_asset_ratio"),
            "gross_margin": latest.get("gross_margin"),
            "ocf_to_revenue": latest.get("operating_cash_to_revenue"),
        }
    return out


def tf_financials_full_history(tf_symbols: list[str], start_date: str,
                                statements: Optional[list[str]] = None) -> dict[str, int]:
    """Batch-fetch and cache full financial-statement history for many symbols.

    ``tf_symbols`` are TickFlow-format symbols. ``start_date`` is ``YYYYMMDD``
    (e.g. 10 years ago), passed straight through to each statement endpoint's
    ``start_date`` filter. ``statements`` defaults to all four types
    (income/balance/cashflow/metrics). Requests are chunked at ``_FIN_BATCH``
    (100/req, matching the TickFlow Expert 财务数据 limit). Returns
    ``{statement: total records upserted}``.
    """
    from . import cache_store

    if not tf_symbols:
        return {}
    if statements is None:
        statements = list(_STATEMENT_PATHS.keys())

    totals: dict[str, int] = {}
    for statement in statements:
        path = _STATEMENT_PATHS.get(statement)
        if path is None:
            continue
        written = 0
        for i in range(0, len(tf_symbols), _FIN_BATCH):
            if i > 0:
                time.sleep(0.5)
            chunk = tf_symbols[i:i + _FIN_BATCH]
            try:
                resp = _get(path, {"symbols": ",".join(chunk), "start_date": start_date})
            except TickFlowError as e:
                logger.warning("tf_financials_full_history: %s batch %d skipped (%s)",
                               statement, i // _FIN_BATCH, e)
                continue
            for sym, records in (resp.get("data") or {}).items():
                if records:
                    written += cache_store.upsert_financials(sym, statement, records)
        totals[statement] = written
        logger.info("tf_financials_full_history: %s -> %d records upserted across %d symbols",
                     statement, written, len(tf_symbols))
    return totals


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


def tf_batch_klines_history(tf_symbols: list[str], count: int = 2500,
                             period: str = "1d", adjust: str = "forward") -> dict[str, list[dict]]:
    """Batch-fetch deep daily history via ``/v1/klines/batch`` and cache it.

    ``tf_symbols`` are TickFlow-format symbols (e.g. "600519.SH"). Requests are
    chunked at ``_KLINE_BATCH`` (200/req, matching the TickFlow Expert 日线K线
    批量查询 limit) and ``count`` (up to ~2500 ≈ 10 years of trading days) bars
    per symbol are requested per chunk. Each symbol's bars are upserted into the
    OHLCV cache via ``cache_store.upsert_ohlcv`` and also returned, keyed by
    TickFlow-format symbol.
    """
    from . import cache_store

    if not tf_symbols:
        return {}

    out: dict[str, bool] = {}
    for i in range(0, len(tf_symbols), _KLINE_BATCH):
        if i > 0:
            time.sleep(0.5)
        chunk = tf_symbols[i:i + _KLINE_BATCH]
        try:
            resp = _get("klines/batch", {
                "symbols": ",".join(chunk),
                "period": period,
                "count": count,
                "adjust": adjust,
            })
        except TickFlowError as e:
            logger.warning("tf_batch_klines_history: batch %d skipped (%s)",
                           i // _KLINE_BATCH, e)
            continue
        for tf_sym, kdata in (resp.get("data") or {}).items():
            bars = _parse_kline_arrays(kdata)
            if not bars:
                continue
            cache_store.upsert_ohlcv(tf_sym, bars, adjust)
            out[tf_sym] = True
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


