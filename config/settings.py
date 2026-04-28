from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_DEFAULT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))


@dataclass
class Settings:
    # secrets (from .env)
    telegram_token: str
    openai_api_key: str

    # model
    openai_model: str = "gpt-4o"

    # bot security
    allowed_user_ids: list[int] = field(default_factory=list)

    # paths
    data_dir: Path = _DEFAULT_HOME
    workspace_root: Path = field(default_factory=lambda: _DEFAULT_HOME / "workspace")
    db_path: Path = field(default_factory=lambda: _DEFAULT_HOME / "iagent.db")
    log_dir: Path = field(default_factory=lambda: _DEFAULT_HOME / "logs")

    # agent
    history_window: int = 20
    max_iterations: int = 10

    # tools
    shell_timeout: int = 30
    shell_allowlist: Optional[list[str]] = None  # None = allow all

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.workspace_root = Path(self.workspace_root)
        self.db_path = Path(self.db_path)
        self.log_dir = Path(self.log_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def load_settings(
    env_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> Settings:
    home = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))

    # load .env — explicit path first, then IAGENT_HOME/.env, then cwd/.env
    for candidate in filter(None, [env_path, home / ".env", Path(".env")]):
        if Path(candidate).exists():
            load_dotenv(candidate)
            break

    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")

    if not telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN is not set. Add it to .env or environment.")
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env or environment.")

    # load optional JSON config (we used to support YAML but PyYAML has
    # no prebuilt wheel for iOS Python 3.9, so JSON keeps the install
    # zero-dependency on the device)
    cfg: dict = {}
    for candidate in filter(None, [config_path, home / "config.json", Path("config.json")]):
        p = Path(candidate)
        if p.exists():
            with open(p) as f:
                cfg = json.load(f) or {}
            break

    allowed_raw = cfg.get("allowed_user_ids", [])
    allowed_ids = [int(x) for x in allowed_raw]

    return Settings(
        telegram_token=telegram_token,
        openai_api_key=openai_api_key,
        openai_model=cfg.get("openai_model", "gpt-4o"),
        allowed_user_ids=allowed_ids,
        data_dir=Path(cfg.get("data_dir", home)),
        workspace_root=Path(cfg.get("workspace_root", home / "workspace")),
        db_path=Path(cfg.get("db_path", home / "iagent.db")),
        log_dir=Path(cfg.get("log_dir", home / "logs")),
        history_window=int(cfg.get("history_window", 20)),
        max_iterations=int(cfg.get("max_iterations", 10)),
        shell_timeout=int(cfg.get("shell_timeout", 30)),
        shell_allowlist=cfg.get("shell_allowlist", None),
    )
