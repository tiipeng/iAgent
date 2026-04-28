from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
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

    # load optional YAML config
    yaml_cfg: dict = {}
    for candidate in filter(None, [config_path, home / "config.yaml", Path("config.yaml")]):
        p = Path(candidate)
        if p.exists():
            with open(p) as f:
                yaml_cfg = yaml.safe_load(f) or {}
            break

    allowed_raw = yaml_cfg.get("allowed_user_ids", [])
    allowed_ids = [int(x) for x in allowed_raw]

    return Settings(
        telegram_token=telegram_token,
        openai_api_key=openai_api_key,
        openai_model=yaml_cfg.get("openai_model", "gpt-4o"),
        allowed_user_ids=allowed_ids,
        data_dir=Path(yaml_cfg.get("data_dir", home)),
        workspace_root=Path(yaml_cfg.get("workspace_root", home / "workspace")),
        db_path=Path(yaml_cfg.get("db_path", home / "iagent.db")),
        log_dir=Path(yaml_cfg.get("log_dir", home / "logs")),
        history_window=int(yaml_cfg.get("history_window", 20)),
        max_iterations=int(yaml_cfg.get("max_iterations", 10)),
        shell_timeout=int(yaml_cfg.get("shell_timeout", 30)),
        shell_allowlist=yaml_cfg.get("shell_allowlist", None),
    )
