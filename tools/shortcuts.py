"""iOS Shortcuts bridge — run and list Shortcuts from the agent.

Uses the `shortcuts` CLI (available on Dopamine/rootless):
  shortcuts run "<name>" [--input-path <file>]
  shortcuts list

This unlocks HealthKit, HomeKit, Photos, Reminders, Contacts, etc.
The user must create the Shortcuts in the iOS Shortcuts app first.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile

from tools.registry import register

_SHORTCUTS_BIN = "/var/jb/usr/bin/shortcuts"


def _has_shortcuts() -> bool:
    return bool(shutil.which("shortcuts") or shutil.which(_SHORTCUTS_BIN))


@register({
    "name": "run_shortcut",
    "description": (
        "Run a named iOS Shortcut. Optionally pass a text input string. "
        "Returns whatever text the Shortcut outputs. Use this to access "
        "HealthKit, HomeKit, Photos, Reminders, Contacts, and any other "
        "iOS feature exposed via the Shortcuts app."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Exact name of the Shortcut as it appears in the Shortcuts app",
            },
            "input": {
                "type": "string",
                "description": "Optional text to pass as input to the Shortcut",
            },
        },
        "required": ["name"],
    },
})
async def run_shortcut(name: str, input: str = "") -> str:
    bin_path = _SHORTCUTS_BIN if shutil.which(_SHORTCUTS_BIN) else "shortcuts"
    if not shutil.which(bin_path):
        return (
            "[Shortcuts unavailable] The `shortcuts` CLI is not installed. "
            "Install it via Sileo (package: shortcuts-cli) or create the "
            "Shortcut to accept text input and call it differently."
        )

    cmd = [bin_path, "run", name]

    if input:
        # Write input to a temp file and pass via --input-path
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(input)
            tmp_path = f.name
        cmd += ["--input-path", tmp_path]
    else:
        tmp_path = None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            return f"[Shortcut '{name}' failed (exit {proc.returncode})]\n{err or out}"
        return out or "(Shortcut ran successfully with no output)"
    except asyncio.TimeoutError:
        return f"[Shortcut '{name}' timed out after 30s]"
    finally:
        if tmp_path:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@register({
    "name": "list_shortcuts",
    "description": (
        "List all Shortcuts installed on this device. "
        "Returns their names, one per line."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def list_shortcuts() -> str:
    bin_path = _SHORTCUTS_BIN if shutil.which(_SHORTCUTS_BIN) else "shortcuts"
    if not shutil.which(bin_path):
        return "[Shortcuts unavailable] The `shortcuts` CLI is not installed."

    try:
        proc = await asyncio.create_subprocess_exec(
            bin_path, "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        out = stdout.decode(errors="replace").strip()
        if not out:
            return "No Shortcuts found (or the shortcuts CLI returned nothing)."
        return out
    except asyncio.TimeoutError:
        return "[list_shortcuts timed out]"
