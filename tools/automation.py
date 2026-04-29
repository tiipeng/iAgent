"""Automation tools — open URLs / apps, respring, generate Shortcuts.

What works on rootless Dopamine without extra tweaks:
  - uiopen: launch any URL or bundle ID
  - lsappinfo: list installed apps
  - killall SpringBoard: respring
  - generate .shortcut plist: user taps once in Files to install

What does NOT work without an extra jailbreak tweak:
  - synthetic touch (taps, swipes) — needs AutoTouch / simulatetouch
  - reading other apps' UI state — iOS sandbox blocks it
  - full silent shortcut install — user must approve "Allow Untrusted Shortcuts"
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))
_WORKSPACE = _IAGENT_HOME / "workspace"


def _which(name: str) -> Optional[str]:
    for prefix in ("/var/jb/usr/bin/", "/var/jb/usr/sbin/", "/var/jb/bin/"):
        p = prefix + name
        if Path(p).exists():
            return p
    return shutil.which(name)


async def _run(args: list, timeout: float = 10.0) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return -1, f"(timed out after {timeout:.0f}s)"
    except Exception as exc:
        return -1, f"(error: {exc})"


# ── Open URL / app ────────────────────────────────────────────────────────

@register({
    "name": "open_url",
    "description": (
        "Open any URL on the device — http(s), tel:, mailto:, app deep links "
        "(spotify://, photos-redirect://), or shortcuts:// schemes. "
        "Brings the matching app to the foreground."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL or deep link to open"},
        },
        "required": ["url"],
    },
})
async def open_url(url: str) -> str:
    bin_path = _which("uiopen")
    if not bin_path:
        return "[open_url] uiopen not installed. apt install uikittools"
    rc, out = await _run([bin_path, url])
    if rc != 0:
        return f"[open_url failed] {out}"
    return f"Opened: {url}"


@register({
    "name": "open_app",
    "description": (
        "Launch an iOS app by bundle ID (e.g. 'com.apple.Preferences', "
        "'com.spotify.client', 'com.apple.shortcuts'). "
        "Use list_apps to discover bundle IDs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bundle_id": {
                "type": "string",
                "description": "iOS bundle identifier (com.example.app)",
            },
        },
        "required": ["bundle_id"],
    },
})
async def open_app(bundle_id: str) -> str:
    bin_path = _which("uiopen")
    if not bin_path:
        return "[open_app] uiopen not installed. apt install uikittools"
    rc, out = await _run([bin_path, "-b", bundle_id])
    if rc != 0:
        return f"[open_app failed] {out}"
    return f"Launched: {bundle_id}"


@register({
    "name": "list_apps",
    "description": (
        "List all apps installed on the device with their bundle IDs and names. "
        "Useful before open_app. Output may be long — agent should grep for what it needs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Optional substring to match against name or bundle ID",
            },
        },
        "required": [],
    },
})
async def list_apps(filter: str = "") -> str:
    bin_path = _which("lsappinfo")
    if not bin_path:
        return "[list_apps] lsappinfo not installed. apt install uikittools"
    rc, out = await _run([bin_path, "list"], timeout=20.0)
    if rc != 0:
        return f"[list_apps failed] {out}"
    if filter:
        f = filter.lower()
        lines = [l for l in out.splitlines() if f in l.lower()]
        out = "\n".join(lines)
    return out or "(no apps matched filter)"


# ── SpringBoard control ───────────────────────────────────────────────────

@register({
    "name": "respring",
    "description": (
        "Restart SpringBoard (the iOS home screen). Safe — does not reboot the "
        "device. Useful after installing tweaks or to reset UI state."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def respring() -> str:
    rc, out = await _run(["killall", "-9", "SpringBoard"])
    if rc != 0:
        return f"[respring] killall failed: {out}"
    return "SpringBoard killed — UI will reload in a few seconds."


# ── (Shortcut generation removed — Shortcuts integration is gone) ────────
