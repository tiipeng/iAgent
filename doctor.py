#!/usr/bin/env python3
"""iAgent doctor — read-only health check.

Runs through every known failure mode and prints green/red. Each red row
includes a fix suggestion. Also populates the capability registry as a
side effect so tools can query it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

import capabilities

IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))
ENV_PATH = IAGENT_HOME / ".env"
CONFIG_PATH = IAGENT_HOME / "config.json"
LOG_DIR = IAGENT_HOME / "logs"
VENV_PYTHON = IAGENT_HOME / "venv" / "bin" / "python"

GREEN = "\033[1;32m"
RED = "\033[1;31m"
YELLOW = "\033[1;33m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class Result:
    name: str
    ok: bool
    message: str
    fix: Optional[str] = None


def _line(r: Result) -> None:
    mark = f"{GREEN}✓{RESET}" if r.ok else f"{RED}✗{RESET}"
    print(f"{mark} {r.name}: {r.message}")
    if not r.ok and r.fix:
        print(f"  {DIM}→ fix:{RESET} {r.fix}")


# ── Env reader ──────────────────────────────────────────────────────────
def _read_env() -> dict:
    if not ENV_PATH.exists():
        return {}
    out: dict = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


# ── Checks ──────────────────────────────────────────────────────────────
def check_python() -> Result:
    py = "/var/jb/usr/bin/python3.9"
    if not Path(py).exists():
        py = shutil.which("python3") or ""
    if not py:
        return Result("python", False, "no python3 found", "install via Sileo: python3")
    try:
        r = subprocess.run([py, "-V"], capture_output=True, text=True, check=False)
        version = r.stdout.strip() or r.stderr.strip()
        return Result("python", True, f"{version} at {py}")
    except Exception as e:
        return Result("python", False, str(e))


def check_venv() -> Result:
    if not VENV_PYTHON.exists():
        return Result(
            "venv",
            False,
            f"missing at {VENV_PYTHON}",
            "re-run: curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh",
        )
    try:
        r = subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=True,
            check=False,
        )
        count = len([l for l in r.stdout.splitlines() if l.strip()])
        return Result("venv", True, f"{count} packages installed")
    except Exception as e:
        return Result("venv", False, str(e))


def check_env_file() -> Result:
    if not ENV_PATH.exists():
        return Result(
            "env",
            False,
            f".env missing at {ENV_PATH}",
            f"run: {IAGENT_HOME}/setup",
        )
    env = _read_env()
    missing = [k for k in ("TELEGRAM_TOKEN", "OPENAI_API_KEY") if not env.get(k)]
    if missing:
        return Result(
            "env",
            False,
            f"missing keys: {', '.join(missing)}",
            f"run: {IAGENT_HOME}/setup",
        )
    return Result("env", True, "TELEGRAM_TOKEN + OPENAI_API_KEY present")


def check_config() -> Result:
    if not CONFIG_PATH.exists():
        return Result(
            "config",
            False,
            f"config.json missing at {CONFIG_PATH}",
            f"run: {IAGENT_HOME}/setup",
        )
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as e:
        return Result("config", False, f"invalid JSON: {e}", f"edit {CONFIG_PATH}")
    ids = cfg.get("allowed_user_ids", [])
    if not ids:
        return Result(
            "config",
            False,
            "allowed_user_ids is empty (anyone could use the bot)",
            f"run: {IAGENT_HOME}/setup  or set allowed_user_ids in {CONFIG_PATH}",
        )
    return Result("config", True, f"allowed_user_ids has {len(ids)} entry/entries")


def check_telegram_token() -> Result:
    env = _read_env()
    token = env.get("TELEGRAM_TOKEN", "")
    if not token:
        return Result("telegram", False, "no token to verify")
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10.0,
        )
        if r.status_code == 200 and r.json().get("ok"):
            uname = r.json()["result"].get("username", "?")
            return Result("telegram", True, f"verified — bot @{uname}")
        return Result(
            "telegram",
            False,
            f"rejected (HTTP {r.status_code})",
            f"run: {IAGENT_HOME}/setup",
        )
    except Exception as e:
        return Result("telegram", False, f"network error: {e}")


def check_openai_key() -> Result:
    env = _read_env()
    key = env.get("OPENAI_API_KEY", "")
    if not key:
        return Result("openai", False, "no key to verify")
    try:
        r = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        if r.status_code == 200:
            return Result("openai", True, "verified")
        return Result(
            "openai",
            False,
            f"rejected (HTTP {r.status_code})",
            f"run: {IAGENT_HOME}/setup",
        )
    except Exception as e:
        return Result("openai", False, f"network error: {e}")


def check_tmux() -> Result:
    """iAgent runs inside a tmux session named 'iagent'. iOS aggressively
    kills system-domain LaunchDaemons that touch the network, so the
    canonical way to keep the bot alive is `iagent` (which spawns tmux).
    """
    if not shutil.which("tmux"):
        return Result(
            "tmux",
            False,
            "tmux is not installed",
            "sudo apt install tmux",
        )
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", "iagent"],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            # Get the pane PID for context
            p = subprocess.run(
                ["tmux", "list-panes", "-t", "iagent", "-F", "#{pane_pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            pid = p.stdout.strip().splitlines()[0] if p.stdout.strip() else "?"
            return Result("bot", True, f"running in tmux session 'iagent' (pid={pid})")
        return Result(
            "bot",
            False,
            "not running",
            "start with:  iagent",
        )
    except Exception as e:
        return Result("bot", False, str(e))


def check_logs() -> Result:
    if not LOG_DIR.exists():
        return Result("logs", True, "no log dir yet (daemon hasn't started)")
    files = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return Result("logs", True, "log dir empty")
    latest = files[0]
    age_s = max(0, int(time.time() - latest.stat().st_mtime))
    # Just report freshness; don't grep for errors here (too noisy).
    return Result("logs", True, f"{latest.name} last modified {age_s}s ago")


def check_disk() -> Result:
    try:
        st = shutil.disk_usage("/var/jb")
        free_mb = st.free // (1024 * 1024)
        if free_mb < 200:
            return Result(
                "disk",
                False,
                f"only {free_mb} MB free on /var/jb",
                "free space — apt-get clean, remove unused packages",
            )
        return Result("disk", True, f"{free_mb} MB free on /var/jb")
    except Exception as e:
        return Result("disk", False, str(e))


def check_ca_certs() -> Result:
    cert = Path("/var/jb/etc/ssl/cert.pem")
    if cert.exists():
        return Result("ca-certificates", True, str(cert))
    return Result(
        "ca-certificates",
        False,
        "missing — TLS may fail",
        "sudo apt install ca-certificates",
    )


# ── Main ────────────────────────────────────────────────────────────────
CHECKS: list[Callable[[], Result]] = [
    check_python,
    check_venv,
    check_env_file,
    check_config,
    check_telegram_token,
    check_openai_key,
    check_tmux,
    check_logs,
    check_disk,
    check_ca_certs,
]


def main() -> int:
    print(f"\n\033[1miAgent doctor\033[0m  {DIM}home={IAGENT_HOME}{RESET}")
    print(DIM + "─" * 60 + RESET)

    results = []
    for fn in CHECKS:
        try:
            r = fn()
        except Exception as e:
            r = Result(fn.__name__.replace("check_", ""), False, f"check crashed: {e}")
        results.append(r)
        _line(r)

    # Refresh capability registry as a side effect
    print(DIM + "─" * 60 + RESET)
    print(f"{DIM}refreshing capability registry…{RESET}")
    reg = capabilities.load()
    reg["apt"] = capabilities.probe_apt(["pbcopy", "pbpaste", "ca-certificates", "clang", "shortcuts"])
    sc = capabilities.probe_shortcuts()
    if sc is not None:
        reg["shortcuts"] = sc
    capabilities.save(reg)
    print(f"  apt:        {', '.join(f'{k}={v}' for k, v in reg['apt'].items())}")
    print(f"  shortcuts:  {len(reg['shortcuts'])} registered")
    print()

    failed = sum(1 for r in results if not r.ok)
    if failed:
        print(f"{RED}{failed} check(s) failed{RESET}")
        return 1
    print(f"{GREEN}all good{RESET}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
