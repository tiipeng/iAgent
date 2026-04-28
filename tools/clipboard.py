"""Clipboard tool — read from and write to the iOS system clipboard.

Uses pbcopy / pbpaste (available via Dopamine/Procursus or as apt packages).
Falls back to xclip / xsel on Linux. The user can install pbcopy/pbpaste
from Sileo if not present.
"""
from __future__ import annotations

import asyncio
import shutil

from tools.registry import register


def _pbcopy() -> str:
    for candidate in ("/var/jb/usr/bin/pbcopy", "pbcopy"):
        if shutil.which(candidate):
            return candidate
    return ""


def _pbpaste() -> str:
    for candidate in ("/var/jb/usr/bin/pbpaste", "pbpaste"):
        if shutil.which(candidate):
            return candidate
    return ""


@register({
    "name": "clipboard_read",
    "description": "Read the current text content of the iOS clipboard.",
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def clipboard_read() -> str:
    paste_bin = _pbpaste()
    if not paste_bin:
        return (
            "[Clipboard unavailable] pbpaste not found. "
            "Install via Sileo: sudo apt install pbcopy"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            paste_bin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            return f"[clipboard_read failed] {stderr.decode(errors='replace').strip()}"
        return stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        return "[clipboard_read timed out]"


@register({
    "name": "clipboard_write",
    "description": "Write text to the iOS clipboard so the user can paste it anywhere.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to copy to the clipboard"},
        },
        "required": ["text"],
    },
})
async def clipboard_write(text: str) -> str:
    copy_bin = _pbcopy()
    if not copy_bin:
        return (
            "[Clipboard unavailable] pbcopy not found. "
            "Install via Sileo: sudo apt install pbcopy"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            copy_bin,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(input=text.encode()), timeout=5.0
        )
        if proc.returncode != 0:
            return f"[clipboard_write failed] {stderr.decode(errors='replace').strip()}"
        preview = text[:60] + ("…" if len(text) > 60 else "")
        return f"Copied to clipboard: {preview!r}"
    except asyncio.TimeoutError:
        return "[clipboard_write timed out]"
