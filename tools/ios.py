"""iOS-specific tools — Shortcuts bridges for HealthKit, HomeKit, Reminders,
Location, Music, Files, and more.

Phase 3.5. Each tool requires the user to create one Shortcut in the
Shortcuts app. The Shortcut name and expected behaviour is documented in
each tool's description. All Shortcuts receive text input and return text.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Optional

from tools.registry import register

_SHORTCUTS_BIN = "/var/jb/usr/bin/shortcuts"


def _shortcuts_bin() -> str:
    if shutil.which(_SHORTCUTS_BIN):
        return _SHORTCUTS_BIN
    if shutil.which("shortcuts"):
        return "shortcuts"
    return ""


async def _run(name: str, input_text: str = "", timeout: float = 30.0) -> str:
    bin_path = _shortcuts_bin()
    if not bin_path:
        return "[Shortcuts unavailable] Install shortcuts-cli via Sileo."

    cmd = [bin_path, "run", name]
    tmp_path: Optional[str] = None

    if input_text:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(input_text)
            tmp_path = f.name
        cmd += ["--input-path", tmp_path]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode or 0
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if rc != 0:
            return f"[Shortcut '{name}' failed (exit {rc})] {err or out}"
        return out or f"(Shortcut '{name}' ran with no output)"
    except asyncio.TimeoutError:
        return f"[Shortcut '{name}' timed out after {timeout:.0f}s]"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Health ────────────────────────────────────────────────────────────────

@register({
    "name": "read_health",
    "description": (
        "Read a HealthKit metric for today (steps, heart_rate, sleep, calories, "
        "distance, flights_climbed, active_minutes, weight). "
        "Requires Shortcut 'iAgent Health': accepts metric name as input, "
        "queries HealthKit, returns the value as text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "Metric to read: steps, heart_rate, sleep, calories, distance, weight, …",
            },
        },
        "required": ["metric"],
    },
})
async def read_health(metric: str) -> str:
    return await _run("iAgent Health", metric)


# ── HomeKit ───────────────────────────────────────────────────────────────

@register({
    "name": "set_home_scene",
    "description": (
        "Trigger a HomeKit scene by name (e.g. 'Good Night', 'Movie Mode', 'Morning'). "
        "Requires Shortcut 'iAgent HomeKit': accepts scene name as input, "
        "triggers the matching HomeKit scene."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scene": {
                "type": "string",
                "description": "HomeKit scene name exactly as it appears in the Home app",
            },
        },
        "required": ["scene"],
    },
})
async def set_home_scene(scene: str) -> str:
    return await _run("iAgent HomeKit", scene)


# ── Reminders ─────────────────────────────────────────────────────────────

@register({
    "name": "create_reminder",
    "description": (
        "Add a reminder to the iOS Reminders app. "
        "Requires Shortcut 'iAgent Reminder': accepts 'text|due_date' as input "
        "(pipe-separated), creates the reminder. due_date is optional ISO-8601 string."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Reminder text",
            },
            "due": {
                "type": "string",
                "description": "Optional due date/time in ISO-8601 format (e.g. '2026-05-01T09:00:00')",
            },
        },
        "required": ["text"],
    },
})
async def create_reminder(text: str, due: str = "") -> str:
    payload = f"{text}|{due}" if due else text
    return await _run("iAgent Reminder", payload)


# ── Calendar ──────────────────────────────────────────────────────────────

@register({
    "name": "create_calendar_event",
    "description": (
        "Add an event to the iOS Calendar app. "
        "Requires Shortcut 'iAgent Calendar': accepts 'title|start|end|notes' "
        "as pipe-separated input and creates the event."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start time ISO-8601 (e.g. '2026-05-01T14:00:00')"},
            "end":   {"type": "string", "description": "End time ISO-8601"},
            "notes": {"type": "string", "description": "Optional notes / description"},
        },
        "required": ["title", "start", "end"],
    },
})
async def create_calendar_event(title: str, start: str, end: str, notes: str = "") -> str:
    payload = "|".join([title, start, end, notes])
    return await _run("iAgent Calendar", payload)


# ── Location ──────────────────────────────────────────────────────────────

@register({
    "name": "get_location",
    "description": (
        "Get the device's current GPS coordinates and address. "
        "Requires Shortcut 'iAgent Location': returns 'lat,lon\\naddress' as text."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def get_location() -> str:
    return await _run("iAgent Location", timeout=15.0)


# ── Music ─────────────────────────────────────────────────────────────────

@register({
    "name": "play_music",
    "description": (
        "Search and play music in the Apple Music app. "
        "Requires Shortcut 'iAgent Music': accepts a search query as input "
        "and plays the top match."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Song title, artist, album, or playlist name",
            },
        },
        "required": ["query"],
    },
})
async def play_music(query: str) -> str:
    return await _run("iAgent Music", query)


# ── Files (iCloud Drive) ──────────────────────────────────────────────────

@register({
    "name": "save_to_files",
    "description": (
        "Save a text string to the iOS Files app (iCloud Drive / On My iPad). "
        "Requires Shortcut 'iAgent Save File': accepts 'filename|content' as "
        "pipe-separated input and saves the file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Target filename (e.g. 'notes.txt', 'report.md')",
            },
            "content": {
                "type": "string",
                "description": "Text content to save",
            },
        },
        "required": ["filename", "content"],
    },
})
async def save_to_files(filename: str, content: str) -> str:
    payload = f"{filename}|{content}"
    return await _run("iAgent Save File", payload)


# ── Messages ──────────────────────────────────────────────────────────────

@register({
    "name": "send_imessage",
    "description": (
        "Send an iMessage or SMS. "
        "Requires Shortcut 'iAgent Message': accepts 'recipient|message' as "
        "pipe-separated input. recipient can be a phone number or contact name."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "Phone number (+491234567890) or contact name",
            },
            "message": {
                "type": "string",
                "description": "Message text to send",
            },
        },
        "required": ["recipient", "message"],
    },
})
async def send_imessage(recipient: str, message: str) -> str:
    payload = f"{recipient}|{message}"
    return await _run("iAgent Message", payload)
