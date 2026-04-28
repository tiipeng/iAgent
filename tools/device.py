"""Device info tools — battery, screenshot, brightness, device identity.

These run directly via shell or Shortcuts so the agent never has to guess
the right command. Always available; no extra packages required for basic use.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))
_SHORTCUTS_BIN = "/var/jb/usr/bin/shortcuts"


async def _sh(cmd: str, timeout: float = 8.0) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return out.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return "(timed out)"
    except Exception as exc:
        return f"(error: {exc})"


def _shortcuts_bin() -> str:
    for p in (_SHORTCUTS_BIN, "shortcuts"):
        if shutil.which(p):
            return p
    return ""


# ── Battery ───────────────────────────────────────────────────────────────

@register({
    "name": "get_battery",
    "description": (
        "Get the device's current battery percentage and charging status. "
        "Works without any extra packages on jailbroken iOS."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def get_battery() -> str:
    # Primary: Linux sysfs (exposed by Dopamine/Procursus kernel)
    capacity = await _sh("cat /sys/class/power_supply/battery/capacity 2>/dev/null")
    status   = await _sh("cat /sys/class/power_supply/battery/status 2>/dev/null")
    if capacity and capacity.isdigit():
        charging = ""
        if status:
            charging = " — " + status
        return f"{capacity}%{charging}"

    # Fallback: upower
    upower = await _sh(
        "upower -i $(upower -e 2>/dev/null | grep -i battery | head -1) 2>/dev/null "
        "| grep -E 'percentage|state'"
    )
    if upower:
        return upower

    # Fallback: SpringBoard battery via activator or sysctl
    sysctl = await _sh("sysctl -n hw.battery.capacity hw.battery.voltage 2>/dev/null")
    if sysctl:
        return sysctl

    return (
        "Battery info unavailable via sysfs. "
        "Try installing 'upower' from Sileo, or ask me to create an 'iAgent Health' Shortcut."
    )


# ── Device info ───────────────────────────────────────────────────────────

@register({
    "name": "get_device_info",
    "description": (
        "Return hardware and OS info: device model, iOS version, kernel, uptime, CPU, RAM."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def get_device_info() -> str:
    parts = await asyncio.gather(
        _sh("uname -a 2>/dev/null"),
        _sh("sysctl -n hw.machine 2>/dev/null"),
        _sh("sw_vers 2>/dev/null || cat /etc/os-release 2>/dev/null | head -5"),
        _sh("uptime 2>/dev/null"),
        _sh("sysctl -n hw.memsize 2>/dev/null"),
    )
    labels = ["Kernel", "Machine", "OS", "Uptime", "RAM (bytes)"]
    lines = [f"{l}: {v}" for l, v in zip(labels, parts) if v and "(error)" not in v]
    return "\n".join(lines) or "Device info unavailable"


# ── Screenshot ────────────────────────────────────────────────────────────

@register({
    "name": "take_screenshot",
    "description": (
        "Take a screenshot of the current screen. "
        "Saves to $IAGENT_HOME/workspace/screenshot.png and returns the path. "
        "Requires a Shortcut named 'iAgent Screenshot': "
        "Take Screenshot → Save to File ($IAGENT_HOME/workspace/screenshot.png) → return path. "
        "Alternatively, if 'screencapture-ios' is installed via Sileo, uses that."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def take_screenshot() -> str:
    out_path = str(_IAGENT_HOME / "workspace" / "screenshot.png")

    # Try native CLI tool first (Procursus package: screencapture-ios or similar)
    for candidate in ("/var/jb/usr/bin/screencapture", "screencapture"):
        if shutil.which(candidate):
            result = await _sh(f"{candidate} -x {out_path}")
            if Path(out_path).exists():
                return f"Screenshot saved to {out_path}"
            return f"screencapture ran but file not found: {result}"

    # Fallback: Shortcuts bridge
    sc = _shortcuts_bin()
    if sc:
        try:
            proc = await asyncio.create_subprocess_exec(
                sc, "run", "iAgent Screenshot",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            out = stdout.decode(errors="replace").strip()
            if Path(out_path).exists():
                return f"Screenshot saved to {out_path}"
            if out:
                return out
        except asyncio.TimeoutError:
            pass

    return (
        "Screenshot unavailable. Options:\n"
        "1. Create a Shortcut named 'iAgent Screenshot': "
        "Take Screenshot → Save to File → return path\n"
        "2. Install 'screencapture-ios' via Sileo"
    )


# ── Screen brightness ─────────────────────────────────────────────────────

@register({
    "name": "set_brightness",
    "description": (
        "Set the screen brightness (0.0 = off, 1.0 = full). "
        "Requires a Shortcut named 'iAgent Brightness' that accepts a number (0–1) as input."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "level": {
                "type": "number",
                "description": "Brightness level between 0.0 and 1.0",
            },
        },
        "required": ["level"],
    },
})
async def set_brightness(level: float) -> str:
    level = max(0.0, min(1.0, level))
    sc = _shortcuts_bin()
    if not sc:
        return "[set_brightness] shortcuts CLI not found — install shortcuts-cli via Sileo"

    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(str(round(level, 2)))
        tmp = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            sc, "run", "iAgent Brightness", "--input-path", tmp,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return f"Brightness set to {int(level * 100)}%"
    except asyncio.TimeoutError:
        return "[set_brightness] timed out"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
