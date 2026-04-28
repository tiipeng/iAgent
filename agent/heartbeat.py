"""Heartbeat — periodic self-prompts that keep iAgent proactive.

Disabled when heartbeat_interval == 0 (default). When enabled, every
`interval` seconds the agent sends itself a configurable prompt so it can
check on running tasks, send scheduled summaries, etc.

The heartbeat fires as a plain tool-calling loop on a synthetic chat_id
(-999) so it never pollutes real conversation history.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from openai import AsyncOpenAI
from telegram.ext import Application

logger = logging.getLogger("iagent.heartbeat")

HEARTBEAT_CHAT_ID = -999
DEFAULT_PROMPT = (
    "Heartbeat tick. Check if there is anything proactive you should do: "
    "e.g. remind the user of pending tasks, summarise recent activity, "
    "or run scheduled maintenance. If nothing is needed, reply with a single dot."
)


class Heartbeat:
    def __init__(
        self,
        app: Application,
        interval: int,
        prompt: str = DEFAULT_PROMPT,
    ) -> None:
        self._app = app
        self._interval = interval
        self._prompt = prompt
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def start(self) -> None:
        if self._interval <= 0:
            logger.info("Heartbeat disabled (interval=0)")
            return
        self._task = asyncio.create_task(self._loop(), name="heartbeat")
        logger.info("Heartbeat started — interval=%ds", self._interval)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        await asyncio.sleep(self._interval)  # first tick delayed by one interval
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Heartbeat tick failed")
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        from agent.context import ChatContext
        from agent.memory import Memory
        import agent.loop as loop_module
        from config.settings import Settings

        bot_data = self._app.bot_data
        settings: Settings = bot_data["settings"]
        memory: Memory = bot_data["memory"]
        client: AsyncOpenAI = bot_data["openai_client"]

        ctx = ChatContext(
            chat_id=HEARTBEAT_CHAT_ID,
            history_window=10,
            max_iterations=settings.max_iterations,
        )

        logger.debug("Heartbeat tick firing")
        reply = await loop_module.run(
            client=client,
            model=settings.openai_model,
            context=ctx,
            memory=memory,
            user_message=self._prompt,
        )

        # Only forward to the first allowed user if there is something real to say
        reply = reply.strip()
        if reply and reply != ".":
            for uid in settings.allowed_user_ids:
                try:
                    await self._app.bot.send_message(chat_id=uid, text=f"🕐 {reply}")
                except Exception:
                    logger.exception("Heartbeat: failed to send message to %d", uid)
