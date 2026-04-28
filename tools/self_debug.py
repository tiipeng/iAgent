"""Self-debugging tools — let iAgent read its own logs, inspect its source,
propose patches, and restart itself.

Phase 4.3. Safety rules:
  - patch_own_source requires confirm=True; without it only shows the diff.
  - patch_own_source always writes a .bak before modifying.
  - restart_self sends the Telegram reply first, then restarts after 3 s.
  - All file access is restricted to $IAGENT_HOME/code/ and $IAGENT_HOME/logs/.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import shutil
from pathlib import Path
from typing import Optional

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))
_CODE_DIR = _IAGENT_HOME / "code"
_LOG_DIR = _IAGENT_HOME / "logs"
_IAGENT_CMD = str(_IAGENT_HOME / "iagent")


def _safe_path(rel: str, base: Path) -> Optional[Path]:
    """Resolve rel inside base; return None if it escapes."""
    try:
        p = (base / rel).resolve()
        p.relative_to(base.resolve())
        return p
    except (ValueError, OSError):
        return None


# ── Logs ─────────────────────────────────────────────────────────────────

@register({
    "name": "read_own_logs",
    "description": (
        "Read the last N lines of iAgent's log files to diagnose errors. "
        "Returns combined output from iagent.log and stderr.log."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lines": {
                "type": "integer",
                "description": "Number of lines to return (default 50, max 200)",
            },
        },
        "required": [],
    },
})
async def read_own_logs(lines: int = 50) -> str:
    lines = max(1, min(lines, 200))
    results = []
    for name in ("iagent.log", "stderr.log"):
        p = _LOG_DIR / name
        if p.exists():
            text = p.read_text(errors="replace")
            tail = "\n".join(text.splitlines()[-lines:])
            results.append(f"=== {name} (last {lines} lines) ===\n{tail}")
    if not results:
        return "No log files found yet."
    return "\n\n".join(results)


# ── Source inspection ─────────────────────────────────────────────────────

@register({
    "name": "list_own_files",
    "description": (
        "List all Python source files in iAgent's code directory. "
        "Use this before read_own_source to find the right file."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def list_own_files() -> str:
    if not _CODE_DIR.exists():
        return f"Code directory not found: {_CODE_DIR}"
    files = sorted(_CODE_DIR.rglob("*.py"))
    if not files:
        return "No Python files found."
    lines = [str(p.relative_to(_CODE_DIR)) for p in files]
    return "\n".join(lines)


@register({
    "name": "read_own_source",
    "description": (
        "Read a source file from iAgent's code directory. "
        "Pass a relative path like 'tools/shell.py' or 'agent/loop.py'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Relative path within the code directory",
            },
        },
        "required": ["file"],
    },
})
async def read_own_source(file: str) -> str:
    path = _safe_path(file, _CODE_DIR)
    if path is None:
        return f"[read_own_source] Path '{file}' is outside the code directory."
    if not path.exists():
        return f"[read_own_source] File not found: {file}"
    return path.read_text(errors="replace")


# ── Patching ──────────────────────────────────────────────────────────────

@register({
    "name": "patch_own_source",
    "description": (
        "Replace an exact string in one of iAgent's source files. "
        "When confirm=false (default), only shows the proposed diff — nothing is changed. "
        "Set confirm=true ONLY after the user has explicitly approved the patch. "
        "A .bak backup is written before any change. "
        "After patching, call restart_self to load the new code."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Relative path within the code directory (e.g. 'tools/shell.py')",
            },
            "old_text": {
                "type": "string",
                "description": "Exact string to replace (must appear exactly once in the file)",
            },
            "new_text": {
                "type": "string",
                "description": "Replacement string",
            },
            "confirm": {
                "type": "boolean",
                "description": "Set true only when the user has approved the patch",
            },
        },
        "required": ["file", "old_text", "new_text"],
    },
})
async def patch_own_source(
    file: str,
    old_text: str,
    new_text: str,
    confirm: bool = False,
) -> str:
    path = _safe_path(file, _CODE_DIR)
    if path is None:
        return f"[patch_own_source] Path '{file}' is outside the code directory."
    if not path.exists():
        return f"[patch_own_source] File not found: {file}"

    original = path.read_text(errors="replace")
    count = original.count(old_text)
    if count == 0:
        return f"[patch_own_source] old_text not found in {file}."
    if count > 1:
        return (
            f"[patch_own_source] old_text appears {count} times in {file} — "
            "make it more specific so it matches exactly once."
        )

    patched = original.replace(old_text, new_text, 1)

    # Always show the diff
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=f"a/{file}",
        tofile=f"b/{file}",
        n=3,
    ))
    diff_text = "".join(diff_lines) or "(no visible diff)"

    if not confirm:
        return (
            f"Proposed patch for {file} (NOT applied yet):\n\n"
            f"```diff\n{diff_text}\n```\n\n"
            "Reply 'yes, apply the patch' to confirm, then I will call "
            "patch_own_source again with confirm=true."
        )

    # Write backup then apply
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    path.write_text(patched)
    return (
        f"Patch applied to {file}. Backup saved at {bak.name}.\n"
        "Call restart_self to load the updated code."
    )


# ── Restart ───────────────────────────────────────────────────────────────

@register({
    "name": "restart_self",
    "description": (
        "Restart the iAgent bot process. "
        "The current reply is sent first; the restart fires 3 seconds later. "
        "The bot will be offline for a few seconds while tmux restarts it."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def restart_self() -> str:
    iagent = _IAGENT_CMD
    if not Path(iagent).exists():
        iagent = shutil.which("iagent") or "iagent"

    async def _delayed_restart() -> None:
        await asyncio.sleep(3)
        proc = await asyncio.create_subprocess_exec(
            iagent, "restart",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    asyncio.create_task(_delayed_restart())
    return "Restarting iAgent in 3 seconds… I'll be back shortly."
