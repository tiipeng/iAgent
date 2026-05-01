from __future__ import annotations
import asyncio, json
from typing import Any
from tools.registry import register


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _icon(status: str | None) -> str:
    return {"ok": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭️", "info": "ℹ️"}.get(status or "info", "ℹ️")


def _label(name: str) -> str:
    labels = {
        "iagent_runtime": "iAgent runtime",
        "tool_registry": "Tool registry",
        "homebridge_service": "Homebridge",
        "xxtouch_http": "XXTouch",
        "ios_mcp_http": "ios-mcp",
        "battery_probe": "Battery",
        "history_sanitizer": "History sanitizer",
    }
    return labels.get(name, name.replace("_", " ").title())


def _find_check(selftest: dict[str, Any], name: str) -> dict[str, Any]:
    for check in selftest.get("checks", []) or []:
        if check.get("name") == name:
            return check
    return {"name": name, "status": "skip", "message": "not checked", "details": {}}


def _ports_text(details: dict[str, Any]) -> str:
    ports = details.get("ports") or {}
    if not isinstance(ports, dict) or not ports:
        return ""
    parts = []
    for port, state in sorted(ports.items(), key=lambda kv: str(kv[0])):
        parts.append(f"{port} {state}")
    return " (" + ", ".join(parts) + ")"


def format_selftest_card(selftest: dict[str, Any]) -> str:
    status = selftest.get("status", "info")
    summary = selftest.get("summary", {}) or {}
    counts = summary.get("counts", {}) or summary.get("by_status", {}) or {}
    title = f"{_icon(status)} Steve/iAgent Status: {str(status).upper()}"
    lines = [title]
    if counts:
        lines.append("Checks: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for name in ["iagent_runtime", "tool_registry", "homebridge_service", "xxtouch_http", "ios_mcp_http", "battery_probe", "history_sanitizer"]:
        check = _find_check(selftest, name)
        details = check.get("details") if isinstance(check.get("details"), dict) else {}
        extra = _ports_text(details) if name == "homebridge_service" else ""
        message = check.get("message") or ""
        if len(message) > 90:
            message = message[:87] + "..."
        lines.append(f"{_icon(check.get('status'))} {_label(name)}{extra} — {message}")
    return "\n".join(lines)


def format_journal_card(summary: dict[str, Any] | None) -> str:
    if not summary or not summary.get("total"):
        return "📘 Journal: empty"
    lines = [f"📘 Journal: {summary.get('total')} recent events"]
    by_status = summary.get("by_status") or {}
    if by_status:
        lines.append("Status: " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    issue_codes = summary.get("issue_codes") or {}
    if issue_codes:
        top = sorted(issue_codes.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        lines.append("Issues: " + ", ".join(f"{k}×{v}" for k, v in top))
    last = summary.get("last_event") or {}
    if last:
        msg = last.get("message") or ""
        if len(msg) > 90:
            msg = msg[:87] + "..."
        lines.append(f"Last: {last.get('event_type')} / {last.get('component')} / {last.get('status')} — {msg}")
    return "\n".join(lines)


def format_known_blockers_card() -> str:
    return "\n".join([
        "Known blockers:",
        "⚠️ Ring — refresh token/auth still needed before devices can work.",
        "⚠️ Samsung TV — pairing may need TV awake + physical Allow popup.",
        "⚠️ Dyson — integration not finalized yet.",
    ])


def format_ops_status_card(selftest: dict[str, Any], journal_summary: dict[str, Any] | None = None, include_blockers: bool = True) -> str:
    parts = [format_selftest_card(selftest)]
    if journal_summary is not None:
        parts.append(format_journal_card(journal_summary))
    if include_blockers:
        parts.append(format_known_blockers_card())
    return "\n\n".join(parts)


def status_card_sync(live: bool = True, include_journal: bool = True, journal_limit: int = 20, include_blockers: bool = True) -> dict[str, Any]:
    from tools.selftest import selftest_sync
    selftest = selftest_sync(live=live)
    journal = None
    if include_journal:
        from tools.ops_journal import summarize_events
        journal = summarize_events(limit=journal_limit)
    return {
        "status": selftest.get("status"),
        "selftest": selftest,
        "journal": journal,
        "card": format_ops_status_card(selftest, journal, include_blockers=include_blockers),
    }


@register({"name": "format_status_card", "description": "Format given selftest/journal data into a human-readable Telegram-friendly iAgent status card.", "parameters": {"type": "object", "properties": {"selftest": {"type": "object"}, "journal_summary": {"type": "object"}, "include_blockers": {"type": "boolean", "default": True}}, "required": ["selftest"]}})
async def format_status_card(selftest: dict[str, Any], journal_summary: dict[str, Any] | None = None, include_blockers: bool = True) -> str:
    return format_ops_status_card(selftest, journal_summary, include_blockers=include_blockers)


@register({"name": "get_status_card", "description": "Run iAgent selftest and ops-journal summary, then return a Telegram-friendly status card for Steve/iAgent, Homebridge, XXTouch, ios-mcp, battery, and known blockers.", "parameters": {"type": "object", "properties": {"live": {"type": "boolean", "default": True}, "include_journal": {"type": "boolean", "default": True}, "journal_limit": {"type": "integer", "default": 20}, "include_blockers": {"type": "boolean", "default": True}}, "required": []}})
async def get_status_card(live: bool = True, include_journal: bool = True, journal_limit: int = 20, include_blockers: bool = True) -> str:
    result = await asyncio.to_thread(status_card_sync, live, include_journal, journal_limit, include_blockers)
    return result["card"]
