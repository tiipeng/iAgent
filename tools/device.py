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


_SHELL_CANDIDATES = ["/var/jb/bin/sh", "/bin/sh", "/var/jb/usr/bin/sh"]


def _find_shell() -> str:
    for s in _SHELL_CANDIDATES:
        if Path(s).exists():
            return s
    return "/bin/sh"


async def _sh(cmd: str, timeout: float = 8.0) -> str:
    sh = _find_shell()
    try:
        proc = await asyncio.create_subprocess_exec(
            sh, "-c", cmd,
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
        "Battery info unavailable. iOS doesn't expose battery via sysfs (Linux), "
        "and 'upower' is not in any Procursus / Sileo repo. "
        "Set up a Shortcut once:\n"
        "  1. Shortcuts app → New Shortcut.\n"
        "  2. 'Get Battery Level' action.\n"
        "  3. 'Get Battery State' action.\n"
        "  4. Combine into text and Return.\n"
        "  5. Name it exactly: iAgent Health.\n"
        "Then I can call read_health('battery')."
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
        "Screenshot unavailable. Set up a Shortcut once:\n"
        "  1. Open the Shortcuts app on the iPad.\n"
        "  2. New Shortcut → 'Take Screenshot' action.\n"
        "  3. 'Save File' → save to "
        f"{out_path} (Folder: On My iPad → iagent → workspace).\n"
        "  4. Name it exactly: iAgent Screenshot.\n"
        "Then ask me to take a screenshot again. "
        "(There is NO Procursus package for screencapture — don't ask to apt install one.)"
    )


# ── Sensors / sysctl ──────────────────────────────────────────────────────

# Common sysctl names worth surfacing on iOS jailbreak. Not all are present on
# every device — get_sensor returns "(unavailable)" if a key doesn't exist.
_SYSCTL_BY_TOPIC = {
    "battery":     ["hw.batterycount", "hw.battery.voltage", "hw.battery.capacity"],
    "thermal":     ["hw.tmp", "hw.cputype", "machdep.xcpm.cpu_thermal_level"],
    "memory":      ["hw.memsize", "hw.physmem", "hw.usermem", "vm.page_free_count"],
    "cpu":         ["hw.ncpu", "hw.cpufrequency", "hw.cpufamily", "hw.cputype",
                    "hw.cpusubtype", "hw.cpu64bit_capable"],
    "device":      ["hw.machine", "hw.model", "hw.targettype", "kern.hostname",
                    "kern.osversion", "kern.osrelease", "kern.ostype"],
    "network":     ["net.inet.ip.forwarding", "net.inet.tcp.sendspace"],
    "uptime":      ["kern.boottime"],
    "load":        ["vm.loadavg"],
}

_SYS_FILES = {
    "battery":  "/sys/class/power_supply/battery/uevent",
    "thermal":  "/sys/class/thermal/thermal_zone0/temp",
    "memory":   "/proc/meminfo",
    "cpuinfo":  "/proc/cpuinfo",
    "stat":     "/proc/stat",
    "loadavg":  "/proc/loadavg",
    "uptime":   "/proc/uptime",
}


@register({
    "name": "list_sensors",
    "description": (
        "List every sensor / sysctl / sys-file the agent can read on this device. "
        "Returns a grouped list of topic names (battery, thermal, memory, cpu, "
        "device, network, uptime, load) plus available /sys and /proc files."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def list_sensors() -> str:
    lines = ["sysctl groups (use get_sensor):"]
    for topic, keys in _SYSCTL_BY_TOPIC.items():
        lines.append(f"  • {topic}: {', '.join(keys)}")
    lines.append("\n/sys + /proc files (use file_read):")
    for name, path in _SYS_FILES.items():
        exists = "✓" if Path(path).exists() else "✗"
        lines.append(f"  {exists} {name}: {path}")
    return "\n".join(lines)


@register({
    "name": "get_sensor",
    "description": (
        "Read a sensor / sysctl topic. Pass one of the topic names from list_sensors "
        "(e.g. 'battery', 'thermal', 'memory', 'cpu', 'device'). "
        "Returns the values of every sysctl key in that group."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "One of: battery, thermal, memory, cpu, device, network, uptime, load",
            },
        },
        "required": ["topic"],
    },
})
async def get_sensor(topic: str) -> str:
    keys = _SYSCTL_BY_TOPIC.get(topic.lower())
    if not keys:
        return f"Unknown topic '{topic}'. Try one of: {', '.join(_SYSCTL_BY_TOPIC)}"

    lines = []
    for k in keys:
        val = await _sh(f"sysctl -n {k} 2>/dev/null")
        if val and "(error)" not in val:
            lines.append(f"{k} = {val}")
        else:
            lines.append(f"{k} = (unavailable)")
    return "\n".join(lines)


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
