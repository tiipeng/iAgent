"""Native iOS data tools — read directly from system SQLite databases.

On rootless Dopamine the `mobile` user owns or can read most of iOS's
own data stores. These tools don't need any Shortcut, MCP server, or
Sileo package — they just open the relevant SQLite file read-only.

What's exposed:
  read_messages         iMessage / SMS history (sms.db)
  read_contacts         AddressBook (AddressBook.sqlitedb)
  read_calendar_events  Calendar (Calendar.sqlitedb)
  read_safari_history   Safari history (History.db)
  list_voice_memos      Voice memo .m4a files

Caveats:
  - SQLite files may be locked while iOS is writing to them. We open
    read-only with ?immutable=1 to avoid contention; rare write moments
    can still cause a "database is locked" error — retry once.
  - Messages.app stores dates as nanoseconds since 2001-01-01 UTC.
  - All paths assume rootless layout (/var/mobile/...). Code falls back
    gracefully when a DB is missing on this iOS version.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from tools.registry import register

# Mac/iOS epoch starts 2001-01-01 (978307200 unix epoch)
_MAC_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

_PATHS = {
    "sms":      [Path("/var/mobile/Library/SMS/sms.db")],
    "contacts": [Path("/var/mobile/Library/AddressBook/AddressBook.sqlitedb")],
    "calendar": [Path("/var/mobile/Library/Calendar/Calendar.sqlitedb")],
    "safari":   [Path("/var/mobile/Library/Safari/History.db"),
                 Path("/var/mobile/Library/Safari/History.sqlite")],
    "voice":    [Path("/var/mobile/Media/Recordings"),
                 Path("/var/mobile/Library/VoiceMemos")],
}


def _find(kind: str) -> Optional[Path]:
    for p in _PATHS.get(kind, []):
        if p.exists():
            return p
    return None


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Open SQLite read-only, immutable so iOS lock contention can't bite."""
    uri = f"file:{path}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def _from_mac_ns(ns: int) -> datetime:
    """Messages.app stores dates as nanoseconds since 2001-01-01 UTC."""
    if ns is None:
        return _MAC_EPOCH
    if ns > 1_000_000_000_000:
        seconds = ns / 1_000_000_000.0
    else:
        seconds = float(ns)
    return _MAC_EPOCH + timedelta(seconds=seconds)


# ── Messages ─────────────────────────────────────────────────────────────

@register({
    "name": "read_messages",
    "description": (
        "Read recent iMessage / SMS messages from the device. "
        "Returns a chronological list of messages with sender, text, and timestamp."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent messages to return (default 20, max 100)",
            },
            "contact": {
                "type": "string",
                "description": (
                    "Optional substring to filter the other party — phone number "
                    "fragment, email, or contact name."
                ),
            },
        },
        "required": [],
    },
})
async def read_messages(limit: int = 20, contact: str = "") -> str:
    db = _find("sms")
    if not db:
        return "[read_messages] sms.db not found at /var/mobile/Library/SMS/"
    limit = max(1, min(limit, 100))
    try:
        with _connect_ro(db) as conn:
            sql = """
                SELECT
                    h.id            AS handle,
                    m.is_from_me    AS from_me,
                    m.text          AS text,
                    m.date          AS date_ns
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.text IS NOT NULL
            """
            params: list = []
            if contact:
                sql += " AND h.id LIKE ?"
                params.append(f"%{contact}%")
            sql += " ORDER BY m.date DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        return f"[read_messages] {e}"

    if not rows:
        return "(no messages found)"
    lines = []
    for handle, from_me, text, date_ns in reversed(rows):
        ts = _from_mac_ns(date_ns).strftime("%Y-%m-%d %H:%M")
        who = "me" if from_me else (handle or "?")
        snippet = (text or "").replace("\n", " ")[:200]
        lines.append(f"[{ts}] {who}: {snippet}")
    return "\n".join(lines)


# ── Contacts ─────────────────────────────────────────────────────────────

