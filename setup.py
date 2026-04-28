#!/usr/bin/env python3
"""iAgent interactive setup wizard.

Walks a fresh user through onboarding: Telegram token, OpenAI key,
allowed user ID, optional SOUL.md, heartbeat interval, optional
LaunchDaemon install. Validates tokens BEFORE writing files so a
typo never lands in .env and crashes the daemon.

Re-runnable: detects existing values and offers to keep them.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))
ENV_PATH = IAGENT_HOME / ".env"
CONFIG_PATH = IAGENT_HOME / "config.json"
SOUL_PATH = IAGENT_HOME / "SOUL.md"
PLIST_NAME = "com.tiipeng.iagent.plist"
PLIST_SRC = IAGENT_HOME / PLIST_NAME
PLIST_DEST = Path("/var/jb/Library/LaunchDaemons") / PLIST_NAME

# ── Pretty output ───────────────────────────────────────────────────────
GREEN = "\033[1;32m"
RED = "\033[1;31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def info(msg: str) -> None:
    print(f"{DIM}      {msg}{RESET}")


def ok(msg: str) -> None:
    print(f"      {GREEN}→{RESET} {msg}")


def err(msg: str) -> None:
    print(f"      {RED}✗{RESET} {msg}")


def step(n: int, total: int, title: str) -> None:
    print(f"\n{BOLD}[{n}/{total}]{RESET} {title}")


def heading() -> None:
    print(f"{BOLD}iAgent setup wizard{RESET}")
    print(DIM + "─" * 60 + RESET)
    print(f"  Home: {IAGENT_HOME}")
    print()


# ── Existing values ─────────────────────────────────────────────────────
def read_existing_env() -> dict:
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


def read_existing_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}


# ── Validators ──────────────────────────────────────────────────────────
def verify_telegram(token: str) -> Optional[str]:
    """Return bot username on success, None on failure."""
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10.0,
        )
        if r.status_code == 200 and r.json().get("ok"):
            return r.json()["result"].get("username", "?")
    except Exception:
        pass
    return None


def verify_openai(api_key: str) -> bool:
    try:
        r = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        return r.status_code == 200
    except Exception:
        return False


# ── Prompts ─────────────────────────────────────────────────────────────
def prompt_secret(label: str, current: str = "") -> str:
    if current:
        masked = current[:6] + "…" + current[-4:] if len(current) > 12 else "****"
        keep = input(f"  {label} [keep current: {masked}]: ").strip()
        if not keep:
            return current
        return keep
    while True:
        v = getpass.getpass(f"  {label}: ").strip()
        if v:
            return v
        err("required")


def prompt_text(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    v = input(f"  {label}{suffix}: ").strip()
    return v or default


def prompt_yes_no(label: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    v = input(f"  {label} {suffix}: ").strip().lower()
    if not v:
        return default
    return v in ("y", "yes")


# ── File writers ────────────────────────────────────────────────────────
def write_env(telegram_token: str, openai_key: str) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "# iAgent secrets — never commit this file.\n"
        f"TELEGRAM_TOKEN={telegram_token}\n"
        f"OPENAI_API_KEY={openai_key}\n"
    )
    ENV_PATH.write_text(body)
    os.chmod(ENV_PATH, 0o600)


def write_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


SOUL_TEMPLATE = """# SOUL.md — iAgent personality

This text is prepended to the system prompt on every turn. Keep it short
and concrete. Examples that work well:

- You are terse. No fluff. No "as an AI…".
- Reply in the same language as the user's message.
- When the user asks for a command, run it instead of explaining how to.
- If a tool fails, try a different approach before giving up.

Write your own preferences below this line.

---

