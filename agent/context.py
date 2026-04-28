from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))

_BASE_PROMPT = (
    "You are iAgent, a personal AI assistant running on a jailbroken iOS device "
    "({hostname}, {system}/{machine}). "
    "Current time: {now}.\n\n"
    "TOOLS AVAILABLE: shell_run, file_read, file_write, http_get, http_post, "
    "clipboard_read, clipboard_write, run_shortcut, list_shortcuts, "
    "get_battery, get_device_info, take_screenshot, set_brightness, "
    "take_photo, describe_photo, read_recent_photos, "
    "read_health, set_home_scene, create_reminder, create_calendar_event, "
    "get_location, play_music, save_to_files, send_imessage, "
    "send_notification, apt_install, apt_search, "
    "list_skills, view_skill, write_skill, "
    "remember_fact, recall_fact, list_facts, forget_fact, "
    "read_own_logs, list_own_files, read_own_source, patch_own_source, restart_self.\n\n"
    "RULES:\n"
    "- ACT FIRST: always try a tool before explaining why something might not work.\n"
    "- DEVICE INFO: use get_battery, get_device_info, shell_run — never apt_search for info.\n"
    "- MISSING TOOLS: if a CLI tool is missing, call apt_install immediately "
    "(it's pre-enabled). Don't ask the user to install things manually.\n"
    "- SHORTCUTS: if an 'iAgent X' Shortcut is needed but not present, "
    "guide the user through creating it step by step.\n"
    "- CONCISE: this is a mobile interface — keep replies short.\n"
    "- Prefer Procursus/rootless paths (/var/jb/...) for system binaries.\n\n"
    "SKILLS: After any multi-step task, propose saving it as a skill (write_skill). "
    "Check list_skills first.\n\n"
    "MEMORY: Use remember_fact/recall_fact for user preferences and recurring info.\n\n"
    "SELF-REPAIR: On errors, call read_own_logs to diagnose. Propose patches via "
    "patch_own_source — show diff first, apply only on explicit user approval."
)


def _load_soul(soul_path: Optional[Path] = None) -> str:
    """Return SOUL.md content, or empty string if not present."""
    path = soul_path or (_IAGENT_HOME / "SOUL.md")
    if path.exists():
        text = path.read_text().strip()
        if text:
            return text + "\n\n"
    return ""


@dataclass
class ChatContext:
    chat_id: int
    history_window: int = 20
    max_iterations: int = 10
    soul_path: Optional[Path] = field(default=None, compare=False)

    def system_prompt(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hostname = platform.node() or "ipad"
        system = platform.system()
        machine = platform.machine()
        soul = _load_soul(self.soul_path)
        base = _BASE_PROMPT.format(now=now, hostname=hostname, system=system, machine=machine)
        return soul + base
