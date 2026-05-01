from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))
_LOG_DIR = _IAGENT_HOME / "logs"
_DEFAULT_PATH = _LOG_DIR / "ops_journal.jsonl"
_ALLOWED_STATUS = {"ok", "warn", "fail", "skip", "info"}
_SECRET_KEY_RE = re.compile(r"(password|passwd|token|refreshToken|refresh_token|pincode|pin|setup.?code|api.?key|secret)", re.I)
_SECRET_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{3}\b"),  # HomeKit setup code
    re.compile(r"(?i)(setup\s*code|pincode|pin|password|passwd|refreshToken|refresh_token|api[_-]?key|token)\s*[:=]\s*['\"]?[^\s,'\"}]+"),
    re.compile(r"(?i)(token\s*:\s*)['\"][^'\"]+['\"]"),
]


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def _safe_status(status: str) -> str:
    status = str(status or "info").lower()
    return status if status in _ALLOWED_STATUS else "info"


def redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: (m.group(1) + ": [REDACTED]") if m.groups() else "[REDACTED]", redacted)
    return redacted


def redact_value(value: Any, key: str | None = None) -> Any:
    if key and _SECRET_KEY_RE.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, key) for v in value]
    return value


def make_event(event_type: str, status: str, message: str, component: str | None = None, details: dict[str, Any] | None = None, timestamp: int | None = None) -> dict[str, Any]:
    return {
        "timestamp": int(time.time() if timestamp is None else timestamp),
        "event_type": str(event_type or "event"),
        "component": component or "iagent",
        "status": _safe_status(status),
        "message": str(message or ""),
        "details": details or {},
    }


def sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    clean = make_event(
        event.get("event_type", "event"),
        event.get("status", "info"),
        event.get("message", ""),
        component=event.get("component") or "iagent",
        details=event.get("details") or {},
        timestamp=event.get("timestamp"),
    )
    return redact_value(clean)


def record_event(event: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else _DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    clean = sanitize_event(event)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(clean, sort_keys=True, ensure_ascii=False) + "\n")
    return {"path": str(p), "event": clean}


def read_events(path: str | Path | None = None, limit: int = 20, component: str | None = None, event_type: str | None = None) -> list[dict[str, Any]]:
    p = Path(path) if path is not None else _DEFAULT_PATH
    limit = max(1, min(int(limit), 200))
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(errors="replace").splitlines():
        try:
            item = sanitize_event(json.loads(line))
        except Exception:
            continue
        if component and item.get("component") != component:
            continue
        if event_type and item.get("event_type") != event_type:
            continue
        rows.append(item)
    return rows[-limit:]


def _extract_issue_codes(event: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    details = event.get("details") or {}
    if isinstance(details.get("code"), str):
        codes.append(details["code"])
    for key in ("issues", "checks"):
        val = details.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and isinstance(item.get("code"), str):
                    codes.append(item["code"])
                if isinstance(item, dict) and item.get("status") in {"warn", "fail"} and isinstance(item.get("name"), str):
                    codes.append(item["name"])
    return codes


def summarize_events(path: str | Path | None = None, limit: int = 100) -> dict[str, Any]:
    events = read_events(path=path, limit=limit)
    by_status = Counter(e.get("status", "info") for e in events)
    by_type = Counter(e.get("event_type", "event") for e in events)
    by_component = Counter(e.get("component", "iagent") for e in events)
    issue_codes = Counter()
    for event in events:
        issue_codes.update(_extract_issue_codes(event))
    last = events[-1] if events else None
    return {"path": str(Path(path) if path is not None else _DEFAULT_PATH), "total": len(events), "by_status": dict(by_status), "by_type": dict(by_type), "by_component": dict(by_component), "issue_codes": dict(issue_codes), "last_event": last}


def status_card_from_summary(summary: dict[str, Any]) -> str:
    if not summary.get("total"):
        return "Ops journal is empty."
    counts = summary.get("by_status", {})
    parts = [f"Ops journal: {summary.get('total')} recent events"]
    parts.append("Status: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if summary.get("issue_codes"):
        top = sorted(summary["issue_codes"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        parts.append("Issues: " + ", ".join(f"{k}×{v}" for k, v in top))
    last = summary.get("last_event") or {}
    if last:
        parts.append(f"Last: {last.get('event_type')} / {last.get('component')} / {last.get('status')} — {last.get('message')}")
    return "\n".join(parts)


@register({"name": "read_ops_journal", "description": "Read recent redacted iAgent operations journal events. Tracks selftests, service repairs, warnings/failures, and useful issue codes.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 20}, "component": {"type": "string"}, "event_type": {"type": "string"}}, "required": []}})
async def read_ops_journal(limit: int = 20, component: str | None = None, event_type: str | None = None) -> str:
    return _json(await asyncio.to_thread(read_events, None, limit, component, event_type))


@register({"name": "summarize_ops_journal", "description": "Summarize recent redacted iAgent operations journal events as counts by status/type/component and known issue codes.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "default": 100}}, "required": []}})
async def summarize_ops_journal(limit: int = 100) -> str:
    summary = await asyncio.to_thread(summarize_events, None, limit)
    summary["status_card"] = status_card_from_summary(summary)
    return _json(summary)
