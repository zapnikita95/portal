"""
Персистентная история событий Portal (отправка/приём файла и текста).
SQLite рядом с config.json (десктоп).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import portal_config


def history_db_path() -> Path:
    p = portal_config.config_path().parent / "portal_history.sqlite3"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(history_db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS portal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                direction TEXT NOT NULL,
                kind TEXT NOT NULL,
                peer_ip TEXT,
                peer_label TEXT,
                name TEXT,
                snippet TEXT,
                stored_path TEXT,
                route_json TEXT,
                filesize INTEGER
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_portal_events_ts ON portal_events(ts DESC)"
        )


def append_event(
    *,
    direction: str,
    kind: str,
    peer_ip: str = "",
    peer_label: str = "",
    name: str = "",
    snippet: str = "",
    stored_path: str = "",
    route_json: str = "",
    filesize: Optional[int] = None,
) -> None:
    """Потокобезопасно: открывает своё соединение."""
    try:
        init_db()
        with _connect() as con:
            con.execute(
                """
                INSERT INTO portal_events
                (ts, direction, kind, peer_ip, peer_label, name, snippet, stored_path, route_json, filesize)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    direction,
                    kind,
                    peer_ip or "",
                    peer_label or "",
                    name or "",
                    snippet or "",
                    stored_path or "",
                    route_json or "",
                    filesize,
                ),
            )
    except Exception:
        pass


def list_events(*, limit: int = 200, search: str = "") -> List[Dict[str, Any]]:
    init_db()
    q = (search or "").strip().lower()
    with _connect() as con:
        if q:
            like = f"%{q}%"
            rows = con.execute(
                """
                SELECT * FROM portal_events
                WHERE lower(COALESCE(peer_ip,'')) LIKE ?
                   OR lower(COALESCE(peer_label,'')) LIKE ?
                   OR lower(COALESCE(name,'')) LIKE ?
                   OR lower(COALESCE(snippet,'')) LIKE ?
                   OR lower(COALESCE(stored_path,'')) LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (like, like, like, like, like, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM portal_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_event(event_id: int) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM portal_events WHERE id = ?", (int(event_id),)
        ).fetchone()
    return dict(row) if row else None


def parse_route_ips(route_json: str) -> List[str]:
    if not route_json:
        return []
    try:
        data = json.loads(route_json)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return []
