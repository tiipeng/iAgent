from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import aiofiles

from tools.registry import register

logger = logging.getLogger("iagent.tools.file_io")

_workspace_root: Path = Path.home() / ".iagent" / "workspace"


def configure(workspace_root: Path) -> None:
    global _workspace_root
    _workspace_root = Path(workspace_root)


def _safe_path(relative_or_absolute: str) -> Optional[Path]:
    """Resolve path and ensure it stays within workspace_root."""
    p = Path(relative_or_absolute)
    if not p.is_absolute():
        p = _workspace_root / p
    try:
        resolved = p.resolve()
        workspace_resolved = _workspace_root.resolve()
        resolved.relative_to(workspace_resolved)  # raises ValueError if outside
        return resolved
    except ValueError:
        return None


@register({
    "name": "read_file",
    "description": "Read a text file from the workspace and return its contents.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path inside the workspace, or absolute path within the workspace root.",
            }
        },
        "required": ["path"],
    },
})
async def read_file(path: str) -> str:
    safe = _safe_path(path)
    if safe is None:
        return f"[Error: path '{path}' is outside the workspace]"
    if not safe.exists():
        return f"[Error: file not found: {path}]"
    async with aiofiles.open(safe, encoding="utf-8", errors="replace") as f:
        return await f.read()


@register({
    "name": "write_file",
    "description": "Write text content to a file in the workspace. Creates the file if it does not exist.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path inside the workspace.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write.",
            },
        },
        "required": ["path", "content"],
    },
})
async def write_file(path: str, content: str) -> str:
    safe = _safe_path(path)
    if safe is None:
        return f"[Error: path '{path}' is outside the workspace]"
    safe.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(safe, "w", encoding="utf-8") as f:
        await f.write(content)
    return f"Written {len(content)} chars to {safe.relative_to(_workspace_root)}"


@register({
    "name": "list_files",
    "description": "List files and directories inside a workspace path.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to list. Defaults to workspace root if omitted.",
                "default": ".",
            }
        },
        "required": [],
    },
})
async def list_files(path: str = ".") -> str:
    safe = _safe_path(path)
    if safe is None:
        return f"[Error: path '{path}' is outside the workspace]"
    if not safe.is_dir():
        return f"[Error: not a directory: {path}]"
    entries = sorted(os.listdir(safe))
    if not entries:
        return "(empty directory)"
    lines = []
    for entry in entries:
        full = safe / entry
        lines.append(f"{'d' if full.is_dir() else 'f'}  {entry}")
    return "\n".join(lines)