@register({
    "name": "read_contacts",
    "description": (
        "Search the device's address book. Returns matching contacts with "
        "their name, phone numbers, and email addresses."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Name fragment to search for (case-insensitive). Empty = first 20.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 20)",
            },
        },
        "required": [],
    },
})
async def read_contacts(query: str = "", limit: int = 20) -> str:
    db = _find("contacts")
    if not db:
        return "[read_contacts] AddressBook.sqlitedb not found"
    limit = max(1, min(limit, 100))
    try:
        with _connect_ro(db) as conn:
            sql = """
                SELECT
                    p.ROWID,
                    COALESCE(p.First, '') || ' ' || COALESCE(p.Last, '') AS name,
                    p.Organization
                FROM ABPerson p
            """
            params: list = []
            if query:
                sql += " WHERE name LIKE ? OR p.Organization LIKE ?"
                params.extend([f"%{query}%", f"%{query}%"])
            sql += " LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()

            results = []
            for rowid, name, org in rows:
                vals = conn.execute(
                    "SELECT value FROM ABMultiValue WHERE record_id = ?", (rowid,)
                ).fetchall()
                contacts = [v[0] for v in vals if v[0]]
                line = f"• {name.strip() or org or '?'}"
                if org and name.strip():
                    line += f"  ({org})"
                if contacts:
                    line += "\n    " + ", ".join(contacts[:5])
                results.append(line)
    except sqlite3.OperationalError as e:
        return f"[read_contacts] {e}"

    return "\n".join(results) if results else "(no contacts matched)"


# ── Calendar ─────────────────────────────────────────────────────────────

@register({
    "name": "read_calendar_events",
    "description": (
        "Read upcoming or recent calendar events from the device's Calendar database. "
        "Useful for 'what's on my calendar today/this week?' questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Window in days from today (positive = upcoming, default 7)",
            },
        },
        "required": [],
    },
})
async def read_calendar_events(days: int = 7) -> str:
    db = _find("calendar")
    if not db:
        return "[read_calendar_events] Calendar.sqlitedb not found"
    days = max(-365, min(days, 365))
    try:
        with _connect_ro(db) as conn:
            now = (datetime.now(timezone.utc) - _MAC_EPOCH).total_seconds()
            until = now + (days * 86400) if days >= 0 else now
            since = now if days >= 0 else now + (days * 86400)
            rows = conn.execute(
                """
                SELECT summary, start_date, end_date, location
                FROM CalendarItem
                WHERE start_date BETWEEN ? AND ?
                ORDER BY start_date
                LIMIT 100
                """,
                (since, until),
            ).fetchall()
    except sqlite3.OperationalError as e:
        return f"[read_calendar_events] {e}"

    if not rows:
        return f"(no events in the next {days} days)"
    lines = []
    for summary, start, end, location in rows:
        start_dt = _MAC_EPOCH + timedelta(seconds=start or 0)
        line = f"{start_dt.strftime('%a %b %d %H:%M')}  {summary or '(no title)'}"
        if location:
            line += f"  @ {location}"
        lines.append(line)
    return "\n".join(lines)


# ── Safari history ───────────────────────────────────────────────────────

@register({
    "name": "read_safari_history",
    "description": (
        "Read Safari browsing history. Returns recently visited URLs with titles and timestamps."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent visits to return (default 20, max 200)",
            },
            "query": {
                "type": "string",
                "description": "Optional URL substring filter",
            },
        },
        "required": [],
    },
})
async def read_safari_history(limit: int = 20, query: str = "") -> str:
    db = _find("safari")
    if not db:
        return "[read_safari_history] History.db not found"
    limit = max(1, min(limit, 200))
    try:
        with _connect_ro(db) as conn:
            sql = """
                SELECT v.visit_time, v.title, i.url
                FROM history_visits v
                JOIN history_items i ON v.history_item = i.id
            """
            params: list = []
            if query:
                sql += " WHERE i.url LIKE ?"
                params.append(f"%{query}%")
            sql += " ORDER BY v.visit_time DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        return f"[read_safari_history] {e}"

    if not rows:
        return "(no history)"
    lines = []
    for visit_time, title, url in rows:
        ts = _from_mac_ns(visit_time).strftime("%Y-%m-%d %H:%M")
        lines.append(f"[{ts}] {title or url}\n    {url}")
    return "\n".join(lines)


# ── Voice memos ──────────────────────────────────────────────────────────

@register({
    "name": "list_voice_memos",
    "description": (
        "List voice memo recordings stored on the device. Returns file paths "
        "sorted newest first; the agent can then send_photo (file_send) or "
        "describe with another tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent recordings to return (default 10, max 50)",
            },
        },
        "required": [],
    },
})
async def list_voice_memos(limit: int = 10) -> str:
    base = _find("voice")
    if not base:
        return "[list_voice_memos] Recordings folder not found"
    limit = max(1, min(limit, 50))
    files = []
    for ext in (".m4a", ".caf", ".wav"):
        files += list(base.rglob(f"*{ext}"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "(no recordings)"
    lines = []
    for f in files[:limit]:
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = f.stat().st_size // 1024
        lines.append(f"[{ts}] {size_kb:>6} KB  {f}")
    return "\n".join(lines)
