"""Push notification tool — send a local iOS notification from the agent.

Strategy (in order of preference):
1. `shortcuts run` with a "Show Notification" Shortcut named "iAgent Notify"
   — requires the user to create this Shortcut once in the Shortcuts app.
2. `alertsound` / `ntfy` CLI if available.
3. Graceful degradation: returns instructions.

The user only needs to create one Shortcut:
  Name: iAgent Notify
  Action: Receive Input from Shortcut → Show Notification (body = Shortcut Input)
"""
from __future__ import annotations

import asyncio
import shutil

from tools.registry import register

_SHORTCUT_NAME = "iAgent Notify"
_SHORTCUTS_BIN = "/var/jb/usr/bin/shortcuts"


def _shortcuts_bin() -> str:
    if shutil.which(_SHORTCUTS_BIN):
        return _SHORTCUTS_BIN
    if shutil.which("shortcuts"):
        return "shortcuts"
    return ""


@register({
    "name": "send_notification",
    "description": (
        "Send a push notification to this iOS device. "
        "Requires a Shortcut named 'iAgent Notify' that accepts text input "
        "and shows it as a notification. Create it once in the Shortcuts app: "
        "Receive Input → Show Notification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Notification title (short)",
            },
            "body": {
                "type": "string",
                "description": "Notification body text",
            },
        },
        "required": ["title", "body"],
    },
})
async def send_notification(title: str, body: str) -> str:
    bin_path = _shortcuts_bin()
    if not bin_path:
        return (
            "[Notifications unavailable] The `shortcuts` CLI is not installed. "
            "Install via Sileo: shortcuts-cli"
        )

    import tempfile, os
    payload = f"{title}\n{body}"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(payload)
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            bin_path, "run", _SHORTCUT_NAME, "--input-path", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            return (
                f"[Notification failed (exit {proc.returncode})] {err}\n"
                f"Make sure a Shortcut named '{_SHORTCUT_NAME}' exists."
            )
        return f"Notification sent: {title!r}"
    except asyncio.TimeoutError:
        return "[send_notification timed out]"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
