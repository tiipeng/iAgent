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
import json
import os
import plistlib
import shutil
import uuid
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


# ── Shortcut generation ───────────────────────────────────────────────────

# Minimal Shortcuts.app file format — the WFWorkflowActions array is what
# the Shortcuts app reads. Each action is a dict with WFWorkflowActionIdentifier
# (the action type) and WFWorkflowActionParameters (its config).

_KNOWN_ACTIONS = {
    "show_notification": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
        "param_keys": {"text": "WFNotificationActionBody",
                       "title": "WFNotificationActionTitle"},
    },
    "speak_text": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.speaktext",
        "param_keys": {"text": "WFText"},
    },
    "get_clipboard": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.getclipboard",
        "param_keys": {},
    },
    "set_clipboard": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.setclipboard",
        "param_keys": {"text": "WFTextActionText"},
    },
    "take_photo": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.takephoto",
        "param_keys": {},
    },
    "take_screenshot": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.takescreenshot",
        "param_keys": {},
    },
    "get_location": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.location",
        "param_keys": {},
    },
    "get_battery_level": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.getbatterylevel",
        "param_keys": {},
    },
    "get_current_song": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.getcurrentsong",
        "param_keys": {},
    },
    "play_music": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.playmusic",
        "param_keys": {},
    },
    "open_url": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.openurl",
        "param_keys": {"url": "WFInput"},
    },
    "url": {
        "WFWorkflowActionIdentifier": "is.workflow.actions.url",
        "param_keys": {"url": "WFURLActionURL"},
    },
}


def _build_action(action_name: str, params: dict) -> Optional[dict]:
    spec = _KNOWN_ACTIONS.get(action_name)
    if not spec:
        return None
    plist_params = {}
    for friendly, plist_key in spec["param_keys"].items():
        if friendly in params:
            plist_params[plist_key] = params[friendly]
    return {
        "WFWorkflowActionIdentifier": spec["WFWorkflowActionIdentifier"],
        "WFWorkflowActionParameters": plist_params,
    }


@register({
    "name": "list_shortcut_actions",
    "description": (
        "List the action types create_shortcut understands when generating a "
        ".shortcut file directly. For anything beyond these, walk the user "
        "through creating it in the Shortcuts app instead."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def list_shortcut_actions() -> str:
    lines = []
    for name, spec in _KNOWN_ACTIONS.items():
        params = list(spec["param_keys"].keys())
        param_str = "(" + ", ".join(params) + ")" if params else "(no params)"
        lines.append(f"  • {name} {param_str}")
    return "Known actions:\n" + "\n".join(lines)


@register({
    "name": "create_shortcut",
    "description": (
        "Generate a .shortcut plist file the user can tap once to install. "
        "Saves to $IAGENT_HOME/workspace/<name>.shortcut and returns the path. "
        "User must enable Settings → Shortcuts → 'Allow Untrusted Shortcuts' once. "
        "Then they tap the file in Files app to import. "
        "Only the actions returned by list_shortcut_actions are supported. "
        "For complex shortcuts, walk the user through creating in the app instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Shortcut display name",
            },
            "actions": {
                "type": "array",
                "description": (
                    "Ordered list of actions. Each item is "
                    "{action: <action_name>, params: {<param>: <value>}}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "params": {"type": "object"},
                    },
                    "required": ["action"],
                },
            },
        },
        "required": ["name", "actions"],
    },
})
async def create_shortcut(name: str, actions: list) -> str:
    actions_plist = []
    unknown = []
    for a in actions:
        action_name = a.get("action", "")
        params = a.get("params", {})
        built = _build_action(action_name, params)
        if built is None:
            unknown.append(action_name)
        else:
            actions_plist.append(built)

    if unknown:
        return (
            f"[create_shortcut] Unknown actions: {', '.join(unknown)}. "
            "Call list_shortcut_actions to see what's supported."
        )

    workflow = {
        "WFWorkflowActions": actions_plist,
        "WFWorkflowClientVersion": "2607.0.5",
        "WFWorkflowClientRelease": "2.2.2",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 4292311040,
            "WFWorkflowIconGlyphNumber": 59446,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowTypes": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowHasShortcutInputVariables": False,
    }

    _WORKSPACE.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    out_path = _WORKSPACE / f"{safe_name}.shortcut"
    with out_path.open("wb") as f:
        plistlib.dump(workflow, f, fmt=plistlib.FMT_BINARY)

    # Try to auto-launch the Shortcuts import dialog via uiopen.
    # This brings up the "Add Shortcut" preview where the user only needs
    # to tap once. Without uiopen we fall back to the manual Files-app path.
    uiopen = _which("uiopen")
    auto_launched = False
    if uiopen:
        import_url = f"shortcuts://import-shortcut?url=file://{out_path}"
        rc, _out = await _run([uiopen, import_url], timeout=5.0)
        auto_launched = (rc == 0)

    msg = f"Shortcut file generated: {out_path}\n\n"
    if auto_launched:
        msg += (
            "✓ Opened Shortcuts import dialog on the iPad. "
            "Tap 'Add Shortcut' (or 'Add Untrusted Shortcut') to install.\n\n"
            "If nothing happened: enable Settings → Shortcuts → "
            "'Allow Untrusted Shortcuts' (one-time), then ask me to do this again."
        )
    else:
        msg += (
            "To install:\n"
            "1. (one-time) Settings → Shortcuts → 'Allow Untrusted Shortcuts'\n"
            f"2. Open Files app → On My iPad → iagent → workspace → tap '{out_path.name}'\n"
            "Or in Terminal: "
            f"uiopen 'shortcuts://import-shortcut?url=file://{out_path}'"
        )
    return msg
