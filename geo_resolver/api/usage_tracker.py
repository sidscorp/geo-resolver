"""Lightweight SQLite request/usage logger for the GeoResolver API."""

import os
import sqlite3
import threading
import time
from contextlib import contextmanager

_DB_PATH = os.environ.get(
    "GEO_RESOLVER_USAGE_DB",
    os.path.expanduser("~/.geo-resolver/usage.db"),
)
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(_DB_PATH)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                query TEXT NOT NULL,
                mode TEXT,
                model TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_s REAL,
                status TEXT DEFAULT 'ok',
                error TEXT
            )
        """)
        _local.conn.commit()
    return _local.conn


def log_request(
    query: str,
    mode: str | None = None,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_s: float | None = None,
    status: str = "ok",
    error: str | None = None,
):
    """Log a single API request to SQLite."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO requests
           (timestamp, query, mode, model, prompt_tokens, completion_tokens,
            total_tokens, latency_s, status, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            time.time(), query, mode, model,
            prompt_tokens, completion_tokens, total_tokens,
            latency_s, status, error,
        ),
    )
    conn.commit()


def get_stats(days: int = 30) -> dict:
    """Get usage statistics for the last N days."""
    conn = _get_conn()
    cutoff = time.time() - (days * 86400)

    row = conn.execute(
        """SELECT
               COUNT(*) as total_requests,
               SUM(prompt_tokens) as total_prompt,
               SUM(completion_tokens) as total_completion,
               SUM(total_tokens) as total_tokens,
               AVG(latency_s) as avg_latency,
               SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
           FROM requests WHERE timestamp > ?""",
        (cutoff,),
    ).fetchone()

    daily = conn.execute(
        """SELECT
               DATE(timestamp, 'unixepoch', 'localtime') as day,
               COUNT(*) as requests,
               SUM(total_tokens) as tokens
           FROM requests
           WHERE timestamp > ?
           GROUP BY day ORDER BY day DESC LIMIT 30""",
        (cutoff,),
    ).fetchall()

    recent = conn.execute(
        """SELECT timestamp, query, model, total_tokens, latency_s, status
           FROM requests ORDER BY id DESC LIMIT 20""",
    ).fetchall()

    return {
        "period_days": days,
        "total_requests": row[0] or 0,
        "total_prompt_tokens": row[1] or 0,
        "total_completion_tokens": row[2] or 0,
        "total_tokens": row[3] or 0,
        "avg_latency_s": round(row[4], 2) if row[4] else 0,
        "errors": row[5] or 0,
        "daily": [
            {"date": d[0], "requests": d[1], "tokens": d[2] or 0}
            for d in daily
        ],
        "recent": [
            {
                "timestamp": r[0],
                "query": r[1],
                "model": r[2],
                "total_tokens": r[3] or 0,
                "latency_s": round(r[4], 2) if r[4] else None,
                "status": r[5],
            }
            for r in recent
        ],
    }
