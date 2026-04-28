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
    "You have access to tools that can run shell commands, read/write files, "
    "fetch URLs, manage the clipboard, run iOS Shortcuts, and more. "
    "Be concise in your replies — this is a mobile interface. "
    "When using the shell tool, prefer Procursus/rootless paths (/var/jb/...) "
    "for system binaries on iOS.\n\n"
    "SKILLS: After completing any multi-step task, consider whether the procedure "
    "is worth saving for reuse. If so, propose it to the user and — on approval — "
    "call write_skill. Use list_skills and view_skill before inventing a procedure "
    "that might already exist.\n\n"
    "MEMORY: Use remember_fact / recall_fact for anything the user wants remembered "
    "across conversations (preferences, names, schedules, etc.).\n\n"
    "SELF-REPAIR: If a tool fails or you see an error, call read_own_logs to "
    "diagnose it. You may propose a source patch via patch_own_source — but ALWAYS "
    "show the diff to the user and wait for explicit approval before applying."
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
