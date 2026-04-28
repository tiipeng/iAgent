from __future__ import annotations

import logging
import platform
from datetime import datetime

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agent.context import ChatContext
from agent.memory import Memory
import agent.loop as loop_module
from bot.middleware import is_allowed
from config.settings import Settings
from openai import AsyncOpenAI

logger = logging.getLogger("iagent.bot")

BOT_COMMANDS = [
    BotCommand("start",   "Wake up the bot"),
    BotCommand("help",    "List all commands"),
    BotCommand("clear",   "Reset conversation history"),
    BotCommand("status",  "Show uptime, model, memory stats"),
    BotCommand("skills",  "List available skills"),
    BotCommand("facts",   "List remembered facts"),
    BotCommand("model",   "Show or switch the AI model"),
    BotCommand("memory",  "Show how many messages are in history"),
]


def _app_data(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data


def _guard(fn):
    """Decorator: silently drop messages from non-allowed users."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        settings: Settings = _app_data(context)["settings"]
        if not is_allowed(update, settings.allowed_user_ids):
            return
        await fn(update, context)
    wrapper.__name__ = fn.__name__
    return wrapper


# ── Commands ──────────────────────────────────────────────────────────────

@_guard
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "iAgent online.\n"
        "Send me any message and I'll get to work.\n\n"
        "Commands: /help"
    )


@_guard
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["*iAgent commands*\n"]
    for cmd in BOT_COMMANDS:
        lines.append(f"/{cmd.command} — {cmd.description}")
    lines += [
        "",
        "Or just talk to me in plain language — I have tools for shell, "
        "files, HTTP, clipboard, Shortcuts, HealthKit, HomeKit, and more.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@_guard
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    memory: Memory = _app_data(context)["memory"]
    await memory.clear(update.effective_chat.id)
    await update.message.reply_text("Conversation history cleared.")


@_guard
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = _app_data(context)["settings"]
    memory: Memory = _app_data(context)["memory"]
    chat_id = update.effective_chat.id

    history = await memory.get_history(chat_id, limit=200)
    msg_count = len(history)

    hb_interval = settings.heartbeat_interval
    hb_str = f"every {hb_interval}s" if hb_interval else "disabled"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hostname = platform.node() or "ipad"

    text = (
        f"*iAgent status*\n"
        f"Time:       {now}\n"
        f"Host:       {hostname}\n"
        f"Model:      {settings.openai_model}\n"
        f"History:    {msg_count} messages\n"
        f"Heartbeat:  {hb_str}\n"
        f"Skills dir: $IAGENT_HOME/skills/"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@_guard
async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from tools.skills import list_skills
    result = await list_skills()
    await update.message.reply_text(result, parse_mode="Markdown")


@_guard
async def cmd_facts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from tools.facts import list_facts
    result = await list_facts()
    await update.message.reply_text(result, parse_mode="Markdown")


@_guard
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = _app_data(context)["settings"]
    args = context.args  # words after /model

    if not args:
        await update.message.reply_text(
            f"Current model: `{settings.openai_model}`\n\n"
            "To switch: `/model gpt-4o-mini`",
            parse_mode="Markdown",
        )
        return

    new_model = args[0].strip()
    settings.openai_model = new_model
    await update.message.reply_text(f"Model switched to `{new_model}` (until restart).", parse_mode="Markdown")


@_guard
async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    memory: Memory = _app_data(context)["memory"]
    settings: Settings = _app_data(context)["settings"]
    chat_id = update.effective_chat.id
    history = await memory.get_history(chat_id, limit=500)
    count = len(history)
    window = settings.history_window
    await update.message.reply_text(
        f"*Conversation memory*\n"
        f"{count} messages stored\n"
        f"Active window: last {window} messages\n\n"
        f"Use /clear to wipe history.",
        parse_mode="Markdown",
    )


# ── Message handler ───────────────────────────────────────────────────────

@_guard
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text or ""
    if not user_text.strip():
        return

    settings: Settings = _app_data(context)["settings"]
    chat_id = update.effective_chat.id
    memory: Memory = _app_data(context)["memory"]
    openai_client: AsyncOpenAI = _app_data(context)["openai_client"]
    chat_context = ChatContext(
        chat_id=chat_id,
        history_window=settings.history_window,
        max_iterations=settings.max_iterations,
    )

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply = await loop_module.run(
            client=openai_client,
            model=settings.openai_model,
            context=chat_context,
            memory=memory,
            user_message=user_text,
        )
    except Exception as exc:
        logger.exception("Agent loop error for chat %d", chat_id)
        reply = f"Sorry, something went wrong: {exc}"

    for chunk in _split_message(reply, 4096):
        await update.message.reply_text(chunk)


def _split_message(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks


# ── Registration ──────────────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("clear",   cmd_clear))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("skills",  cmd_skills))
    app.add_handler(CommandHandler("facts",   cmd_facts))
    app.add_handler(CommandHandler("model",   cmd_model))
    app.add_handler(CommandHandler("memory",  cmd_memory))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
