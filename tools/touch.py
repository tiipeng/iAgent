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
    """XXTouch Lite returns HTML at /; presence of any 200 response means
    the daemon is up. /version doesn't exist on Lite — don't probe it."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as c:
            r = await c.get(f"{_XXTOUCH_URL}/")
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

async def _xx_post(path: str, body: Optional[dict] = None) -> tuple[int, str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            if body is None:
                r = await c.post(f"{_XXTOUCH_URL}{path}")
            else:
                r = await c.post(f"{_XXTOUCH_URL}{path}", json=body)
            return r.status_code, r.text
    except Exception as e:
        return -1, f"XXTouch HTTP error: {e}"


# XXTouch Lite has no run-lua-string endpoint. Strategy: write a Lua snippet
# to the currently-selected script file on disk, then POST /launch_script_file.
# Path confirmed from XXTouch's bundled plist: scripts live under
# /private/var/mobile/Media/1ferver/lua/scripts/ (which is the same as
# /var/mobile/Media/1ferver/lua/scripts/ via the standard /private symlink).
_SCRIPT_DIRS = [
    Path("/var/mobile/Media/1ferver/lua/scripts"),
    Path("/private/var/mobile/Media/1ferver/lua/scripts"),
    # Fallbacks for older / non-standard installs
    Path("/var/jb/var/mobile/Media/1ferver/lua/scripts"),
    Path("/var/jb/var/mobile/Library/XXTouchLite/scripts"),
]


async def _xxtouch_selected_script() -> Optional[Path]:
    """Ask XXTouch which script is currently selected, then locate it on disk."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{_XXTOUCH_URL}/get_selected_script_file")
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("code") != 0:
            return None
        filename = data.get("data", {}).get("filename")
        if not filename:
            return None
    except Exception:
        return None
    for d in _SCRIPT_DIRS:
        p = d / filename
        if p.exists() or d.exists():
            return p
    return None


_XXTOUCH_ROOT = "/var/mobile/Media/1ferver"
_XXTOUCH_SCRIPTS_REL = "lua/scripts"


async def _xx_run_lua(script: str) -> str:
    """Save Lua snippet via XXTouch's API + select + launch.

    Wire confirmed from script_choose.js:
      /write_file  body: {filename: "lua/scripts/main.lua", data: <base64>}
      /select_script_file  body: {filename: "/var/mobile/Media/1ferver/lua/scripts/main.lua"}
      /launch_script_file  body: {} or empty
    """
    import base64
    filename = "main.lua"
    rel_path = f"{_XXTOUCH_SCRIPTS_REL}/{filename}"
    abs_path = f"{_XXTOUCH_ROOT}/{rel_path}"

    # 1. Write the script via the API. write_file accepts base64 in 'data'.
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    rc, body = await _xx_post("/write_file", {"filename": rel_path, "data": b64})
    if rc != 200 or '"code":0' not in body:
        return f"[XXTouch] write_file failed ({rc}): {body[:200]}"

    # 2. Select that exact script (XXTouch wants the full absolute path here).
    rc, body = await _xx_post("/select_script_file", {"filename": abs_path})
    if rc != 200 or '"code":0' not in body:
        return f"[XXTouch] select_script_file failed ({rc}): {body[:200]}"

    # 3. Launch it. XXTouch responses we tolerate as success:
    #    HTTP 200 with code:0  → kicked off
    #    httpx connection error → daemon dropped the connection on launch (normal)
    #    HTTP 200 with code:3 ("already running") → previous script still going
    rc, body = await _xx_post("/launch_script_file", {})
    if rc == -1:
        return f"[XXTouch] launched {len(script)}-byte Lua (connection dropped — normal)"
    if rc == 200:
        if '"code":0' in body:
            return f"[XXTouch] launched {len(script)}-byte Lua via {filename}"
        if '"code":3' in body:
            return "[XXTouch] previous script still running — request queued / collided"
        return f"[XXTouch] unexpected response: {body[:200]}"
    return f"[XXTouch] launch failed (HTTP {rc}): {body[:200]}"


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
        # XXTouch Lite has touch.tap(x, y) as a complete tap (down+up internally).
        # No usleep needed — that global doesn't exist in their Lua sandbox.
        script = f'nLog("iagent tap {x},{y}"); touch.tap({x}, {y})'
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
        # XXTouch Lite's touch namespace + ms-precision sleep names. The function
        # touch.swipe may exist; if not, the agent can fall back to a manual
        # on/move/off loop (timing handled by mSleep / sys.msleep — both are
        # commonly aliased). We try touch.swipe first because it's the simplest
        # call that XXTouch is most likely to ship.
        ms = max(50, int(duration * 1000))
        script = (
            f'nLog("iagent swipe {from_x},{from_y}->{to_x},{to_y}")\n'
            f"if touch.swipe then\n"
            f"  touch.swipe({from_x}, {from_y}, {to_x}, {to_y}, {ms})\n"
            f"else\n"
            f"  touch.on(1, {from_x}, {from_y})\n"
            f"  local steps = 16\n"
            f"  local sl = mSleep or (sys and sys.msleep) or function() end\n"
            f"  for i = 1, steps do\n"
            f"    local fx = {from_x} + ({to_x} - {from_x}) * i / steps\n"
            f"    local fy = {from_y} + ({to_y} - {from_y}) * i / steps\n"
            f"    touch.move(1, fx, fy)\n"
            f"    sl({ms} / steps)\n"
            f"  end\n"
            f"  touch.off(1)\n"
            f"end\n"
        )
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


