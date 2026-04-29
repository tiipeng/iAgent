"""Synthetic touch input.

Two backends supported, in preference order:

1. **XXTouch** (ch.xxtou.xxtouch) — runs a local HTTP API server on
   port 46952. Modern, rootless-compatible, but paid via Sileo.

2. **SimulateTouch** (`stouch` binary) — older, free, but rarely in
   default Procursus repos.

Both are auto-detected. If neither is present, every call returns a
clear error and points the user at install options.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Optional

import httpx

from tools.registry import register

# ── Backend detection ─────────────────────────────────────────────────────

_STOUCH_PATHS = [
    "/var/jb/usr/bin/stouch",
    "/var/jb/usr/local/bin/stouch",
    "/usr/bin/stouch",
]
_XXTOUCH_URL = "http://127.0.0.1:46952"


def _find_stouch() -> Optional[str]:
    for p in _STOUCH_PATHS:
        if Path(p).exists():
            return p
    return shutil.which("stouch")


async def _xxtouch_alive() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.0) as c:
            r = await c.get(f"{_XXTOUCH_URL}/version")
            return r.status_code == 200
    except Exception:
        return False


async def _backend() -> str:
    if _find_stouch():
        return "stouch"
    if await _xxtouch_alive():
        return "xxtouch"
    return "none"


_NO_BACKEND_MSG = (
    "No synthetic-touch backend installed.\n"
    "Options:\n"
    "  1. XXTouch (paid, modern):  sudo apt install ch.xxtou.xxtouch\n"
    "  2. SimulateTouch (free): not in your current repos. Add one of these "
    "Sileo repos that ship it: https://repo.dynastic.co/  or  "
    "https://repo.bingner.com/  then sudo apt install simulatetouch\n"
    "After installing, ask me to retry the action."
)


# ── stouch backend ────────────────────────────────────────────────────────

async def _stouch(args: list[str]) -> tuple[int, str]:
    bin_path = _find_stouch()
    if not bin_path:
        return -1, _NO_BACKEND_MSG
    try:
        proc = await asyncio.create_subprocess_exec(
            bin_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        return proc.returncode or 0, out.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return -1, "stouch timed out"


# ── XXTouch HTTP backend ──────────────────────────────────────────────────

async def _xx_post(path: str, body: dict) -> tuple[int, str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(f"{_XXTOUCH_URL}{path}", json=body)
            return r.status_code, r.text
    except Exception as e:
        return -1, f"XXTouch HTTP error: {e}"


async def _xx_run_lua(script: str) -> str:
    """Run a Lua snippet via XXTouch and return its stdout/result."""
    rc, body = await _xx_post("/command/run_lua_string", {"lua_string": script})
    if rc != 200:
        return f"[XXTouch lua failed {rc}] {body[:300]}"
    return body[:1000]


# ── Tools ─────────────────────────────────────────────────────────────────

@register({
    "name": "tap",
    "description": (
        "Send a synthetic tap at screen coordinates (x, y). "
        "Origin is top-left. Coordinates in pixels (XXTouch backend) or "
        "points (stouch backend). Use take_screenshot to see the screen, "
        "then map identified pixel coords to tap()."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["x", "y"],
    },
})
async def tap(x: int, y: int) -> str:
    backend = await _backend()
    if backend == "stouch":
        rc, out = await _stouch(["touch", str(x), str(y)])
        return f"Tapped ({x}, {y})" if rc == 0 else f"[tap] {out}"
    if backend == "xxtouch":
        # XXTouch Lua API — `touch` global object
        script = f"touch.on(1, {x}, {y}); usleep(50000); touch.off(1)"
        out = await _xx_run_lua(script)
        return f"Tapped ({x}, {y}) via XXTouch — {out}"
    return _NO_BACKEND_MSG


@register({
    "name": "swipe",
    "description": (
        "Send a synthetic swipe gesture from (from_x, from_y) to (to_x, to_y) "
        "over `duration` seconds. Used for scrolling, dragging, app switching."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "from_x": {"type": "integer"},
            "from_y": {"type": "integer"},
            "to_x":   {"type": "integer"},
            "to_y":   {"type": "integer"},
            "duration": {"type": "number", "description": "seconds, default 0.3"},
        },
        "required": ["from_x", "from_y", "to_x", "to_y"],
    },
})
async def swipe(from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.3) -> str:
    backend = await _backend()
    if backend == "stouch":
        rc, out = await _stouch(["swipe", str(from_x), str(from_y),
                                  str(to_x), str(to_y), str(duration)])
        return f"Swiped {from_x},{from_y} → {to_x},{to_y}" if rc == 0 else f"[swipe] {out}"
    if backend == "xxtouch":
        steps = max(8, int(duration * 50))
        per_step_us = max(2000, int((duration * 1_000_000) / steps))
        script = f"""
        local x1, y1, x2, y2, n = {from_x}, {from_y}, {to_x}, {to_y}, {steps}
        touch.on(1, x1, y1)
        for i = 1, n do
            local fx = x1 + (x2 - x1) * i / n
            local fy = y1 + (y2 - y1) * i / n
            touch.move(1, fx, fy)
            usleep({per_step_us})
        end
        touch.off(1)
        """
        out = await _xx_run_lua(script)
        return f"Swiped via XXTouch ({from_x},{from_y})→({to_x},{to_y}) — {out}"
    return _NO_BACKEND_MSG


@register({
    "name": "scroll",
    "description": (
        "Vertical/horizontal scroll convenience wrapper around swipe. "
        "Direction 'up' reveals lower content (swipes finger up). "
        "Defaults to a ~half-screen scroll on iPad."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "integer", "description": "pixels (default 400)"},
        },
        "required": ["direction"],
    },
})
async def scroll(direction: str, amount: int = 400) -> str:
    cx, cy = 500, 500
    half = amount // 2
    if direction == "up":
        return await swipe(cx, cy + half, cx, cy - half)
    if direction == "down":
        return await swipe(cx, cy - half, cx, cy + half)
    if direction == "left":
        return await swipe(cx + half, cy, cx - half, cy)
    if direction == "right":
        return await swipe(cx - half, cy, cx + half, cy)
    return f"[scroll] unknown direction {direction!r}"


@register({
    "name": "press_home",
    "description": (
        "Return to the home screen. Uses Activator if available, else swipes "
        "up from the bottom edge (works on Face ID iPads / no Home button)."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def press_home() -> str:
    activator = "/var/jb/usr/bin/activator"
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
    return await swipe(500, 1300, 500, 100, duration=0.25)


@register({
    "name": "touch_backend_status",
    "description": (
        "Report which synthetic-touch backend is active (XXTouch / stouch / none). "
        "Useful before attempting tap/swipe to predict whether they'll succeed."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def touch_backend_status() -> str:
    backend = await _backend()
    if backend == "stouch":
        return f"Active: stouch at {_find_stouch()}"
    if backend == "xxtouch":
        return f"Active: XXTouch HTTP API at {_XXTOUCH_URL}"
    return _NO_BACKEND_MSG
