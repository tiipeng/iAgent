# iAgent

Personal AI agent that runs **natively on a jailbroken iPad** — Telegram bot + local CLI, powered by **OpenAI GPT-4o** with tool calling. It can run shell commands, read/write files, fetch URLs, control the clipboard, use XXTouch for screenshots/UI automation, inspect device state, remember facts, manage skills, debug its own runtime, and operate Homebridge through a jailbroken-iOS-safe ops layer. No cloud relay, no Docker.

Inspired by [openclaw](https://github.com/openclaw/openclaw) and [hermes-agent](https://github.com/NousResearch/hermes-agent), but rebuilt for the realities of rootless Dopamine on iOS 15–16.

---

## Table of contents

- [Quick install](#quick-install)
- [The `iagent` command](#the-iagent-command--daily-driver)
- [Telegram slash commands](#telegram-slash-commands)
- [CLI REPL slash commands](#cli-repl-slash-commands)
- [Agent tools](#agent-tools)
- [iPad ops layer](#ipad-ops-layer)
- [Native iOS automation realities](#native-ios-automation-realities)
- [Configuration reference](#configuration-reference)
- [Architecture](#architecture)
- [Things we learned the hard way](#things-we-learned-the-hard-way)
- [Troubleshooting](#troubleshooting)

---

## Why this exists

Both `openclaw` and `hermes-agent` failed to install on a jailbroken iPad:

- **openclaw** — installer demands Homebrew, which on iOS thinks the user must be in the macOS `admin` group.
- **hermes-agent** — `pyproject.toml` requires Python ≥ 3.11, but Procursus ships only Python 3.9.9. Even with `--no-deps`, transitive deps like `jiter` and `tokenizers` need a Rust toolchain that doesn't recognise the iPad's machine triple.

iAgent is the same idea, rebuilt around what actually works on the device. The current build also includes an operations layer for a real jailbroken iPad setup: tmux-safe service management, Homebridge runbooks, self-tests, repair playbooks, an ops journal, and Telegram-friendly status cards.

---

## Requirements

**Hardware / OS**
- iPad or iPhone, **arm64e**, jailbroken with **Dopamine** (iOS 15.0–16.5.1, rootless)

**Sileo packages** (install from the default Procursus repo)
- `python3` (3.9.9 — bundled with Dopamine)
- `tmux` ← required for `iagent` to keep the bot alive in a session
- `git`, `curl`, `ca-certificates` — usually present
- `openssh` — recommended for editing config from a Mac
- *Optional but unlocks more features:* `pbcopy`/`pbpaste`, `jq`, `sqlite3`, `ffmpeg`, `socat`/`ncat`, `ios-mcp`, `XXTouch`, `clang`/`make` for rare native builds
- Homebridge support expects Node.js 18.x from Procursus or your rootless prefix

**Accounts you need**
- A [Telegram bot token](https://t.me/BotFather) (chat with `@BotFather` → `/newbot`)
- Your Telegram numeric user ID — message `@userinfobot` to get it
- An [OpenAI API key](https://platform.openai.com/api-keys)

---

## Quick install

Open a terminal on the iPad (NewTerm 3, or SSH from your Mac with `ssh mobile@<iPad-IP>`):

```bash
sudo apt install tmux
curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh
```

The bootstrap clones the repo, sets up a virtualenv, installs every pinned dependency from prebuilt wheels, then **launches an interactive setup wizard** that walks you through:

1. Telegram bot token (validated against `getMe` before saving)
2. OpenAI API key (validated against `/v1/models` before saving)
3. Your numeric Telegram user ID
4. Optional `SOUL.md` personality file
5. Heartbeat interval (0 = disabled)

After it finishes, **open a new shell** (or `source ~/.zshrc`):

```bash
iagent              # start the bot in a tmux session
```

That's it. Search for your bot's `@username` in Telegram, tap **Start**, and send a message.

---

## The `iagent` command — daily driver

Single entry point for everything:

| Command | What it does |
|---|---|
| `iagent` | Start the bot in tmux. If running, prints status. |
| `iagent attach` | Attach to the tmux session. **Detach with `Ctrl+B` then `D`** (don't `Ctrl+C` — kills the bot). |
| `iagent stop` | Kill the tmux session. |
| `iagent restart` | Stop + start. |
| `iagent status` | Print whether the bot is running. |
| `iagent logs` | Tail the log files. |
| `iagent fg` | Run the bot in the foreground — useful for live debugging. |
| `iagent chat` | Open the local CLI REPL (offline from Telegram). |
| `iagent setup` | Re-run the interactive setup wizard. |
| `iagent doctor` | Run the health check. |
| `iagent help` | Full help. |

**The bot survives** SSH disconnect, terminal close, login session changes. It dies on iPad reboot or under heavy memory pressure (rare).

> **Why no LaunchDaemon?** Tried multiple times. iOS aggressively SIGKILLs system-domain LaunchDaemons that touch the network — even on jailbreak. tmux is what every other persistent-process project on jailbroken iOS uses. See [§13 below](#13-launchdaemons-do-not-work-for-this-on-ios-rootless).

---

## Telegram slash commands

Type `/` in the chat or tap the bot's command menu. All commands are also auto-registered with Telegram so they appear in the suggestion list.

### General

| Command | What it does |
|---|---|
| `/start` | Wake up the bot |
| `/help` | List all commands grouped by category |
| `/clear` | Reset conversation history |
| `/status` | Time, host, model, history count, heartbeat state. For deep health, ask for a Steve/iAgent status card. |
| `/model` | Show current model |
| `/model gpt-4o-mini` | Switch model until next restart |
| `/memory` | Show conversation message count + window size |

### Agent state

| Command | What it does |
|---|---|
| `/skills` | List all available skills |
| `/facts` | List all remembered facts |

### iOS / system

| Command | What it does |
|---|---|
| `/battery` | Battery percentage and charging state (`ioreg` fallback on iOS) |
| `/wifi` | Wi-Fi SSID and IP address |
| `/disk` | Disk usage for `/` and `/var/jb` |
| `/ip` | All network interfaces |
| `/processes` | Top 10 processes by CPU |
| `/logs` | Last 30 log lines (or `/logs 50` for more) |
| `/restart` | Restart the bot — sends reply first, restarts after 3 s |

> **Anything else** — just talk in plain language. The agent has a tool for almost everything (see below).

---

## CLI REPL slash commands

`iagent chat` opens a local REPL that uses the **same** OpenAI client, memory, tools, and agent loop as the bot — but reads stdin / prints stdout. Conversations live under `chat_id = -1` so they don't pollute Telegram history. Tab-completion is enabled for all `/` commands.

| Command | What it does |
|---|---|
| `/help` | List all commands |
| `/clear` | Reset conversation history |
| `/skills` | List skills |
| `/facts` | List facts |
| `/tools` | List every registered agent tool by name |
| `/model` | Show current model |
| `/status` | Model, history count, db path |
| `/battery` | Battery info |
| `/wifi` | Wi-Fi info |
| `/disk` | Disk usage |
| `/ip` | Network interfaces |
| `/processes` | Top processes |
| `/logs [n]` | Last n log lines (default 30) |
| `/restart` | Restart the bot gateway |
| `/quit` | Exit the REPL |

---

## Agent tools

These are what the AI calls internally — you never invoke them directly, you just describe what you want and the agent picks the right tool.

### Core

| Tool | What it does |
|---|---|
| `shell` | Run a shell command through the iOS-safe subprocess layer |
| `read_file` / `write_file` / `list_files` | Sandboxed to `workspace_root` |
| `http_get` / `http_post` | aiohttp request, response truncated at 50 KB |
| `apt_install` / `apt_search` | Install / search Procursus packages — allowlist gated |

### Device

| Tool | What it does |
|---|---|
| `get_battery` | Battery % and charging state, including iOS `ioreg` fallback |
| `get_device_info` | Kernel, machine, OS, uptime, RAM |
| `screenshot_xx` / `look_at_screen` | XXTouch-backed screen capture with stale-file cleanup and optional vision description |
| `tap` / `swipe` / `scroll` / `press_home` | UI automation through XXTouch where available |
| `touch_backend_status` | Check whether the touch/screenshot backend is reachable |
| `set_brightness` | Set screen brightness 0.0–1.0 |
| `clipboard_read` / `clipboard_write` | iOS pasteboard via pbcopy/pbpaste |

### Native iOS and automation

| Tool | What it does |
|---|---|
| `open_url` | Open a URL with iOS URL schemes |
| `open_app` / `list_apps` | Launch or discover installed apps where bundle metadata is visible |
| `respring` | Trigger a respring when explicitly requested |
| `read_recent_photos` / `send_photo` | Read or send recent Photos-library items where permissions allow |
| `describe_photo(path, question)` | GPT-4o vision on an image file |
| `read_messages` | Read local Messages data where the device grants filesystem access |
| `read_contacts` | Read local contacts database |
| `read_calendar_events` | Read local Calendar events |
| `read_safari_history` | Inspect Safari history database |
| `list_voice_memos` | List locally stored Voice Memos |

> Shortcuts are documented as a caveat, not the primary backend. See [Native iOS automation realities](#native-ios-automation-realities).

### Memory

| Tool | What it does |
|---|---|
| `remember_fact(key, value)` | Save a fact across conversations |
| `recall_fact(key)` | Retrieve a fact |
| `list_facts` | List all stored facts |
| `forget_fact(key)` | Delete a fact |

### Skills

| Tool | What it does |
|---|---|
| `list_skills` | List all skills |
| `view_skill(name)` | Read a skill's full content |
| `write_skill(name, content)` | Save a new skill (`$IAGENT_HOME/skills/<name>.md`) |

### Self-debugging

| Tool | What it does |
|---|---|
| `read_own_logs(lines)` | Tail iagent.log + stderr.log |
| `list_own_files` | List Python files in `$IAGENT_HOME/code/` |
| `read_own_source(file)` | Read own source file |
| `patch_own_source(file, old, new, confirm)` | `confirm=false` shows diff; `confirm=true` writes `.bak` and applies |
| `restart_self` | Fire `iagent restart` after 3 s — reply lands first |

### Operations

| Tool | What it does |
|---|---|
| `start_service` / `stop_service` | Service lifecycle through iOS-safe runbooks |
| `diagnose_service` / `troubleshoot_service` | Structured service diagnostics and issue classification |
| `repair_service` | Cautious repair workflow with safe/unsafe action separation |
| `run_selftest` | Live health checks for the iAgent runtime and integrations |
| `read_ops_journal` / `summarize_ops_journal` | Redacted operational event history |
| `get_status_card` / `format_status_card` | Human-readable Telegram status summary |

---

## iPad ops layer

The current iAgent build includes a jailbroken-iPad operations layer. It is designed for the things that normally break on rootless Dopamine: tmux locale, long socket paths, Homebridge startup races, missing Linux utilities, Node/iOS quirks, and agent memory/tool-history problems.

### Service and Homebridge tools

| Tool | What it does |
|---|---|
| `start_service` / `stop_service` | Start/stop services using a runbook-safe environment |
| `diagnose_service` | Inspect service state, logs, ports, tmux panes, and known issue patterns |
| `wait_for_ports` | Retry port checks to avoid false failures during startup races |
| `troubleshoot_service` | Classify known issues and propose the next safe action |
| `inspect_service_listeners` | Inspect listeners or fall back to process candidates when `lsof` is missing |
| `repair_service` | Run cautious repair playbooks without broad process kills |

The bundled Homebridge runbook lives at [`runbooks/homebridge.json`](runbooks/homebridge.json). It knows the iOS-safe tmux approach, the Homebridge and Config UI ports, log paths, plugin paths, and common failure signatures such as invalid locale, port-in-use, Config UI v5 crashes, Ring not configured, and Samsung TV pairing waiting for physical confirmation.

### Self-test, journal, and status cards

| Tool | What it does |
|---|---|
| `run_selftest` | Checks iAgent runtime, tool registry, Homebridge, XXTouch, ios-mcp, battery probe, and history sanitizer |
| `read_ops_journal` | Reads recent redacted operational events |
| `summarize_ops_journal` | Summarizes recent selftests/troubleshooting/repairs |
| `get_status_card` / `format_status_card` | Produces a compact Telegram-friendly health card |

Example status-card output:

```text
✅ Steve/iAgent Status: OK
Checks: fail=0, ok=7, skip=0, warn=0
✅ iAgent runtime
✅ Tool registry
✅ Homebridge
✅ XXTouch
✅ ios-mcp
✅ Battery
✅ History sanitizer
```

### Scripts

| Script | Purpose |
|---|---|
| `scripts/selftest.py` | CLI entry point for the self-test suite |
| `scripts/regression_check.py` | Regression checks for the ops layer, runbooks, journal redaction, and status cards |

Run before shipping changes:

```bash
python3 -m compileall -q agent bot tools scripts main.py chat.py
python3 scripts/regression_check.py
python3 scripts/selftest.py --no-live
```

---

## Native iOS automation realities

Earlier versions tried to rely on a `shortcuts` CLI and direct Shortcuts database writes. On this iOS/rootless setup that is not reliable:

- The normal macOS `shortcuts` binary is not present on iOS.
- Direct SQLite inserts into `Shortcuts.sqlite` can appear in the database but are ignored by the Shortcuts runtime cache.
- Shortcuts created manually in the Shortcuts app can still be useful, but iAgent should not assume it can create or run them through a universal CLI.

Preferred working integrations today:

| Capability | Preferred path |
|---|---|
| Screen screenshots / taps / UI automation | XXTouch |
| Clipboard | `pbcopy` / `pbpaste` |
| Photos/files/databases | Direct file access and SQLite where permissions allow |
| ios-mcp | HTTP service on port `8090`, not stdio MCP |
| Homebridge / smart-home ops | tmux + runbook tools |
| Shortcuts-only features | Manual Shortcut setup, then call through a tested bridge if present |

The old `shortcuts_setup` skill remains as documentation of the caveats, not as a promise that every Shortcut bridge works automatically on iOS.

---

## Built-in skills

Files in `skills/*.md` (shipped with the repo) and `$IAGENT_HOME/skills/*.md` (user-created, persist across updates):

| Skill | Purpose |
|---|---|
| `battery` | Quick battery query |
| `disk_usage` | Free / used space |
| `wifi_info` | SSID + IP |
| `uptime` | Device uptime |
| `homebridge_ipad` | Homebridge on jailbroken iPad via tmux, not LaunchDaemon |
| `ipad_xxtouch_control` | XXTouch screenshots, taps, swipes, and UI automation |
| `ipad_native_data` | Notes about local iOS data stores and app access |
| `ios_mcp_notes` | ios-mcp HTTP service usage and caveats |
| `exit_node_proxy` | Tailscale/exit-node/proxy notes |
| `iagent_self_management` | How iAgent should inspect, patch, restart, and verify itself |
| `autonomous_troubleshooting` | Reproduce → inspect → hypothesize → safe fix → verify loop |
| `shortcuts_setup` | Shortcuts caveats; manual setup only where truly needed |

The agent reads them lazily via `view_skill` whenever a task seems to match. Add your own with `write_skill` or by writing a `.md` file in `$IAGENT_HOME/skills/`.

---

## Configuration reference

### `.env` (secrets — never commit)

| Key | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | From @BotFather |
| `OPENAI_API_KEY` | From platform.openai.com |

### `config.json`

| Key | Default | Purpose |
|---|---|---|
| `openai_model` | `gpt-4o` | Any model your key has access to |
| `allowed_user_ids` | `[]` (open) | Telegram numeric IDs allowed. **Always set this on a personal device.** |
| `history_window` | `20` | Messages kept in context per chat |
| `max_iterations` | `10` | Max tool-call rounds per user message |
| `shell_timeout` | `30` | Seconds before a shell command is killed |
| `shell_allowlist` | `null` | If set, only these commands may run |
| `apt_install_enabled` | `true` | Master switch for the `apt_install` tool |
| `apt_install_allowlist` | 15 packages | Package names the agent may install |
| `heartbeat_interval` | `0` | Seconds between heartbeat self-prompts (`0` = disabled) |
| `heartbeat_prompt` | empty | Custom self-prompt; defaults to a generic check-in |

### `SOUL.md` — personality

Free-form Markdown at `$IAGENT_HOME/SOUL.md`. Prepended to every system prompt. Examples that work well:

```
You are terse. No fluff.
Reply in the same language the user wrote.
You have a sarcastic streak.
Track my caffeine intake when I mention it.
```

No restart needed — re-read on every message.

---

## Architecture

```
┌────────────┐       ┌─────────────────┐       ┌──────────────┐
│ Telegram   │──────▶│ bot/handlers.py │       │ chat.py      │  (CLI)
│  app       │       │   PTB v20+ poll │       │   stdin/out  │
└────────────┘       └────────┬────────┘       └──────┬───────┘
                              │                       │
                              ▼                       ▼
                   ┌───────────────────────────────────────┐
                   │  agent/loop.py                        │
                   │  ┌─ build messages (SOUL+system+hist) │
                   │  ├─ openai.chat.completions.create    │
                   │  ├─ if tool_calls → asyncio.gather    │
                   │  │     ├─ tools.shell                 │
                   │  │     ├─ tools.file_io               │
                   │  │     ├─ tools.http_fetch            │
                   │  │     ├─ tools.automation/native      │
                   │  │     ├─ tools.photo (vision)        │
                   │  │     ├─ tools.touch (XXTouch)        │
                   │  │     ├─ tools.device                │
                   │  │     ├─ tools.facts                 │
                   │  │     ├─ tools.skills                │
                   │  │     ├─ tools.self_debug            │
                   │  │     ├─ tools.services/selftest      │
                   │  │     ├─ tools.ops_journal/status     │
                   │  │     ├─ tools.clipboard             │
                   │  │     └─ tools.apt                   │
                   │  └─ append + loop (configurable max)   │
                   └───────────────┬───────────────────────┘
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                ▼
         ┌────────────────┐ ┌─────────────┐ ┌────────────┐
         │ agent/memory   │ │ agent/facts │ │ OpenAI API │
         │ aiosqlite WAL  │ │ JSON store  │ │ gpt-4o     │
         └────────────────┘ └─────────────┘ └────────────┘
                                   ▲
                                   │
                        ┌──────────┴──────────┐
                        │ agent/heartbeat.py  │
                        │ asyncio bg task     │
                        └─────────────────────┘
```

All tool handlers are pure async, registered with a `@register({...})` decorator that simultaneously stores the OpenAI tool schema and the dispatch function. Adding a new tool is one decorator + one async function + one import line in `main.py`.

---

## Project structure

```
iAgent/
├── iagent.sh                       # The unified `iagent` command (tmux-backed)
├── main.py                         # Telegram bot entry point
├── chat.py                         # Local CLI REPL
├── setup.py                        # Interactive setup wizard
├── doctor.py                       # Read-only health check
├── capabilities.py                 # Capability registry
├── bootstrap.sh                    # On-device curl|sh installer
├── install.sh                      # The actual installer
├── requirements.txt                # All deps pinned for iOS pip-wheel reality
├── ROADMAP.md                      # Phase 1–4 status (all complete)
├── config/
│   ├── settings.py                 # Loads .env + config.json into typed Settings
│   └── config.json.example
├── agent/
│   ├── loop.py                     # OpenAI tool-calling loop (parallel dispatch)
│   ├── memory.py                   # SQLite + WAL conversation store + tool-history sanitizer
│   ├── facts.py                    # Persistent key/value memory
│   ├── heartbeat.py                # Asyncio background self-prompts
│   └── context.py                  # SOUL+system prompt + iOS-aware tool roster
├── tools/
│   ├── registry.py                 # @register decorator + async dispatch
│   ├── shell.py                    # asyncio subprocess (no fork)
│   ├── file_io.py                  # aiofiles, sandboxed
│   ├── http_fetch.py               # aiohttp GET/POST
│   ├── apt.py                      # apt_install / apt_search
│   ├── automation.py               # app launch / UI automation helpers
│   ├── native.py                   # native iOS data helpers where available
│   ├── mcp_bridge.py               # ios-mcp HTTP bridge notes/tools
│   ├── photo.py                    # photo helpers + GPT-4o vision
│   ├── touch.py                    # XXTouch screenshots / tap / swipe / type
│   ├── device.py                   # battery / screenshot / brightness
│   ├── clipboard.py                # pbcopy / pbpaste
│   ├── facts.py                    # remember/recall fact tools
│   ├── skills.py                   # list/view/write skill tools
│   ├── self_debug.py               # logs + source patch + restart
│   ├── shell_env.py                # iOS/rootless-safe shell env helpers
│   ├── services.py                 # runbook-backed service diagnostics/repair
│   ├── selftest.py                 # iAgent/Homebridge/XXTouch/ios-mcp checks
│   ├── ops_journal.py              # redacted operational event journal
│   └── status_cards.py             # Telegram-friendly status summaries
├── runbooks/
│   └── homebridge.json             # Homebridge tmux/runbook definition
├── scripts/
│   ├── regression_check.py         # ops-layer regression checks
│   └── selftest.py                 # CLI selftest wrapper
├── skills/                         # Markdown skill library
│   ├── battery.md
│   ├── disk_usage.md
│   ├── wifi_info.md
│   ├── uptime.md
│   ├── homebridge_ipad.md
│   ├── ipad_xxtouch_control.md
│   ├── ipad_native_data.md
│   ├── ios_mcp_notes.md
│   ├── exit_node_proxy.md
│   ├── iagent_self_management.md
│   ├── autonomous_troubleshooting.md
│   └── shortcuts_setup.md
├── bot/
│   ├── handlers.py                 # All / commands + message handler
│   └── middleware.py               # allowed_user_ids gate
└── utils/
    └── logger.py                   # Rotating file + stderr handlers
```

---

## Things we learned the hard way

### 1. Path & user

NewTerm 3 / `ssh mobile@<ip>` runs as `mobile`. `mobile` cannot write to `/var/jb/usr/local/lib/`. Put your code under `/var/jb/var/mobile/...` instead.

### 2. Python is 3.9.9

Procursus's `python3` is Python 3.9.9. Anything that says `requires-python >= 3.10` is a non-starter. The whole codebase is 3.9-compatible: `from __future__ import annotations`, `Union[X, Y]` instead of `X | Y`, no `match`, no `TaskGroup`.

### 3. Rust toolchain doesn't exist

`openai >= 1.32` (`jiter`), `pydantic >= 2.0` (`pydantic-core`), `tokenizers` — all need Rust. `puccinialin` raises `ValueError: Unknown macOS machine: iPad11,3`. **Fix pattern:** pin to last pre-Rust version. We pin `openai<1.32`, `pydantic<2`, `httpx<0.28`.

### 4. C compiler missing by default (PyYAML)

`SystemError: Cannot locate working compiler`. Either `apt install clang` (~100 MB) or use JSON. We use JSON.

### 5. `httpx 0.28` broke `openai 1.31`

`TypeError: __init__() got an unexpected keyword argument 'proxies'`. Pin `httpx<0.28`.

### 6. Wheel-tag matching on iOS

Pip downloads wheels tagged `macosx_10_9_universal2` because the platform matches and `universal2` covers arm64. If only `manylinux*` wheels exist, source builds happen.

### 7. iOS forbids `fork()`

`multiprocessing`, `subprocess.Popen`, `ProcessPoolExecutor` — all killed by the kernel. `posix_spawn` works. `asyncio.create_subprocess_exec` uses `posix_spawn` internally.

### 8. The pip "scheme" warnings

Procursus's site-packages layout doesn't match what `distutils`/`sysconfig` expect — wall of warnings, but install still works.

### 9. Telegram polling vs webhooks

Webhooks need an inbound TCP port. iOS networking is hostile to inbound. `Application.run_polling()` works fine.

### 10. SQLite WAL on a mobile device

Always `PRAGMA journal_mode=WAL`, otherwise concurrent coroutines deadlock the connection.

### 11. The bot must be Started once

Telegram refuses to deliver messages from a bot to a user who hasn't tapped Start in the bot's chat at least once.

### 12. iOS Jetsam reaps long-running processes

Background processes get killed under memory pressure. tmux-managed processes started by the `mobile` user get gentler treatment than system-domain LaunchDaemons.

### 13. LaunchDaemons do not work for this on iOS rootless ⚠️

Multiple plist configurations all got SIGKILLed by AMFI. Verdict: **iAgent uses tmux**.

### 14. tmux locale and socket on iOS

Two stacked failures the script handles for you:

- iOS locale DB has no `en_US.UTF-8`. tmux rejects the var → use `LC_CTYPE=UTF-8` only, with everything else unset.
- Dopamine's `/tmp` resolves to a 100+ char path under `/private/preboot/<hash>/...`, exceeding the Unix socket name limit. We use `-S $IAGENT_HOME/tmux.sock` for every tmux call.

### 15. Rust-built dependencies via pip on iOS

Pin everything. Our `requirements.txt` has the working set — don't upgrade past the pins without testing on-device.

### 16. Homebridge works best under tmux, not launchd

Homebridge and Config UI can run reliably on iOS, but use tmux sessions with explicit locale and short socket paths. Config UI X v5 may crash on Node 18/iOS; the known-good path is Config UI X v4.x plus iOS-safe plugin paths.

### 17. Missing Linux tools need graceful fallbacks

Do not assume `lsof`, `/bin/sh`, GNU coreutils, or normal Linux process layouts exist. The service layer falls back to `ps` candidates and runbook metadata where exact listener ownership is unavailable.

### 18. Tool-call history must be sanitized

OpenAI rejects orphaned `tool` messages. `agent/memory.py` filters invalid historical tool messages/tool calls before building context.

### 19. Shortcuts are not a universal automation backend on iOS

Manual Shortcuts can work, but there is no reliable universal `shortcuts` CLI on this iOS setup, and direct DB inserts are ignored by the runtime cache. Prefer XXTouch, direct files/SQLite, clipboard, ios-mcp HTTP, and runbook-backed services.

---

## Daily operations

| Task | Command |
|---|---|
| Status | `iagent status` or `/status` in Telegram |
| Stop | `iagent stop` |
| Start | `iagent` |
| Restart | `iagent restart` or `/restart` in Telegram |
| Live tail logs | `iagent logs` or `/logs` in Telegram |
| Update to latest | `cd ~/iAgent && git pull && sh install.sh` |
| Clear chat history | `/clear` |
| Foreground debug | `iagent fg` |
| Local CLI chat | `iagent chat` |
| Health check | `iagent doctor` |
| Ops selftest | `python3 scripts/selftest.py` or ask the agent to run `run_selftest` |
| Regression check | `python3 scripts/regression_check.py` |
| Status card | Ask: `show Steve/iAgent status card` |

---

## Troubleshooting

**First, run `iagent doctor`.** For runtime/integration issues, also run `python3 scripts/selftest.py` or ask the agent for a Steve/iAgent status card. The selftest covers runtime files, tool registry, Homebridge, XXTouch, ios-mcp, battery probe, and history sanitizer.

### Bot doesn't reply

1. `iagent status` — running? If not, `iagent`.
2. Have you tapped **Start** in the bot's Telegram chat?
3. Is your numeric Telegram user ID in `allowed_user_ids`?
4. Is the bot username you're messaging the one your token belongs to? `iagent fg` and look for `Bot: @<username>`.

### `iagent: command not found`

Open a new shell, or `source ~/.zshrc`. Verify with `ls -la /var/jb/var/mobile/iagent/iagent`.

### `tmux: invalid LC_ALL` or `need UTF-8 locale`

The `iagent` script handles this. If you're calling tmux directly, prefix:
```bash
unset LC_ALL LANG LC_CTYPE; LC_CTYPE=UTF-8 tmux ...
```

Or add to `~/.zshrc`:
```bash
tmux() { unset LC_ALL LANG LC_CTYPE LC_MESSAGES; LC_CTYPE=UTF-8 command tmux "$@"; }
alias it='tmux -S /var/jb/var/mobile/iagent/tmux.sock'
```

Then `it list-sessions`, `it attach`, `it kill-server`.

### `Cannot locate working compiler` while installing a dependency

Either replace the dep with something pure-Python, or `sudo apt install clang` (~100 MB).

### `Unknown macOS machine: iPad11,3` while installing a dependency

You're trying to install a Rust-built package. Pin to the last pre-Rust version.

### Homebridge or Config UI does not come up

Ask the agent to run `diagnose_service` or `repair_service` for `homebridge`. The runbook checks tmux panes, known ports, logs, locale problems, startup races, and known plugin/config states. Avoid broad `kill` commands; use the targeted plan from `inspect_service_listeners`/`repair_service`.

### Agent gives OpenAI tool-history errors

Clear history with `/clear` first. The current memory loader sanitizes orphaned tool messages, but very old databases may still contain invalid history rows from older builds.

### Shortcuts tools do not work

This is expected on many iOS/rootless setups. The repo documents Shortcuts caveats, but the preferred paths are XXTouch, direct file/SQLite access, clipboard tools, ios-mcp HTTP, and service runbooks.

### Telegram `/` menu doesn't show commands

Tap **Start** once in the bot's chat. Run `iagent restart`. The `set_my_commands` call fires on startup and is logged — check `iagent logs` for `Registered N bot commands with Telegram`.

---

## License

MIT. See [LICENSE](LICENSE).

---

## Acknowledgements

- [openclaw](https://github.com/openclaw/openclaw) — multi-channel personal-agent idea
- [hermes-agent](https://github.com/NousResearch/hermes-agent) — agentic tool-calling loop architecture
- [Dopamine](https://ellekit.space/dopamine/) — making any of this possible on a stock iPad
- [Procursus](https://github.com/ProcursusTeam/Procursus) — sane-enough Unix userland for iOS
- tmux — the only thing iOS lets you actually keep alive
