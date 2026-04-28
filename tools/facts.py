"""Facts tools — let the agent remember things between conversations.

Backed by $IAGENT_HOME/facts.json. Unlike conversation history (which is
pruned), facts persist indefinitely until explicitly deleted.
"""
from __future__ import annotations

from agent.facts import get_store
from tools.registry import register


@register({
    "name": "remember_fact",
    "description": (
        "Store a named fact that will be remembered across all future conversations. "
        "Use this for things like: user preferences, recurring schedules, "
        "important notes, or anything that should survive a /clear. "
        "Overwrites the key if it already exists."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Short identifier for this fact (e.g. 'user_name', 'timezone')",
            },
            "value": {
                "type": "string",
                "description": "The value to remember",
            },
        },
        "required": ["key", "value"],
    },
})
async def remember_fact(key: str, value: str) -> str:
    key = key.strip().lower().replace(" ", "_")
    if not key:
        return "Key must not be empty."
    get_store().set(key, value)
    return f"Remembered: {key} = {value!r}"


@register({
    "name": "recall_fact",
    "description": (
        "Retrieve a previously stored fact by key. "
        "Returns the value, or a 'not found' message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Fact key to look up"},
        },
        "required": ["key"],
    },
})
async def recall_fact(key: str) -> str:
    key = key.strip().lower().replace(" ", "_")
    value = get_store().get(key)
    if value is None:
        return f"No fact stored for key '{key}'."
    return value


@register({
    "name": "list_facts",
    "description": "List all stored facts (keys and values).",
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def list_facts() -> str:
    facts = get_store().all()
    if not facts:
        return "No facts stored yet."
    lines = [f"• **{k}**: {v}" for k, v in sorted(facts.items())]
    return "\n".join(lines)


@register({
    "name": "forget_fact",
    "description": "Delete a stored fact by key.",
    "parameters": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Fact key to delete"},
        },
        "required": ["key"],
    },
})
async def forget_fact(key: str) -> str:
    key = key.strip().lower().replace(" ", "_")
    if get_store().delete(key):
        return f"Forgot: {key}"
    return f"No fact found for key '{key}'."
