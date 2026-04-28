from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger("iagent.tools")

# Each entry: {"type": "function", "function": {name, description, parameters}}
_schemas: list[dict] = []
_handlers: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {}


def register(schema: dict):
    """Decorator that registers an async tool handler alongside its OpenAI schema."""
    def decorator(fn: Callable[..., Coroutine[Any, Any, str]]):
        _schemas.append({"type": "function", "function": schema})
        _handlers[schema["name"]] = fn
        return fn
    return decorator


def get_schemas() -> list[dict]:
    return list(_schemas)


async def dispatch(name: str, arguments: dict | str) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return f"[Tool error: could not parse arguments JSON for {name}]"

    handler = _handlers.get(name)
    if handler is None:
        return f"[Tool error: unknown tool '{name}']"

    try:
        result = await handler(**arguments)
        return str(result)
    except Exception as exc:
        logger.exception("Tool '%s' raised an error", name)
        return f"[Tool error: {exc}]"
