from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ChatContext:
    chat_id: int
    history_window: int = 20
    max_iterations: int = 10

    def system_prompt(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hostname = platform.node() or "ipad"
        system = platform.system()
        machine = platform.machine()
        return (
            f"You are iAgent, a personal AI assistant running on a jailbroken iOS device "
            f"({hostname}, {system}/{machine}). "
            f"Current time: {now}.\n\n"
            "You have access to tools that can run shell commands, read/write files, "
            "and make HTTP requests directly on this device. "
            "Be concise in your replies — this is a mobile interface. "
            "When using the shell tool, prefer Procursus/rootless paths (/var/jb/...) "
            "for system binaries on iOS."
        )
