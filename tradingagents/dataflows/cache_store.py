"""Persistent market-data cache (Phase 1) + cross-process Redis cache (Phase 2).

History never changes — yesterday's K-line and Q1's net income are immutable.
This module is the single place that converts every TickFlow getter from
"refetch the whole thing every call" to "fetch only what we don't have yet."

There are two layers:

- **DB store (Phase 1)** — durable, used for OHLCV bars and quarterly financial
  statements. Keyed by symbol + date / period_end so upserts naturally dedupe.
- **Redis store (Phase 2)** — cross-process, used for short-TTL whole-market
  snapshots that the API server and Celery worker both want (otherwise each
  process keeps its own cold in-memory cache and re-downloads the universe).

Both layers are opt-in: if `server.database` can't be imported the DB layer
becomes a no-op, and if `REDIS_URL` is unset or unreachable the Redis layer
falls back to an in-memory dict. That way the `tradingagents` package keeps
working as a standalone SDK while still benefiting when run inside the
production server / worker.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ── DB layer (Phase 1: OHLCV + financials) ─────────────────────────────────────

def _session():
    """Lazy import to avoid coupling tradingagents to server at import time."""
    try:
        from server.database import SessionLocal
        return SessionLocal()
    except Exception:
        return None


def _models():
    try:
        from server.models import StockOHLCV, StockFinancials
        return StockOHLCV, StockFinancials
    except Exception:
        return None, None


def get_max_ohlcv_date(tf_symbol: str, adjust: str = "forward") -> Optional[str]:
    """Return the latest cached date for this symbol, or None if cache is empty."""
    db = _session()
    if db is None:
        return None
    try:
        StockOHLCV, _ = _models()
        if StockOHLCV is None:
            return None
        from sqlalchemy import func
        row = (db.query(func.max(StockOHLCV.date))
                 .filter(StockOHLCV.symbol == tf_symbol,
                         StockOHLCV.adjust == adjust)
                 .scalar())
        return row
    finally:
        db.close()


def get_min_ohlcv_date(tf_symbol: str, adjust: str = "forward") -> Optional[str]:
    """Return the earliest cached date for this symbol, or None if cache is empty."""
    db = _session()
    if db is None:
        return None
    try:
        StockOHLCV, _ = _models()
        if StockOHLCV is None:
            return None
        from sqlalchemy import func
        row = (db.query(func.min(StockOHLCV.date))
                 .filter(StockOHLCV.symbol == tf_symbol,
                         StockOHLCV.adjust == adjust)
                 .scalar())
        return row
    finally:
        db.close()


def get_ohlcv_range(tf_symbol: str, start_date: str, end_date: str,
                    adjust: str = "forward") -> list[dict]:
    """Return cached bars in ``[start_date, end_date]`` ordered by date asc."""
    db = _session()
    if db is None:
        return []
    try:
        StockOHLCV, _ = _models()
        if StockOHLCV is None:
            return []
        rows = (db.query(StockOHLCV)
                  .filter(StockOHLCV.symbol == tf_symbol,
                          StockOHLCV.adjust == adjust,
                          StockOHLCV.date >= start_date,
                          StockOHLCV.date <= end_date)
                  .order_by(StockOHLCV.date.asc())
                  .all())
        return [{
            "date": r.date, "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "volume": r.volume, "amount": r.amount,
            "prev_close": r.prev_close,
        } for r in rows]
    finally:
        db.close()


def upsert_ohlcv(tf_symbol: str, bars: list[dict], adjust: str = "forward") -> int:
    """Insert bars; skip rows whose (symbol, date, adjust) already exist.

    Returns count of newly-written rows. Bars are dicts with the keys produced
    by :func:`get_ohlcv_range`. Idempotent — safe to call with overlapping
    ranges (the dedupe is handled by the composite primary key).
    """
    if not bars:
        return 0
    db = _session()
    if db is None:
        return 0
    try:
        StockOHLCV, _ = _models()
        if StockOHLCV is None:
            return 0
        # Pull existing dates in one query, write only the gap
        existing = {
            d for (d,) in db.query(StockOHLCV.date)
                            .filter(StockOHLCV.symbol == tf_symbol,
                                    StockOHLCV.adjust == adjust,
                                    StockOHLCV.date.in_([b["date"] for b in bars]))
                            .all()
        }
        written = 0
        for b in bars:
            if b["date"] in existing:
                continue
            db.add(StockOHLCV(
                symbol=tf_symbol, date=b["date"], adjust=adjust,
                open=b.get("open"), high=b.get("high"), low=b.get("low"),
                close=b.get("close"), volume=b.get("volume"),
                amount=b.get("amount"), prev_close=b.get("prev_close"),
            ))
            written += 1
        if written:
            db.commit()
        return written
    except Exception as e:
        logger.warning("upsert_ohlcv failed for %s: %s", tf_symbol, e)
        db.rollback()
        return 0
    finally:
        db.close()


def get_max_period_end(tf_symbol: str, statement: str) -> Optional[str]:
    db = _session()
    if db is None:
        return None
    try:
        _, StockFinancials = _models()
        if StockFinancials is None:
            return None
        from sqlalchemy import func
        return (db.query(func.max(StockFinancials.period_end))
                  .filter(StockFinancials.symbol == tf_symbol,
                          StockFinancials.statement == statement)
                  .scalar())
    finally:
        db.close()


def get_financials(tf_symbol: str, statement: str,
                   start_period: Optional[str] = None,
                   end_period: Optional[str] = None) -> list[dict]:
    """Return cached statement records sorted by period_end asc."""
    db = _session()
    if db is None:
        return []
    try:
        _, StockFinancials = _models()
        if StockFinancials is None:
            return []
        q = (db.query(StockFinancials)
               .filter(StockFinancials.symbol == tf_symbol,
                       StockFinancials.statement == statement))
        if start_period:
            q = q.filter(StockFinancials.period_end >= start_period)
        if end_period:
            q = q.filter(StockFinancials.period_end <= end_period)
        rows = q.order_by(StockFinancials.period_end.asc()).all()
        return [r.data for r in rows if r.data is not None]
    finally:
        db.close()


def upsert_financials(tf_symbol: str, statement: str,
                       records: list[dict]) -> int:
    """Insert statement rows keyed on (symbol, period_end, statement).

    Each record must include a ``period_end`` field; everything else is stored
    as the JSON ``data`` blob. Returns count of newly-written rows.
    """
    if not records:
        return 0
    db = _session()
    if db is None:
        return 0
    try:
        _, StockFinancials = _models()
        if StockFinancials is None:
            return 0
        periods = [str(r.get("period_end")) for r in records if r.get("period_end")]
        existing = {
            p for (p,) in db.query(StockFinancials.period_end)
                            .filter(StockFinancials.symbol == tf_symbol,
                                    StockFinancials.statement == statement,
                                    StockFinancials.period_end.in_(periods))
                            .all()
        }
        written = 0
        for r in records:
            pe = r.get("period_end")
            if not pe or str(pe) in existing:
                continue
            db.add(StockFinancials(
                symbol=tf_symbol, period_end=str(pe),
                statement=statement, data=r,
            ))
            written += 1
        if written:
            db.commit()
        return written
    except Exception as e:
        logger.warning("upsert_financials failed for %s/%s: %s",
                       tf_symbol, statement, e)
        db.rollback()
        return 0
    finally:
        db.close()


def get_financials_batch(tf_symbols: list[str], statement: str
                         ) -> dict[str, list[dict]]:
    """Bulk variant for the screener. Returns {symbol: [records...]}."""
    db = _session()
    if db is None or not tf_symbols:
        return {}
    try:
        _, StockFinancials = _models()
        if StockFinancials is None:
            return {}
        rows = (db.query(StockFinancials)
                  .filter(StockFinancials.symbol.in_(tf_symbols),
                          StockFinancials.statement == statement)
                  .order_by(StockFinancials.symbol.asc(),
                            StockFinancials.period_end.asc())
                  .all())
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r.symbol, []).append(r.data)
        return out
    finally:
        db.close()


def get_max_period_end_batch(tf_symbols: list[str], statement: str
                              ) -> dict[str, str]:
    """Bulk variant: returns {symbol: max(period_end)} for symbols present."""
    db = _session()
    if db is None or not tf_symbols:
        return {}
    try:
        _, StockFinancials = _models()
        if StockFinancials is None:
            return {}
        from sqlalchemy import func
        rows = (db.query(StockFinancials.symbol,
                         func.max(StockFinancials.period_end))
                  .filter(StockFinancials.symbol.in_(tf_symbols),
                          StockFinancials.statement == statement)
                  .group_by(StockFinancials.symbol)
                  .all())
        return {sym: pe for sym, pe in rows if pe}
    finally:
        db.close()


# ── Redis layer (Phase 2: shared short-TTL snapshots) ──────────────────────────

_REDIS_CLIENT = None
_REDIS_CHECKED = False
_LOCAL_FALLBACK: dict[str, tuple[float, str]] = {}
_LOCAL_LOCK = threading.Lock()


def _redis():
    """Return a cached redis client, or None if redis isn't configured/reachable."""
    global _REDIS_CLIENT, _REDIS_CHECKED
    if _REDIS_CHECKED:
        return _REDIS_CLIENT
    _REDIS_CHECKED = True
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        client.ping()
        _REDIS_CLIENT = client
        logger.info("cache_store: connected to Redis at %s", url)
    except Exception as e:
        logger.warning("cache_store: Redis unreachable (%s) — falling back to in-memory", e)
        _REDIS_CLIENT = None
    return _REDIS_CLIENT


def shared_get_json(key: str, ttl: float):
    """Cross-process cached read. ``ttl`` is used only for the in-memory
    fallback; Redis enforces TTL via SETEX."""
    r = _redis()
    if r is not None:
        try:
            raw = r.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception as e:
            logger.debug("Redis GET failed for %s: %s", key, e)
    with _LOCAL_LOCK:
        item = _LOCAL_FALLBACK.get(key)
        if item is None:
            return None
        ts, raw = item
        if time.time() - ts > ttl:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None


def shared_set_json(key: str, value, ttl_seconds: int = 600) -> None:
    raw = json.dumps(value, default=str)
    r = _redis()
    if r is not None:
        try:
            r.setex(key, ttl_seconds, raw)
            return
        except Exception as e:
            logger.debug("Redis SET failed for %s: %s", key, e)
    with _LOCAL_LOCK:
        _LOCAL_FALLBACK[key] = (time.time(), raw)
