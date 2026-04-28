from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
from datetime import datetime
from pathlib import Path

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agent.context import ChatContext
from agent.memory import Memory
import agent.loop as loop_module
from bot.middleware import is_allowed
from config.settings import Settings
from openai import AsyncOpenAI

logger = logging.getLogger("iagent.bot")

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))

BOT_COMMANDS = [
    BotCommand("start",     "Wake up the bot"),
    BotCommand("help",      "List all commands"),
    BotCommand("clear",     "Reset conversation history"),
    BotCommand("status",    "Show uptime, model, memory stats"),
    BotCommand("skills",    "List available skills"),
    BotCommand("facts",     "List remembered facts"),
    BotCommand("model",     "Show or switch the AI model"),
    BotCommand("memory",    "Show how many messages are in history"),
    BotCommand("battery",   "Battery level and charging state"),
    BotCommand("wifi",      "Wi-Fi SSID and IP address"),
    BotCommand("disk",      "Disk usage"),
    BotCommand("ip",        "All network interface addresses"),
    BotCommand("processes", "Top 10 processes by CPU usage"),
    BotCommand("logs",      "Last 30 log lines"),
    BotCommand("restart",   "Restart the bot (back in ~5 s)"),
]


_SHELL_CANDIDATES = ["/var/jb/bin/sh", "/bin/sh", "/var/jb/usr/bin/sh"]


def _find_shell() -> str:
    for s in _SHELL_CANDIDATES:
        if Path(s).exists():
            return s
    return "/bin/sh"


async def _shell(cmd: str, timeout: float = 10.0) -> str:
    """Run a shell command, return combined stdout+stderr as a string."""
    sh = _find_shell()
    try:
        # exec with explicit shell path — /bin/sh is a stub on rootless Dopamine
        proc = await asyncio.create_subprocess_exec(
            sh, "-c", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(errors="replace").strip() or "(no output)"
    except asyncio.TimeoutError:
        return f"(timed out after {timeout:.0f}s)"
    except Exception as exc:
        return f"(error: {exc})"


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
    sections = {
        "General": ["start", "help", "clear", "status", "model", "memory"],
        "Agent":   ["skills", "facts"],
        "iOS":     ["battery", "wifi", "disk", "ip", "processes", "logs", "restart"],
    }
    lines = ["*iAgent commands*\n"]
    cmd_map = {c.command: c.description for c in BOT_COMMANDS}
    for section, cmds in sections.items():
        lines.append(f"_{section}_")
        for name in cmds:
            lines.append(f"  /{name} — {cmd_map.get(name, '')}")
        lines.append("")
    lines.append("Or just talk to me in plain language.")
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


# ── iOS / system commands ─────────────────────────────────────────────────

@_guard
async def cmd_battery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # iOS jailbreak: battery info lives in sysfs or via upower
    out = await _shell(
        "( "
        "  pct=$(cat /sys/class/power_supply/battery/capacity 2>/dev/null) && "
        "  sta=$(cat /sys/class/power_supply/battery/status 2>/dev/null) && "
        "  echo \"${pct}% — ${sta}\""
        ") || "
        "upower -i $(upower -e 2>/dev/null | grep battery | head -1) 2>/dev/null | "
        "  grep -E 'percentage|state' | sed 's/^[ ]*//' || "
        "echo 'Battery info unavailable. Try: apt install upower'"
    )
    await update.message.reply_text(f"*Battery*\n{out}", parse_mode="Markdown")


@_guard
async def cmd_wifi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ipconfig getifaddr is available on iOS; SSID needs wifiman or similar
    ip = await _shell(
        "ipconfig getifaddr en0 2>/dev/null || "
        "ifconfig en0 2>/dev/null | grep 'inet ' | awk '{print $2}'"
    )
    ssid = await _shell(
        "/var/jb/usr/sbin/wifiman -I 2>/dev/null | grep SSID | head -1 || "
        "cat /var/jb/var/mobile/Library/Preferences/com.apple.wifi.plist 2>/dev/null | "
        "  strings | grep -A1 'SSIDString' | tail -1 || "
        "echo 'SSID: (install wifiman via Sileo for SSID)'"
    )
    await update.message.reply_text(
        f"*Wi-Fi*\n{ssid.strip()}\nIP: `{ip.strip() or 'not connected'}`",
        parse_mode="Markdown",
    )


@_guard
async def cmd_disk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    out = await _shell("df -h / /var/jb 2>/dev/null || df -h /")
    await update.message.reply_text(f"*Disk usage*\n```\n{out}\n```", parse_mode="Markdown")


@_guard
async def cmd_ip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    out = await _shell(
        "ifconfig 2>/dev/null | grep -E '^[a-z]|inet ' | grep -v '127.0.0.1' | grep -v ' ::1'"
    )
    await update.message.reply_text(f"*Network interfaces*\n```\n{out}\n```", parse_mode="Markdown")


@_guard
async def cmd_processes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ps on iOS/Procursus supports BSD flags
    out = await _shell("ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -t' ' -k2 -rn | head -11")
    await update.message.reply_text(f"*Top processes (CPU%)*\n```\n{out}\n```", parse_mode="Markdown")


@_guard
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    n = 30
    if args:
        try:
            n = max(1, min(int(args[0]), 100))
        except ValueError:
            pass

    log_dir = _IAGENT_HOME / "logs"
    lines_all: list[str] = []
    for name in ("iagent.log", "stderr.log"):
        p = log_dir / name
        if p.exists():
            text = p.read_text(errors="replace").splitlines()
            lines_all += [f"[{name}] {l}" for l in text[-n:]]

    if not lines_all:
        await update.message.reply_text("No log files found yet.")
        return

    tail = "\n".join(lines_all[-n:])
    for chunk in _split_message(f"```\n{tail}\n```", 4096):
        await update.message.reply_text(chunk, parse_mode="Markdown")


@_guard
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Restarting iAgent in 3 s… I'll be back shortly.")

    iagent_cmd = str(_IAGENT_HOME / "iagent")
    if not Path(iagent_cmd).exists():
        iagent_cmd = shutil.which("iagent") or "iagent"

    async def _do_restart() -> None:
        await asyncio.sleep(3)
        proc = await asyncio.create_subprocess_exec(
            iagent_cmd, "restart",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    asyncio.create_task(_do_restart())


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

    # Make this chat reachable from photo tool's send_photo etc.
    from tools.photo import current_chat_id as _photo_chat_id
    _photo_chat_id.set(chat_id)

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
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("clear",     cmd_clear))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("skills",    cmd_skills))
    app.add_handler(CommandHandler("facts",     cmd_facts))
    app.add_handler(CommandHandler("model",     cmd_model))
    app.add_handler(CommandHandler("memory",    cmd_memory))
    app.add_handler(CommandHandler("battery",   cmd_battery))
    app.add_handler(CommandHandler("wifi",      cmd_wifi))
    app.add_handler(CommandHandler("disk",      cmd_disk))
    app.add_handler(CommandHandler("ip",        cmd_ip))
    app.add_handler(CommandHandler("processes", cmd_processes))
    app.add_handler(CommandHandler("logs",      cmd_logs))
    app.add_handler(CommandHandler("restart",   cmd_restart))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
