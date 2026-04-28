#!/usr/bin/env python3
"""iAgent single-shot tick.

Designed to be invoked periodically by launchd (StartInterval). Pulls
pending Telegram updates with long-poll, processes each, persists the
offset, and exits. Memory is released between ticks so iOS Jetsam never
sees a long-running daemon to kill.

This replaces main.py's infinite run_polling loop in the daemon path.
main.py is still the right entry point for foreground debugging.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from openai import AsyncOpenAI
from telegram import Bot

from agent.context import ChatContext
from agent.memory import Memory
import agent.loop as loop_module
from config.settings import load_settings
import tools.apt as apt_tool
import tools.file_io as file_io_tool
import tools.http_fetch as http_tool
import tools.shell as shell_tool

# Force tool registration via @register decorators
import tools.shell  # noqa: F401
import tools.file_io  # noqa: F401
import tools.http_fetch  # noqa: F401
import tools.apt  # noqa: F401

from utils.logger import setup_logger

IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))
OFFSET_FILE = IAGENT_HOME / "telegram.offset"
LOCK_FILE = IAGENT_HOME / "tick.lock"

# How long the tick will wait for new updates before exiting (seconds).
# Telegram long-poll: bot returns immediately when a message arrives,
# or after this timeout if nothing comes in. Pair this with the plist
# StartInterval — e.g. timeout=25 + StartInterval=30 → near-zero latency
# while still releasing memory every cycle.
LONG_POLL_TIMEOUT = 25


def _read_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _write_offset(offset: int) -> None:
    OFFSET_FILE.write_text(str(offset))


def _claim_lock(logger: logging.Logger) -> bool:
    """Return True if we acquired the lock; False if another tick is alive."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text())
            os.kill(pid, 0)  # raises if not running
            logger.info("previous tick still running (pid=%d), skipping", pid)
            return False
        except (ProcessLookupError, ValueError, OSError):
            logger.warning("stale tick.lock found, taking over")
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def _split(text: str, n: int = 4096) -> list:
    if len(text) <= n:
        return [text]
    return [text[i:i + n] for i in range(0, len(text), n)]


async def _handle_message(
    bot: Bot,
    update: dict,
    settings,
    memory: Memory,
    openai_client: AsyncOpenAI,
    logger: logging.Logger,
) -> None:
    """Process a single Telegram update — text messages only."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    user_id = (msg.get("from") or {}).get("id")
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if not text or chat_id is None:
        return

    # Allowlist gate (silent drop, just like the main bot)
    if settings.allowed_user_ids and user_id not in settings.allowed_user_ids:
        logger.warning("blocked message from user %s", user_id)
        return

    # Built-in commands
    if text == "/start":
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "👾 iAgent online (interval mode).\n"
                "Send a message and I'll reply within ~30 s.\n"
                "Commands: /clear  reset history."
            ),
        )
        return
    if text == "/clear":
        await memory.clear(chat_id)
        await bot.send_message(chat_id=chat_id, text="Conversation history cleared.")
        return

    # Show typing while we work
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    ctx = ChatContext(
        chat_id=chat_id,
        history_window=settings.history_window,
        max_iterations=settings.max_iterations,
    )
    try:
        reply = await loop_module.run(
            client=openai_client,
            model=settings.openai_model,
            context=ctx,
            memory=memory,
            user_message=text,
        )
    except Exception as exc:
        logger.exception("agent error for chat %s", chat_id)
        reply = f"Sorry, something went wrong: {exc}"

    for chunk in _split(reply):
        try:
            await bot.send_message(chat_id=chat_id, text=chunk)
        except Exception:
            logger.exception("send failed for chat %s", chat_id)


async def main() -> int:
    settings = load_settings()
    logger = setup_logger(settings.log_dir)
    logger.info("tick start (pid=%d)", os.getpid())

    if not _claim_lock(logger):
        return 0

    session = None
    memory = None
    try:
        # Tool config
        shell_tool.configure(
            timeout=settings.shell_timeout, allowlist=settings.shell_allowlist
        )
        file_io_tool.configure(workspace_root=settings.workspace_root)
        apt_tool.configure(
            enabled=settings.apt_install_enabled,
            allowlist=settings.apt_install_allowlist,
        )

        # Memory + HTTP session
        memory = Memory(settings.db_path)
        await memory.init()
        session = aiohttp.ClientSession()
        http_tool.set_session(session)
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

        # Pull any pending updates and process them
        bot = Bot(token=settings.telegram_token)
        async with bot:
            offset = _read_offset()
            logger.info("getUpdates offset=%d timeout=%ds", offset, LONG_POLL_TIMEOUT)
            try:
                updates = await bot.get_updates(
                    offset=offset,
                    timeout=LONG_POLL_TIMEOUT,
                    allowed_updates=["message", "edited_message"],
                )
            except Exception as exc:
                logger.exception("getUpdates failed: %s", exc)
                updates = []

            if not updates:
                logger.info("no updates")
            else:
                logger.info("processing %d update(s)", len(updates))
                for upd in updates:
                    try:
                        await _handle_message(
                            bot, upd.to_dict(), settings, memory, openai_client, logger
                        )
                    except Exception:
                        logger.exception("update handler crashed for %s", upd.update_id)
                    _write_offset(upd.update_id + 1)

        return 0
    finally:
        if session is not None:
            await session.close()
        if memory is not None:
            await memory.close()
        _release_lock()
        logger.info("tick done")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
