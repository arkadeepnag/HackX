"""
Persistence layer.

SQLite with JSON payloads. Deliberately thin: the point is that leads,
conversation sessions and outcome events survive a restart, which the
in-memory dicts in main.py did not. Swapping to PostgreSQL + PostGIS later
means reimplementing this one module, not touching the engines.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("RAAH_DB_PATH", "raah.db"))

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    phone TEXT,
    pincode TEXT,
    segment TEXT,
    status TEXT,
    propensity_score REAL,
    financing_score REAL,
    solar_score REAL,
    routing_class TEXT,
    partner_id TEXT,
    latitude REAL,
    longitude REAL,
    capacity_kw REAL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_pincode ON leads(pincode);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_partner ON leads(partner_id);
CREATE INDEX IF NOT EXISTS idx_leads_geo ON leads(latitude, longitude);

CREATE TABLE IF NOT EXISTS models (
    name TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    phone TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    language TEXT,
    lead_id TEXT,
    context TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    phone TEXT,
    event_type TEXT NOT NULL,
    partner_id TEXT,
    payload TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    direction TEXT NOT NULL,
    body TEXT,
    message_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone);

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


_initialised = False


def init_db(force: bool = False) -> None:
    """Idempotent. Called at import so any entry point (API, worker,
    script, test client) finds the schema present."""
    global _initialised
    if _initialised and not force:
        return
    with _lock:
        conn = _connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
    _initialised = True


def reset_db() -> None:
    """
    Drop and recreate every table. For tests and local demos only --
    init_db() is create-if-absent and deliberately never destroys data,
    so it cannot be used to isolate one test run from the next.
    """
    with _lock:
        conn = _connect()
        try:
            for table in ("leads", "sessions", "events", "messages",
                          "processed_messages", "models"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


# ----------------------------- leads ---------------------------------

def upsert_lead(lead: dict[str, Any]) -> None:
    lead_id = lead["lead_id"]
    with _lock:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT created_at FROM leads WHERE lead_id=?", (lead_id,)
            ).fetchone()
            created = existing["created_at"] if existing else now_iso()
            conn.execute(
                """
                INSERT INTO leads (lead_id, phone, pincode, segment, status,
                    propensity_score, financing_score, solar_score,
                    routing_class, partner_id, latitude, longitude,
                    capacity_kw, payload, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(lead_id) DO UPDATE SET
                    phone=excluded.phone, pincode=excluded.pincode,
                    segment=excluded.segment, status=excluded.status,
                    propensity_score=excluded.propensity_score,
                    financing_score=excluded.financing_score,
                    solar_score=excluded.solar_score,
                    routing_class=excluded.routing_class,
                    partner_id=excluded.partner_id,
                    latitude=excluded.latitude, longitude=excluded.longitude,
                    capacity_kw=excluded.capacity_kw,
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    lead_id, lead.get("phone"), lead.get("pincode"),
                    lead.get("segment"), lead.get("status", "new"),
                    lead.get("propensity_score"), lead.get("financing_score"),
                    lead.get("solar_score"), lead.get("routing_class"),
                    lead.get("partner_id"),
                    lead.get("latitude"), lead.get("longitude"),
                    lead.get("capacity_kw") or lead.get("pv_capacity_kw"),
                    json.dumps(lead, default=str),
                    created, now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_lead(lead_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload FROM leads WHERE lead_id=?", (lead_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None
    finally:
        conn.close()


def get_lead_by_phone(phone: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload FROM leads WHERE phone=? ORDER BY updated_at DESC LIMIT 1",
            (phone,),
        ).fetchone()
        return json.loads(row["payload"]) if row else None
    finally:
        conn.close()


def count_leads(
    min_propensity: float = 0.0,
    min_financing: float = 0.0,
    routing_class: str | None = None,
    status: str | None = None,
    pincode: str | None = None,
    partner_id: str | None = None,
) -> int:
    sql = [
        "SELECT COUNT(*) AS n FROM leads WHERE "
        "COALESCE(propensity_score,0)>=? AND COALESCE(financing_score,0)>=?"
    ]
    args: list[Any] = [min_propensity, min_financing]
    for column, value in (
        ("routing_class", routing_class), ("status", status),
        ("pincode", pincode), ("partner_id", partner_id),
    ):
        if value:
            sql.append(f"AND {column}=?")
            args.append(value)
    conn = _connect()
    try:
        return int(conn.execute(" ".join(sql), args).fetchone()["n"])
    finally:
        conn.close()


def list_leads(
    min_propensity: float = 0.0,
    min_financing: float = 0.0,
    routing_class: str | None = None,
    status: str | None = None,
    pincode: str | None = None,
    partner_id: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = [
        "SELECT payload FROM leads WHERE "
        "COALESCE(propensity_score,0)>=? AND COALESCE(financing_score,0)>=?"
    ]
    args: list[Any] = [min_propensity, min_financing]

    if routing_class:
        sql.append("AND routing_class=?")
        args.append(routing_class)
    if status:
        sql.append("AND status=?")
        args.append(status)
    if pincode:
        sql.append("AND pincode=?")
        args.append(pincode)
    if partner_id:
        sql.append("AND partner_id=?")
        args.append(partner_id)
    if bbox:
        # min_lon, min_lat, max_lon, max_lat -- map viewport queries
        sql.append(
            "AND longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?"
        )
        args.extend([bbox[0], bbox[2], bbox[1], bbox[3]])

    sql.append(
        "ORDER BY COALESCE(propensity_score,0) DESC, "
        "COALESCE(financing_score,0) DESC LIMIT ? OFFSET ?"
    )
    args.extend([limit, offset])

    conn = _connect()
    try:
        rows = conn.execute(" ".join(sql), args).fetchall()
        return [json.loads(r["payload"]) for r in rows]
    finally:
        conn.close()


# ---------------------------- sessions -------------------------------

def get_session(phone: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE phone=?", (phone,)
        ).fetchone()
        if not row:
            return None
        return {
            "phone": row["phone"],
            "state": row["state"],
            "language": row["language"],
            "lead_id": row["lead_id"],
            "context": json.loads(row["context"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def save_session(session: dict[str, Any]) -> None:
    with _lock:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT created_at FROM sessions WHERE phone=?",
                (session["phone"],),
            ).fetchone()
            created = existing["created_at"] if existing else now_iso()
            conn.execute(
                """
                INSERT INTO sessions (phone, state, language, lead_id,
                    context, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(phone) DO UPDATE SET
                    state=excluded.state, language=excluded.language,
                    lead_id=excluded.lead_id, context=excluded.context,
                    updated_at=excluded.updated_at
                """,
                (
                    session["phone"], session["state"], session.get("language"),
                    session.get("lead_id"),
                    json.dumps(session.get("context", {}), default=str),
                    created, now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def delete_session(phone: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM sessions WHERE phone=?", (phone,))
            conn.commit()
        finally:
            conn.close()


# ----------------------------- events --------------------------------

def record_event(
    event_type: str,
    lead_id: str | None = None,
    phone: str | None = None,
    partner_id: str | None = None,
    payload: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO events (lead_id, phone, event_type, partner_id,"
                " payload, created_at) VALUES (?,?,?,?,?,?)",
                (
                    lead_id, phone, event_type, partner_id,
                    json.dumps(payload or {}, default=str),
                    timestamp or now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def list_events(
    lead_id: str | None = None,
    event_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    sql = ["SELECT * FROM events WHERE 1=1"]
    args: list[Any] = []
    if lead_id:
        sql.append("AND lead_id=?")
        args.append(lead_id)
    if event_type:
        sql.append("AND event_type=?")
        args.append(event_type)
    sql.append("ORDER BY created_at DESC LIMIT ?")
    args.append(limit)

    conn = _connect()
    try:
        rows = conn.execute(" ".join(sql), args).fetchall()
        return [
            {
                "id": r["id"], "lead_id": r["lead_id"], "phone": r["phone"],
                "event_type": r["event_type"], "partner_id": r["partner_id"],
                "payload": json.loads(r["payload"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ----------------------------- models --------------------------------

def save_model(name: str, payload: dict[str, Any]) -> int:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT version FROM models WHERE name=?", (name,)
            ).fetchone()
            version = (row["version"] + 1) if row else 1
            conn.execute(
                "INSERT INTO models (name, version, payload, created_at)"
                " VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET"
                " version=excluded.version, payload=excluded.payload,"
                " created_at=excluded.created_at",
                (name, version, json.dumps(payload, default=str), now_iso()),
            )
            conn.commit()
            return version
        finally:
            conn.close()


def get_model(name: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT version, payload, created_at FROM models WHERE name=?",
            (name,),
        ).fetchone()
        if not row:
            return None
        return {
            "name": name, "version": row["version"],
            "created_at": row["created_at"],
            **json.loads(row["payload"]),
        }
    finally:
        conn.close()


# ---------------------------- messages -------------------------------

def log_message(
    phone: str, direction: str, body: str | None, message_id: str | None = None
) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO messages (phone, direction, body, message_id,"
                " created_at) VALUES (?,?,?,?,?)",
                (phone, direction, body, message_id, now_iso()),
            )
            conn.commit()
        finally:
            conn.close()


def already_processed(message_id: str) -> bool:
    """
    Meta retries webhooks aggressively. Without this a retry re-runs the
    state machine and the customer gets asked the same question twice.
    """
    if not message_id:
        return False
    with _lock:
        conn = _connect()
        try:
            try:
                conn.execute(
                    "INSERT INTO processed_messages (message_id, created_at)"
                    " VALUES (?,?)",
                    (message_id, now_iso()),
                )
                conn.commit()
                return False
            except sqlite3.IntegrityError:
                return True
        finally:
            conn.close()


init_db()
