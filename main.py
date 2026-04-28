#!/usr/bin/env python3
"""iAgent — personal AI agent for jailbroken iOS, powered by OpenAI + Telegram."""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from openai import AsyncOpenAI
from telegram.ext import Application, ApplicationBuilder

from agent.heartbeat import Heartbeat
from agent.memory import Memory
from bot.handlers import register_handlers
from config.settings import load_settings
import tools.apt as apt_tool
import tools.file_io as file_io_tool
import tools.http_fetch as http_tool
import tools.photo as photo_tool
import tools.shell as shell_tool
from utils.logger import setup_logger

# Import tool modules so their @register decorators fire
import tools.shell  # noqa: F401
import tools.file_io  # noqa: F401
import tools.http_fetch  # noqa: F401
import tools.apt  # noqa: F401
import tools.skills  # noqa: F401
import tools.shortcuts  # noqa: F401
import tools.clipboard  # noqa: F401
import tools.notify  # noqa: F401
import tools.facts  # noqa: F401
import tools.photo  # noqa: F401
import tools.ios  # noqa: F401
import tools.self_debug  # noqa: F401


async def on_startup(app: Application) -> None:
    settings = app.bot_data["settings"]
    memory: Memory = app.bot_data["memory"]
    await memory.init()

    # Create a shared aiohttp session for the http tools
    session = aiohttp.ClientSession()
    app.bot_data["aiohttp_session"] = session
    http_tool.set_session(session)

    # Start heartbeat (no-op when interval == 0)
    from agent.heartbeat import DEFAULT_PROMPT as _DEFAULT_HB_PROMPT
    hb_prompt = settings.heartbeat_prompt or _DEFAULT_HB_PROMPT
    hb = Heartbeat(app, interval=settings.heartbeat_interval, prompt=hb_prompt)
    hb.start()
    app.bot_data["heartbeat"] = hb

    logger = logging.getLogger("iagent")
    logger.info("iAgent started. Bot: @%s", (await app.bot.get_me()).username)


async def on_shutdown(app: Application) -> None:
    hb: Heartbeat = app.bot_data.get("heartbeat")
    if hb:
        hb.stop()

    memory: Memory = app.bot_data["memory"]
    await memory.close()

    session: aiohttp.ClientSession = app.bot_data.get("aiohttp_session")
    if session:
        await session.close()

    logging.getLogger("iagent").info("iAgent shut down cleanly.")


def main() -> None:
    settings = load_settings()

    log_dir = settings.log_dir
    logger = setup_logger(log_dir)
    logger.info("Loading iAgent…")

    # Configure tool modules
    shell_tool.configure(
        timeout=settings.shell_timeout,
        allowlist=settings.shell_allowlist,
    )
    file_io_tool.configure(workspace_root=settings.workspace_root)
    apt_tool.configure(
        enabled=settings.apt_install_enabled,
        allowlist=settings.apt_install_allowlist,
    )
    photo_tool.configure(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )

    memory = Memory(settings.db_path)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    app: Application = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # Stash shared objects in bot_data so handlers can reach them
    app.bot_data["settings"] = settings
    app.bot_data["memory"] = memory
    app.bot_data["openai_client"] = openai_client

    register_handlers(app)

    logger.info("Starting polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
