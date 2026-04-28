"""Photo / Camera tools — take photos, fetch recent photos, describe with vision.

Three access paths, in preference order:
  1. Direct filesystem — /var/mobile/Media/DCIM/ — works without Shortcuts
  2. iOS Shortcuts CLI — for camera capture and Photos library API access
  3. None — graceful degradation with a setup hint

`send_photo` posts a file directly to the active Telegram chat using the
bot's existing token, so the user can SEE the image in the chat.
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))
_SHORTCUTS_BIN = "/var/jb/usr/bin/shortcuts"
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB — GPT-4o limit before quality degrades

# DCIM lives under user mobile's media root (rootless) — direct read access.
_DCIM_DIRS = [
    Path("/var/mobile/Media/DCIM"),
    Path("/var/jb/var/mobile/Media/DCIM"),
    Path("/private/var/mobile/Media/DCIM"),
]
_PHOTO_EXTS = {".jpg", ".jpeg", ".heic", ".png", ".gif", ".webp"}

_openai_api_key: str = ""
_openai_model: str = "gpt-4o"
_telegram_token: str = ""

# Chat id of the message currently being handled — set by bot/handlers.py
# before each agent-loop run so send_photo knows where to post.
current_chat_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "iagent_current_chat_id", default=None
)


def configure(api_key: str, model: str = "gpt-4o", telegram_token: str = "") -> None:
    global _openai_api_key, _openai_model, _telegram_token
    _openai_api_key = api_key
    _openai_model = model
    _telegram_token = telegram_token


def _find_dcim() -> Optional[Path]:
    for p in _DCIM_DIRS:
        if p.exists():
            return p
    return None


def _shortcuts_bin() -> str:
    if shutil.which(_SHORTCUTS_BIN):
        return _SHORTCUTS_BIN
    if shutil.which("shortcuts"):
        return "shortcuts"
    return ""


async def _run_shortcut(name: str, input_text: str = "") -> tuple[int, str, str]:
    """Run a shortcut, return (returncode, stdout, stderr)."""
    bin_path = _shortcuts_bin()
    if not bin_path:
        return -1, "", "shortcuts CLI not found — install via Sileo: shortcuts-cli"

    cmd = [bin_path, "run", name]
    tmp_path: Optional[str] = None

    if input_text:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(input_text)
            tmp_path = f.name
        cmd += ["--input-path", tmp_path]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )
    except asyncio.TimeoutError:
        return -1, "", f"Shortcut '{name}' timed out after 60s"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@register({
    "name": "take_photo",
    "description": (
        "Take a photo with the iPad camera via iOS Shortcuts. "
        "Returns the path of the saved image in the workspace. "
        "Requires a Shortcut named 'iAgent Take Photo': "
        "Take Photo → Save to File ($IAGENT_HOME/workspace/photo.jpg) → return path."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def take_photo() -> str:
    rc, out, err = await _run_shortcut("iAgent Take Photo")
    if rc != 0:
        return f"[take_photo failed] {err or out}\nMake sure the Shortcut 'iAgent Take Photo' exists."
    path = out or str(_IAGENT_HOME / "workspace" / "photo.jpg")
    return f"Photo saved to: {path}"


@register({
    "name": "read_recent_photos",
    "description": (
        "Fetch the N most recent photos from the device's photo library. "
        "First tries direct filesystem access at /var/mobile/Media/DCIM/ "
        "(works without Shortcuts on jailbroken iOS). Falls back to the "
        "'iAgent Recent Photos' Shortcut if DCIM is empty or unreadable. "
        "Returns newline-separated absolute file paths sorted newest first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent photos to fetch (default 5, max 20)",
            },
        },
        "required": [],
    },
})
async def read_recent_photos(limit: int = 5) -> str:
    limit = max(1, min(limit, 20))

    dcim = _find_dcim()
    if dcim:
        try:
            photos = []
            for p in dcim.rglob("*"):
                if p.is_file() and p.suffix.lower() in _PHOTO_EXTS:
                    photos.append(p)
            photos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            top = photos[:limit]
            if top:
                return "\n".join(str(p) for p in top)
        except (PermissionError, OSError) as e:
            return f"[read_recent_photos] DCIM access blocked: {e}"

    rc, out, err = await _run_shortcut("iAgent Recent Photos", str(limit))
    if rc != 0:
        return (
            f"[read_recent_photos] No DCIM access and Shortcut failed: {err or out}\n"
            "Check that /var/mobile/Media/DCIM/ exists or create the "
            "'iAgent Recent Photos' Shortcut."
        )
    return out or "No photos found."


@register({
    "name": "send_photo",
    "description": (
        "Send a photo file to the user via Telegram so they can see it in the chat. "
        "Pass a local file path (e.g. one returned by read_recent_photos or take_photo). "
        "Optional caption shows below the image."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to a JPEG/PNG/HEIC/WebP file",
            },
            "caption": {
                "type": "string",
                "description": "Optional caption text",
            },
        },
        "required": ["path"],
    },
})
async def send_photo(path: str, caption: str = "") -> str:
    if not _telegram_token:
        return "[send_photo] Telegram token not configured"
    chat_id = current_chat_id.get()
    if not chat_id:
        return "[send_photo] No active chat context (this tool only works during a Telegram message handler)"

    img = Path(path)
    if not img.exists():
        return f"[send_photo] File not found: {path}"
    if img.stat().st_size > 50 * 1024 * 1024:
        return f"[send_photo] File too large ({img.stat().st_size // 1024 // 1024} MB); Telegram limit is 50 MB"

    url = f"https://api.telegram.org/bot{_telegram_token}/sendPhoto"
    try:
        with img.open("rb") as f:
            files = {"photo": (img.name, f, "application/octet-stream")}
            data = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption[:1024]
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, data=data, files=files)
        if resp.status_code != 200:
            return f"[send_photo] Telegram error {resp.status_code}: {resp.text[:200]}"
        return f"Photo sent: {img.name}"
    except Exception as exc:
        return f"[send_photo] {exc}"


@register({
    "name": "describe_photo",
    "description": (
        "Send an image file to GPT-4o vision and get a description. "
        "Pass the local file path (e.g. from take_photo or read_recent_photos). "
        "Returns the model's textual description of the image."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to a JPEG, PNG, GIF, or WebP image file",
            },
            "question": {
                "type": "string",
                "description": "Optional specific question to ask about the image",
            },
        },
        "required": ["path"],
    },
})
async def describe_photo(path: str, question: str = "") -> str:
    if not _openai_api_key:
        return "[describe_photo] OpenAI API key not configured in tools.photo"

    img_path = Path(path)
    if not img_path.exists():
        return f"[describe_photo] File not found: {path}"

    data = img_path.read_bytes()
    if len(data) > _MAX_IMAGE_BYTES:
        return (
            f"[describe_photo] Image too large ({len(data) // 1024} KB). "
            "Resize to under 5 MB first, e.g.: sips -Z 1024 <file>"
        )

    suffix = img_path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(suffix, "image/jpeg")
    b64 = base64.b64encode(data).decode()

    prompt = question or "Describe this image in detail."

    payload = {
        "model": _openai_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {_openai_api_key}"},
            )
        if resp.status_code != 200:
            return f"[describe_photo] API error {resp.status_code}: {resp.text[:400]}"
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"[describe_photo] {exc}"
