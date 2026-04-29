"""Photo tools — read library, describe with vision, send to Telegram.

All Shortcut-based code paths were removed. What's here works
without iOS Shortcuts on rootless Dopamine:
  read_recent_photos  — direct read of /var/mobile/Media/DCIM/
  describe_photo      — GPT-4o vision (HTTP API)
  send_photo          — posts to active Telegram chat via bot API

For "take a new photo" (camera capture) the agent should use the
XXTouch screen tooling or ask the user to take one — there is no
non-Shortcut path to the camera and we don't pretend there is.
"""
from __future__ import annotations

import base64
import contextvars
import os
from pathlib import Path
from typing import Optional

import httpx

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))
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


@register({
    "name": "read_recent_photos",
    "description": (
        "Fetch the N most recent photos from the device's photo library "
        "by reading /var/mobile/Media/DCIM/ directly. "
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
    if not dcim:
        return "[read_recent_photos] /var/mobile/Media/DCIM not found"
    try:
        photos = [
            p for p in dcim.rglob("*")
            if p.is_file() and p.suffix.lower() in _PHOTO_EXTS
        ]
    except (PermissionError, OSError) as e:
        return f"[read_recent_photos] DCIM access blocked: {e}"
    photos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not photos:
        return "(DCIM is empty)"
    return "\n".join(str(p) for p in photos[:limit])


@register({
    "name": "send_photo",
    "description": (
        "Send a photo file to the user via Telegram so they can see it in the chat. "
        "Pass a local file path (e.g. one returned by read_recent_photos or screenshot_xx). "
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
        "Pass the local file path (e.g. from read_recent_photos or screenshot_xx). "
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
            "Resize to under 5 MB first."
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
