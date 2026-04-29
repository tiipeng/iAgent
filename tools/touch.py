"""Synthetic touch input via SimulateTouch's `stouch` binary.

SimulateTouch is a jailbreak tool that exposes a `stouch` CLI capable of
sending synthetic taps, swipes, and gestures to the iOS HID stack — the
same code path real fingers use. Combined with screenshot + GPT-4o vision,
this is what unlocks "look at the screen and tap that button" workflows.

Install via Sileo / apt: SimulateTouch (package name varies by repo).
Common binary path: /var/jb/usr/bin/stouch

Usage as documented:
    stouch touch x y [orientation]
    stouch swipe fromX fromY toX toY [duration]

We wrap each operation in an iAgent tool with sane defaults.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional

from tools.registry import register


_STOUCH_PATHS = [
    "/var/jb/usr/bin/stouch",
    "/var/jb/usr/local/bin/stouch",
    "/usr/bin/stouch",
]


def _find_stouch() -> Optional[str]:
    for p in _STOUCH_PATHS:
        if Path(p).exists():
            return p
    return shutil.which("stouch")


async def _run_stouch(args: list[str], timeout: float = 5.0) -> tuple[int, str]:
    bin_path = _find_stouch()
    if not bin_path:
        return -1, (
            "stouch not installed. Install SimulateTouch via Sileo: "
            "sudo apt search simulatetouch ; "
            "sudo apt install <package-name-from-search>"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            bin_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return -1, "stouch timed out"
    except Exception as exc:
        return -1, str(exc)


# ── Tools ─────────────────────────────────────────────────────────────────

@register({
    "name": "tap",
    "description": (
        "Send a synthetic tap at screen coordinates (x, y). "
        "Origin is top-left. Coordinates are in points (use take_screenshot "
        "to see the screen, then map pixel coordinates back to points by "
        "dividing by the device's scale factor — typically 2 for iPad)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate in points"},
            "y": {"type": "integer", "description": "Y coordinate in points"},
            "orientation": {
                "type": "integer",
                "description": "Optional orientation: 1=portrait, 2=landscape-left, 3=upside-down, 4=landscape-right",
            },
        },
        "required": ["x", "y"],
    },
})
async def tap(x: int, y: int, orientation: int = 0) -> str:
    args = ["touch", str(x), str(y)]
    if orientation in (1, 2, 3, 4):
        args.append(str(orientation))
    rc, out = await _run_stouch(args)
    if rc != 0:
        return f"[tap failed] {out}"
    return f"Tapped ({x}, {y})" + (f" — {out}" if out else "")


@register({
    "name": "swipe",
    "description": (
        "Send a synthetic swipe gesture from (from_x, from_y) to (to_x, to_y). "
        "Useful for scrolling, dragging, or navigating between apps. "
        "Duration in seconds (defaults to 0.3 — 0.5)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "from_x": {"type": "integer"},
            "from_y": {"type": "integer"},
            "to_x":   {"type": "integer"},
            "to_y":   {"type": "integer"},
            "duration": {
                "type": "number",
                "description": "Gesture duration in seconds (default 0.3)",
            },
        },
        "required": ["from_x", "from_y", "to_x", "to_y"],
    },
})
async def swipe(from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.3) -> str:
    args = ["swipe", str(from_x), str(from_y), str(to_x), str(to_y), str(duration)]
    rc, out = await _run_stouch(args)
    if rc != 0:
        return f"[swipe failed] {out}"
    return f"Swiped ({from_x},{from_y}) → ({to_x},{to_y}) over {duration}s"


@register({
    "name": "scroll",
    "description": (
        "Convenience wrapper around swipe for vertical scrolling. "
        "Direction 'up' scrolls content up (i.e. swipes up — reveals lower content); "
        "'down' scrolls content down. Defaults to ~half-screen scroll on iPad."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
            },
            "amount": {
                "type": "integer",
                "description": "Pixels of swipe distance (default 400)",
            },
        },
        "required": ["direction"],
    },
})
async def scroll(direction: str, amount: int = 400) -> str:
    # iPad mid-screen baseline
    cx, cy = 500, 500
    if direction == "up":
        return await swipe(cx, cy + amount // 2, cx, cy - amount // 2)
    if direction == "down":
        return await swipe(cx, cy - amount // 2, cx, cy + amount // 2)
    if direction == "left":
        return await swipe(cx + amount // 2, cy, cx - amount // 2, cy)
    if direction == "right":
        return await swipe(cx - amount // 2, cy, cx + amount // 2, cy)
    return f"[scroll] unknown direction {direction!r}"


@register({
    "name": "press_home",
    "description": (
        "Simulate a Home button press to return to the home screen. "
        "Uses Activator if available, else falls back to a long-distance "
        "swipe up from the bottom (works on Face ID / no-Home-button devices)."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def press_home() -> str:
    activator = shutil.which("activator") or "/var/jb/usr/bin/activator"
    if Path(activator).exists():
        try:
            proc = await asyncio.create_subprocess_exec(
                activator, "send", "libactivator.system.homebutton.press",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode == 0:
                return "Home button pressed (via Activator)"
        except Exception:
            pass
    # Fallback — swipe up from bottom (iPad without Home button gesture)
    return await swipe(500, 1300, 500, 100, duration=0.25)