# ── Screen capture via XXTouch ────────────────────────────────────────────

_SCREENSHOT_PATH = "/var/mobile/Media/1ferver/lua/scripts/iagent_screen.png"


@register({
    "name": "screenshot_xx",
    "description": (
        "Capture the current iPad screen using XXTouch's screen API. "
        "Saves a PNG to the workspace and returns the path. Faster and "
        "more reliable than the Shortcut-based take_screenshot — "
        "no user interaction needed. Use this to see what's on screen."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def screenshot_xx() -> str:
    if await _backend() != "xxtouch":
        return _NO_BACKEND_MSG
    # XXTouch's screen module: screen.image() returns an image object,
    # which has a :save_to_png(path) method. The exact API name varies
    # slightly by version; we try the common forms in one Lua snippet.
    lua = (
        f'local path = "{_SCREENSHOT_PATH}"\n'
        f'nLog("iagent screenshot to " .. path)\n'
        f"local ok, err = pcall(function()\n"
        f"  local img = screen.image()\n"
        f"  if img.save_to_png then\n"
        f"    img:save_to_png(path)\n"
        f"  elseif img.save then\n"
        f"    img:save(path)\n"
        f"  elseif screen.snap then\n"
        f"    screen.snap(path)\n"
        f"  else\n"
        f'    error("no known XXTouch screen save method")\n'
        f"  end\n"
        f"end)\n"
        f'if not ok then nLog("screenshot error: " .. tostring(err)) end\n'
    )
    out = await _xx_run_lua(lua)
    # Wait briefly for the file to appear
    import asyncio as _a
    for _ in range(10):
        if Path(_SCREENSHOT_PATH).exists():
            return _SCREENSHOT_PATH
        await _a.sleep(0.1)
    return f"[screenshot_xx] Lua ran but {_SCREENSHOT_PATH} did not appear: {out}"


@register({
    "name": "look_at_screen",
    "description": (
        "Take a screenshot, send it to the user via Telegram, AND ask GPT-4o "
        "vision to describe what's visible. Use this for 'what's on screen?', "
        "'find the X button', 'identify the WiFi cell location', etc. "
        "Optional question targets the description (e.g. 'where is the search bar?')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Optional specific question to answer about the screen",
            },
        },
        "required": [],
    },
})
async def look_at_screen(question: str = "") -> str:
    path = await screenshot_xx()
    if not Path(path).exists():
        return path  # error message

    # Send to Telegram chat (so the user sees the same image the agent sees)
    try:
        from tools.photo import send_photo, describe_photo
    except ImportError:
        return f"Screenshot at {path}"

    sent = await send_photo(path, caption="Screen snapshot")
    described = await describe_photo(
        path,
        question or "Describe everything visible on this iPad screen, "
                    "including UI elements, text, buttons, and their approximate "
                    "pixel coordinates (x, y) for anything tappable.",
    )
    return f"{sent}\n\n{described}"
