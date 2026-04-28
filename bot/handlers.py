from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agent.context import ChatContext
from agent.memory import Memory
import agent.loop as loop_module
from bot.middleware import is_allowed
from config.settings import Settings
from openai import AsyncOpenAI

logger = logging.getLogger("iagent.bot")


def _app_data(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = _app_data(context)["settings"]
    if not is_allowed(update, settings.allowed_user_ids):
        return

    await update.message.reply_text(
        "👾 iAgent online.\n"
        "I can run commands, read/write files, and fetch URLs on this device.\n"
        "Use /clear to reset your conversation history."
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = _app_data(context)["settings"]
    if not is_allowed(update, settings.allowed_user_ids):
        return

    memory: Memory = _app_data(context)["memory"]
    chat_id = update.effective_chat.id
    await memory.clear(chat_id)
    await update.message.reply_text("Conversation history cleared.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = _app_data(context)["settings"]
    if not is_allowed(update, settings.allowed_user_ids):
        logger.warning("Blocked message from user %s", update.effective_user)
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    chat_id = update.effective_chat.id
    memory: Memory = _app_data(context)["memory"]
    openai_client: AsyncOpenAI = _app_data(context)["openai_client"]
    chat_context = ChatContext(
        chat_id=chat_id,
        history_window=settings.history_window,
        max_iterations=settings.max_iterations,
    )

    # Show typing indicator while the agent works
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

    # Telegram message limit is 4096 chars; split if needed
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


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
