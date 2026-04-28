from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger("iagent.memory")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    role        TEXT    NOT NULL,
    content     TEXT,
    tool_calls  TEXT,
    tool_call_id TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""
_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id)"


class Memory:
    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
        await self._db.commit()
        logger.info("Memory DB initialised at %s", self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def append(
        self,
        chat_id: int,
        role: str,
        content: Optional[str] = None,
        tool_calls: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> None:
        await self._db.execute(
            "INSERT INTO messages (chat_id, role, content, tool_calls, tool_call_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, role, content, tool_calls, tool_call_id),
        )
        await self._db.commit()

    async def get_history(self, chat_id: int, limit: int = 20) -> list[dict]:
        async with self._db.execute(
            "SELECT role, content, tool_calls, tool_call_id FROM messages "
            "WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        # reverse so oldest-first for the OpenAI messages array
        rows.reverse()
        messages: list[dict] = []
        for role, content, tool_calls_json, tool_call_id in rows:
            msg: dict = {"role": role}
            if content is not None:
                msg["content"] = content
            if tool_calls_json:
                import json
                msg["tool_calls"] = json.loads(tool_calls_json)
            if tool_call_id:
                msg["tool_call_id"] = tool_call_id
            messages.append(msg)
        return messages

    async def prune(self, chat_id: int, keep: int = 20) -> None:
        await self._db.execute(
            "DELETE FROM messages WHERE chat_id = ? AND id NOT IN ("
            "  SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?"
            ")",
            (chat_id, chat_id, keep),
        )
        await self._db.commit()

    async def clear(self, chat_id: int) -> None:
        await self._db.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        await self._db.commit()
        logger.info("Cleared history for chat %d", chat_id)
