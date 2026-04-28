#!/usr/bin/env python3
"""Local CLI chat for iAgent — same agent loop and tools, no Telegram."""
from __future__ import annotations

import asyncio
import logging
import sys

import aiohttp
from openai import AsyncOpenAI

from agent.context import ChatContext
from agent.memory import Memory
import agent.loop as loop_module
from config.settings import load_settings
import tools.apt as apt_tool
import tools.file_io as file_io_tool
import tools.http_fetch as http_tool
import tools.photo as photo_tool
import tools.shell as shell_tool

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

# A dedicated chat id so CLI conversations don't pollute Telegram history.
CLI_CHAT_ID = -1


_CLI_HELP = """\
  /help      show this message
  /clear     reset conversation history
  /skills    list available skills
  /facts     list remembered facts
  /tools     list all registered agent tools
  /model     show current model
  /status    show session info
  /quit      exit"""


def _print_banner(model: str) -> None:
    print("\033[1;36m" + "─" * 60 + "\033[0m")
    print(f" iAgent CLI — model: \033[1m{model}\033[0m")
    print(" Type /help for commands")
    print("\033[1;36m" + "─" * 60 + "\033[0m")


async def main() -> None:
    # Quieter logging for the REPL; surface errors only
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(name)s: %(message)s")

    settings = load_settings()
    shell_tool.configure(timeout=settings.shell_timeout, allowlist=settings.shell_allowlist)
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
    await memory.init()

    session = aiohttp.ClientSession()
    http_tool.set_session(session)

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    context = ChatContext(
        chat_id=CLI_CHAT_ID,
        history_window=settings.history_window,
        max_iterations=settings.max_iterations,
    )

    _print_banner(settings.openai_model)

    try:
        loop = asyncio.get_event_loop()
        while True:
            try:
                # Run blocking input() in a thread so we don't block the loop.
                line = await loop.run_in_executor(None, lambda: input("\033[1;32myou>\033[0m "))
            except (EOFError, KeyboardInterrupt):
                print()
                break

            line = line.strip()
            if not line:
                continue

            if line in ("/quit", "/exit", ":q"):
                break
            if line in ("/help", "/?"):
                print(_CLI_HELP)
                continue
            if line == "/clear":
                await memory.clear(CLI_CHAT_ID)
                print("\033[2m(history cleared)\033[0m")
                continue
            if line == "/skills":
                from tools.skills import list_skills
                print(await list_skills())
                continue
            if line == "/facts":
                from tools.facts import list_facts
                print(await list_facts())
                continue
            if line == "/tools":
                import tools.registry as registry
                names = [s["function"]["name"] for s in registry.get_schemas()]
                print("\n".join(f"  • {n}" for n in sorted(names)))
                continue
            if line == "/model":
                print(f"  {settings.openai_model}")
                continue
            if line == "/status":
                history = await memory.get_history(CLI_CHAT_ID, limit=500)
                print(
                    f"  model:   {settings.openai_model}\n"
                    f"  history: {len(history)} messages (window={settings.history_window})\n"
                    f"  db:      {settings.db_path}"
                )
                continue

            try:
                reply = await loop_module.run(
                    client=openai_client,
                    model=settings.openai_model,
                    context=context,
                    memory=memory,
                    user_message=line,
                )
            except KeyboardInterrupt:
                print("\n\033[2m(interrupted)\033[0m")
                continue
            except Exception as exc:
                print(f"\033[1;31merror:\033[0m {exc}")
                continue

            print(f"\033[1;35magent>\033[0m {reply}\n")
    finally:
        await session.close()
        await memory.close()
        print("bye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
