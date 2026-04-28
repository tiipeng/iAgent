from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Optional

from tools.registry import register

logger = logging.getLogger("iagent.tools.shell")

# Injected at startup from Settings
_timeout: int = 30
_allowlist: Optional[list[str]] = None

# On rootless Dopamine /bin/sh is a stub; prefer the Procursus shell.
_SHELL_CANDIDATES = ["/var/jb/bin/sh", "/bin/sh"]


def _find_shell() -> str:
    import os
    for s in _SHELL_CANDIDATES:
        if os.path.isfile(s):
            return s
    return "/bin/sh"


def configure(timeout: int = 30, allowlist: Optional[list[str]] = None) -> None:
    global _timeout, _allowlist
    _timeout = timeout
    _allowlist = allowlist


@register({
    "name": "shell",
    "description": (
        "Run a shell command on the device and return its stdout + stderr. "
        "Use for system info, file operations, or any local task. "
        "Commands are killed after the configured timeout."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            }
        },
        "required": ["command"],
    },
})
async def shell(command: str) -> str:
    if _allowlist is not None:
        cmd_name = shlex.split(command)[0] if command.strip() else ""
        if cmd_name not in _allowlist:
            return f"[Shell blocked: '{cmd_name}' is not in the allowlist]"

    sh = _find_shell()
    logger.debug("shell: %s", command)

    try:
        proc = await asyncio.create_subprocess_exec(
            sh, "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_timeout)
        output = stdout.decode(errors="replace").strip()
        exit_code = proc.returncode
        if exit_code != 0:
            return f"[exit {exit_code}]\n{output}"
        return output or "(no output)"
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"[Shell timeout after {_timeout}s]"
