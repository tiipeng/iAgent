from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from tools.registry import register

logger = logging.getLogger("iagent.tools.http")

_session: Optional[aiohttp.ClientSession] = None
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_BYTES = 50_000  # truncate large responses to keep tokens reasonable


def set_session(session: aiohttp.ClientSession) -> None:
    global _session
    _session = session


def _get_session() -> aiohttp.ClientSession:
    if _session is None:
        raise RuntimeError("aiohttp session not initialised — call set_session() first")
    return _session


@register({
    "name": "http_get",
    "description": "Fetch a URL via HTTP GET and return the response body as text.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."},
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers as key-value pairs.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["url"],
    },
})
async def http_get(url: str, headers: Optional[dict] = None) -> str:
    session = _get_session()
    logger.debug("GET %s", url)
    try:
        async with session.get(url, headers=headers or {}, timeout=_TIMEOUT, ssl=None) as resp:
            body = await resp.content.read(_MAX_BYTES)
            text = body.decode(errors="replace")
            truncated = len(body) >= _MAX_BYTES
            result = f"HTTP {resp.status}\n{text}"
            if truncated:
                result += "\n[... truncated]"
            return result
    except aiohttp.ClientError as exc:
        return f"[HTTP error: {exc}]"


@register({
    "name": "http_post",
    "description": "Send an HTTP POST request with a JSON body and return the response.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to POST to."},
            "body": {"type": "object", "description": "JSON-serialisable request body."},
            "headers": {
                "type": "object",
                "description": "Optional HTTP headers.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["url", "body"],
    },
})
async def http_post(url: str, body: dict, headers: Optional[dict] = None) -> str:
    session = _get_session()
    logger.debug("POST %s", url)
    try:
        async with session.post(url, json=body, headers=headers or {}, timeout=_TIMEOUT, ssl=None) as resp:
            raw = await resp.content.read(_MAX_BYTES)
            text = raw.decode(errors="replace")
            return f"HTTP {resp.status}\n{text}"
    except aiohttp.ClientError as exc:
        return f"[HTTP error: {exc}]"