"""


# ── Main flow ───────────────────────────────────────────────────────────
def main() -> int:
    heading()

    existing_env = read_existing_env()
    existing_cfg = read_existing_config()

    # ── 1. Telegram token ────────────────────────────────────────────────
    step(1, 6, "Telegram bot token (from @BotFather)")
    while True:
        token = prompt_secret("Token", existing_env.get("TELEGRAM_TOKEN", ""))
        info("verifying…")
        username = verify_telegram(token)
        if username:
            ok(f"verified — bot is @{username}")
            break
        err("Telegram rejected this token. Try again, or Ctrl-C to abort.")

    # ── 2. OpenAI key ────────────────────────────────────────────────────
    step(2, 6, "OpenAI API key (sk-…)")
    while True:
        key = prompt_secret("Key", existing_env.get("OPENAI_API_KEY", ""))
        info("verifying…")
        if verify_openai(key):
            ok("verified")
            break
        err("OpenAI rejected this key. Try again, or Ctrl-C to abort.")

    write_env(token, key)
    ok(f"wrote {ENV_PATH}")

    # ── 3. Allowed user ID ───────────────────────────────────────────────
    step(3, 6, "Your Telegram numeric user ID (from @userinfobot)")
    current_ids = existing_cfg.get("allowed_user_ids", [])
    default = str(current_ids[0]) if current_ids else ""
    while True:
        raw = prompt_text("User ID", default)
        if not raw:
            err("required — bot must know who is allowed to talk to it")
            continue
        try:
            uid = int(raw)
            break
        except ValueError:
            err("must be a number")

    # ── 4. SOUL.md ───────────────────────────────────────────────────────
    step(4, 6, "Personality / SOUL.md")
    if SOUL_PATH.exists():
        info(f"existing SOUL.md found ({SOUL_PATH.stat().st_size} bytes)")
        edit = prompt_yes_no("Open editor to edit it now?", default=False)
    else:
        edit = prompt_yes_no("Create SOUL.md from template and open editor now?", default=False)
        if edit:
            SOUL_PATH.write_text(SOUL_TEMPLATE)
    if edit:
        editor = os.environ.get("EDITOR", "nano")
        if not shutil.which(editor):
            editor = "nano" if shutil.which("nano") else "vi"
        subprocess.run([editor, str(SOUL_PATH)], check=False)

    # ── 5. Heartbeat ─────────────────────────────────────────────────────
    step(5, 6, "Heartbeat — periodic self-prompts (Phase 2.2 — not yet implemented)")
    info("setting saved for when heartbeat ships; 0 = disabled")
    current_hb = existing_cfg.get("heartbeat_interval", 0)
    raw = prompt_text("Interval in minutes (0 = disabled)", str(current_hb))
    try:
        heartbeat_min = max(0, int(raw))
    except ValueError:
        heartbeat_min = 0

    # ── Persist config ───────────────────────────────────────────────────
    cfg = {
        "openai_model": existing_cfg.get("openai_model", "gpt-4o"),
        "allowed_user_ids": [uid],
        "history_window": existing_cfg.get("history_window", 20),
        "max_iterations": existing_cfg.get("max_iterations", 10),
        "shell_timeout": existing_cfg.get("shell_timeout", 30),
        "shell_allowlist": existing_cfg.get("shell_allowlist", None),
        "heartbeat_interval": heartbeat_min * 60,
        # Phase 1.3 apt_install — disabled by default
        "apt_install_enabled": existing_cfg.get("apt_install_enabled", False),
        "apt_install_allowlist": existing_cfg.get("apt_install_allowlist", []),
    }
    write_config(cfg)
    ok(f"wrote {CONFIG_PATH}")

    # ── 6. LaunchDaemon ──────────────────────────────────────────────────
    step(6, 6, "Install LaunchDaemon (auto-start at boot, requires sudo)")
    if not PLIST_SRC.exists():
        err(f"plist source missing at {PLIST_SRC} — re-run install.sh first")
    else:
        already_loaded = _daemon_loaded()
        if already_loaded:
            info("daemon already loaded — will reload to pick up new config")
        if prompt_yes_no("Install / reload the daemon now?", default=True):
            _install_daemon()

    # ── Done ─────────────────────────────────────────────────────────────
    print(f"\n{GREEN}✓ Setup complete.{RESET}")
    print(f"  Logs:    {DIM}tail -f {IAGENT_HOME}/logs/stderr.log{RESET}")
    print(f"  Status:  {DIM}launchctl list | grep iagent{RESET}")
    print(f"  CLI:     {DIM}{IAGENT_HOME}/chat{RESET}")
    print()
    print("  In Telegram, search for your bot and tap Start.")
    return 0


# ── Daemon helpers ──────────────────────────────────────────────────────
def _daemon_loaded() -> bool:
    try:
        out = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, check=False
        )
        return "com.tiipeng.iagent" in out.stdout
    except Exception:
        return False


def _install_daemon() -> None:
    cmds = [
        ["sudo", "cp", str(PLIST_SRC), str(PLIST_DEST)],
        ["sudo", "chown", "root:wheel", str(PLIST_DEST)],
        ["sudo", "chmod", "644", str(PLIST_DEST)],
    ]
    if _daemon_loaded():
        cmds.insert(0, ["sudo", "launchctl", "unload", str(PLIST_DEST)])
    cmds.append(["sudo", "launchctl", "load", str(PLIST_DEST)])

    for cmd in cmds:
        info(" ".join(cmd))
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            err(f"command failed (exit {result.returncode})")
            return
    ok("daemon loaded")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\naborted.")
        sys.exit(130)
