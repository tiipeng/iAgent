"""apt_install / apt_search tools — let the agent install Sileo packages.

v1: allowlist-only. Install only succeeds if the package name is in
    config.apt_install_allowlist AND config.apt_install_enabled is true.
    No interactive approval prompt yet (see ROADMAP Phase 1.3 risks).
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

import capabilities
from tools.registry import register

logger = logging.getLogger("iagent.tools.apt")

_PKG_RE = re.compile(r"^[a-z0-9.+-]+$")
_MIN_FREE_MB = 500

# Configured by main.py / chat.py at startup
_enabled: bool = False
_allowlist: list[str] = []


def configure(enabled: bool, allowlist: Optional[list[str]] = None) -> None:
    global _enabled, _allowlist
    _enabled = enabled
    _allowlist = list(allowlist or [])


def _apt_path() -> Optional[str]:
    p = Path("/var/jb/usr/bin/apt")
    if p.exists():
        return str(p)
    return shutil.which("apt") or shutil.which("apt-get")


def _free_disk_mb() -> int:
    try:
        st = shutil.disk_usage("/var/jb")
        return st.free // (1024 * 1024)
    except Exception:
        return 0


@register({
    "name": "apt_install",
    "description": (
        "Install a Sileo/Procursus package via apt-get. v1 only allows packages "
        "configured in apt_install_allowlist; anything else is refused. Returns "
        "the install output or a 'refused' message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "package": {
                "type": "string",
                "description": "Package name, e.g. 'pbcopy', 'ca-certificates', 'shortcuts'.",
            },
            "reason": {
                "type": "string",
                "description": "Why the agent wants this package (logged + shown to user).",
            },
        },
        "required": ["package", "reason"],
    },
})
async def apt_install(package: str, reason: str) -> str:
    if not _enabled:
        return (
            "[refused: apt_install is disabled in config.json. "
            "Set apt_install_enabled=true to allow installs.]"
        )
    if not _PKG_RE.match(package):
        return f"[refused: '{package}' is not a valid package name]"
    if package not in _allowlist:
        return (
            f"[refused: '{package}' is not in apt_install_allowlist. "
            f"Add it to config.json and re-load the daemon to permit this install. "
            f"Reason given: {reason}]"
        )
    free = _free_disk_mb()
    if free < _MIN_FREE_MB:
        return f"[refused: only {free} MB free, need at least {_MIN_FREE_MB} MB]"

    apt = _apt_path()
    if not apt:
        return "[error: apt not found at /var/jb/usr/bin/apt]"

    logger.info("apt install %s — reason: %s", package, reason)
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",  # non-interactive — relies on sudoers rule, never asks for password
            apt,
            "install",
            "-y",
            "--no-install-recommends",
            "--allow-unauthenticated",
            "-o", "Acquire::AllowInsecureRepositories=true",
            "-o", "Acquire::AllowDowngradeToInsecureRepositories=true",
            package,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = stdout.decode(errors="replace").strip()

        if proc.returncode == 0:
            capabilities.invalidate()  # registry now stale
            return f"[installed {package}]\n{output[-2000:]}"

        # Try to identify the specific failure mode from the output so the
        # agent stops blaming sudo when apt is the actual problem.
        lower = output.lower()
        hint = ""
        if "password is required" in lower or "sudo:" in lower and "password" in lower:
            hint = (
                "Hint: passwordless sudoers rule missing. Run on the device:\n"
                "  echo 'mobile ALL=NOPASSWD: /var/jb/usr/bin/apt' "
                "| sudo tee /var/jb/etc/sudoers.d/iagent && sudo chmod 440 /var/jb/etc/sudoers.d/iagent\n"
                "Or run: iagent activate"
            )
        elif "unable to locate package" in lower or "has no installation candidate" in lower:
            hint = (
                f"Hint: '{package}' isn't in your configured Sileo repos. "
                "Check apt search, or add the right repo."
            )
        elif "could not get lock" in lower or "another process" in lower:
            hint = "Hint: apt is locked by another process. Wait or kill the holder."
        else:
            hint = "Run 'iagent activate' to verify the environment."
        return f"[exit {proc.returncode}] {package} install failed.\n{output[-2000:]}\n\n{hint}"
    except asyncio.TimeoutError:
        return "[error: apt install timed out after 120s]"


@register({
    "name": "apt_search",
    "description": "Search the Sileo/Procursus repo for available packages.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term, e.g. 'shortcuts' or 'libsbnotify'.",
            },
        },
        "required": ["query"],
    },
})
async def apt_search(query: str) -> str:
    if not _PKG_RE.match(query):
        return f"[refused: '{query}' is not a valid search term]"

    apt = _apt_path()
    if not apt:
        return "[error: apt not found]"
    try:
        proc = await asyncio.create_subprocess_exec(
            apt, "search", query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        return stdout.decode(errors="replace")[:4000] or "(no results)"
    except asyncio.TimeoutError:
        return "[error: apt search timed out]"
