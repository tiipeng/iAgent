# iAgent

Personal AI agent that runs **natively on a jailbroken iPad** — Telegram bot + local CLI, powered by **OpenAI GPT-4o** with tool calling. The agent can run shell commands, read/write files, and fetch URLs directly on the device. No cloud, no Docker, no relay server.

Inspired by [openclaw](https://github.com/openclaw/openclaw) and [hermes-agent](https://github.com/NousResearch/hermes-agent), but built specifically for the constraints of rootless Dopamine on iOS 15–16.

---

## Why this exists

Both `openclaw` and `hermes-agent` failed to install on a jailbroken iPad:

- **openclaw** — its installer demands Homebrew, which on iOS thinks the user must be in the macOS `admin` group. Dead end.
- **hermes-agent** — `pyproject.toml` declares `requires-python >= 3.11`, but Procursus ships only Python 3.9.9. Even with `--no-deps`, transitive deps like `jiter` and `tokenizers` need a Rust toolchain that doesn't recognise the iPad's machine triple (`iPad11,3`).

iAgent is the same idea, rebuilt around what actually works on the device.

---

## Requirements

**Hardware / OS**
- iPad or iPhone, **arm64e**, jailbroken with **Dopamine** (iOS 15.0–16.5.1, rootless)

**Sileo packages** (install from the default Procursus repo)
- `python3` (3.9.9 — bundled with Dopamine)
- `tmux` ← required for `iagent` to keep the bot alive in a session
- `git`, `curl`, `ca-certificates` — usually present
- `openssh` — recommended for editing config from a Mac

**Accounts you need**
- A [Telegram bot token](https://t.me/BotFather) (chat with `@BotFather` → `/newbot`)
- Your Telegram numeric user ID — message `@userinfobot` to get it
- An [OpenAI API key](https://platform.openai.com/api-keys)

---

## Install — one command

Open a terminal on the iPad (NewTerm 3, or SSH from your Mac with `ssh mobile@<iPad-IP>`) and run:

```bash
sudo apt install tmux       # one-time, if you haven't installed tmux before
curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh
```

The bootstrap clones the repo, sets up a virtualenv, installs every dependency from prebuilt wheels, then **launches an interactive setup wizard** that walks you through:

1. Telegram bot token (validated against `getMe` before saving)
2. OpenAI API key (validated against `/v1/models` before saving)
3. Your numeric Telegram user ID
4. Optional `SOUL.md` personality file
5. Heartbeat interval (saved for when Phase 2.2 ships)

After it finishes, **open a new shell** (or `source ~/.zshrc`), and:

```bash
iagent              # start the bot in a tmux session
```

That's it. The bot runs in the background until you stop it or the iPad reboots. Search for your bot's `@username` in Telegram, tap **Start** once, send a message.

---

## The `iagent` command — daily driver

`iagent` is the single entry point for everything:

| Command | What it does |
|---|---|
| `iagent` (or `iagent start`) | Start the bot in a tmux session named `iagent`. If already running, prints status. |
| `iagent attach` | Attach to the running tmux session. **Detach again with `Ctrl+B` then `D`** (don't `Ctrl+C` — that kills the bot). |
| `iagent stop` | Kill the tmux session. |
| `iagent restart` | Stop + start. |
| `iagent status` | Print whether the bot is running. |
| `iagent logs` | Tail the log files (`Ctrl+C` to exit). |
| `iagent fg` | Run the bot in the foreground in this shell. Useful for debugging — you see the traceback live. |
| `iagent chat` | Open the local CLI REPL (offline from Telegram, separate from the bot). |
| `iagent setup` | Re-run the interactive setup wizard. |
| `iagent doctor` | Run the health check. |
| `iagent help` | Full help. |

**The bot survives** SSH disconnect, terminal close, and login session changes. It dies on iPad reboot or under heavy memory pressure (rare). After a reboot, just SSH back in and run `iagent`.

> **Why no LaunchDaemon?** I tried. Multiple times. iOS aggressively SIGKILLs system-domain LaunchDaemons that touch the network — even on jailbreak. tmux is what every other persistent-process project on jailbroken iOS actually uses. See "Things we learned the hard way" → 13 below.

---

## Two ways to chat

### Telegram (production)

Once `iagent` is running, message your bot. Conversations are persisted to SQLite and survive restarts.

### CLI REPL (debugging)

Telegram is awkward when something is broken — the bot writes to a log file and you can't see what's happening live. `iagent chat` opens a local REPL that reuses the **exact same** OpenAI client, memory, tools, and agent loop, but reads from stdin / prints to stdout:

```
────────────────────────────────────────────────────────────
 iAgent CLI — model: gpt-4o
 Commands: /clear  reset history   |   /quit  exit
────────────────────────────────────────────────────────────
you> what kernel am i running? use the shell tool
agent> Darwin iPad-von-Tuan-Anh 23.x.0 ...
```

The CLI uses `chat_id = -1` in SQLite so its history stays separate from Telegram conversations.

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
                   │  ┌─ build messages (system+history)   │
                   │  ├─ openai.chat.completions.create    │
                   │  ├─ if tool_calls → asyncio.gather    │
                   │  │     ├─ tools.shell                 │
                   │  │     ├─ tools.file_io               │
                   │  │     ├─ tools.http_fetch            │
                   │  │     └─ tools.apt (opt-in)          │
                   │  └─ append + loop (max 10 iterations) │
                   └───────────────┬───────────────────────┘
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                ▼
          ┌───────────────┐ ┌─────────────┐ ┌────────────┐
          │ agent/memory  │ │ tools/regis │ │ OpenAI API │
          │ aiosqlite WAL │ │ try (deco)  │ │ gpt-4o     │
          └───────────────┘ └─────────────┘ └────────────┘
```

### Available tools

| Tool | What it does |
|---|---|
| `shell` | Run a shell command (`asyncio.create_subprocess_exec`, configurable timeout, optional allowlist) |
| `read_file` | Read a text file from the workspace |
| `write_file` | Write text to a file in the workspace (sandboxed to `workspace_root`) |
| `list_files` | List a directory inside the workspace |
| `http_get` | Fetch a URL via HTTP GET (truncates response at 50KB) |
| `http_post` | POST a JSON body to a URL |
| `apt_search` | Search the Procursus repo for available Sileo packages |
| `apt_install` | Install a Sileo package — **opt-in**, requires `apt_install_enabled: true` AND the package name in `apt_install_allowlist` in `config.json` |

All tool handlers are pure async, registered with a `@register({...})` decorator that simultaneously stores both the OpenAI tool schema and the dispatch function. Adding a new tool is one decorator + one async function.

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
| `allowed_user_ids` | `[]` (open) | Telegram numeric IDs allowed to talk to the bot. **Keep this set on a personal device** — without it, anyone who finds the bot username can run shell commands on your iPad |
| `history_window` | `20` | Messages kept in context per chat |
| `max_iterations` | `10` | Max tool-call rounds per user message |
| `shell_timeout` | `30` | Seconds before a shell command is killed |
| `shell_allowlist` | `null` | If set, only these commands may run via the `shell` tool |
| `apt_install_enabled` | `false` | Master switch for the `apt_install` tool |
| `apt_install_allowlist` | `[]` | Package names the agent is permitted to install (e.g. `["pbcopy", "ca-certificates"]`) |
| `heartbeat_interval` | `0` | Seconds between heartbeat self-prompts. `0` disables. Wired through; activated when Phase 2.2 ships |

---

## Project structure

```
iAgent/
├── iagent.sh                     # The unified `iagent` command (tmux-backed)
├── main.py                       # Telegram bot entry point (run by `iagent`)
├── chat.py                       # Local CLI REPL (run by `iagent chat`)
├── setup.py                      # Interactive setup wizard (run by `iagent setup`)
├── doctor.py                     # Read-only health check (run by `iagent doctor`)
├── capabilities.py               # Capability registry — installed packages, shortcuts
├── bootstrap.sh                  # On-device curl|sh installer
├── install.sh                    # The actual installer (called by bootstrap)
├── requirements.txt              # All deps pinned for iOS pip-wheel reality
├── config/
│   ├── settings.py               # Loads .env + config.json into typed Settings
│   └── config.json.example
├── agent/
│   ├── loop.py                   # OpenAI tool-calling loop (parallel dispatch)
│   ├── memory.py                 # SQLite + WAL conversation store
│   └── context.py                # Per-chat state + iOS-aware system prompt
├── tools/
│   ├── registry.py               # @register decorator + async dispatch
│   ├── shell.py                  # asyncio subprocess (no fork)
│   ├── file_io.py                # aiofiles, sandboxed to workspace_root
│   ├── http_fetch.py             # aiohttp GET/POST
│   └── apt.py                    # apt_install / apt_search (opt-in)
├── bot/
│   ├── handlers.py               # /start, /clear, MessageHandler
│   └── middleware.py             # allowed_user_ids gate
└── utils/
    └── logger.py                 # Rotating file + stderr handlers
```

---

## Things we learned the hard way

This section documents every dead end, in case you're trying to run a Python project on rootless Dopamine and hit the same walls.

### 1. Path & user

- NewTerm 3 / `ssh mobile@<ip>` runs as `mobile` — **not root**.
- `mobile` cannot write to `/var/jb/usr/local/lib/`. Put your code under `/var/jb/var/mobile/...` instead.

### 2. Python is 3.9.9

Procursus's `python3` package is Python 3.9.9. There's no newer Python in Sileo (as of April 2026). Anything that says `requires-python >= 3.10` is a non-starter unless you patch its `pyproject.toml`, and even then transitive deps usually break.

The whole codebase is therefore 3.9-compatible:
- `from __future__ import annotations` everywhere → string-form type hints
- `typing.Optional` / `typing.Union` instead of `X | Y`
- No PEP 604 unions, no `match`, no `TaskGroup`

### 3. Rust toolchain doesn't exist

Many modern Python packages now ship a Rust crate as a build dep:
- `openai >= 1.32` pulls in `jiter` (Rust JSON parser)
- `pydantic >= 2.0` pulls in `pydantic-core` (Rust)
- `tokenizers` (used by `anthropic`) is fully Rust

When pip tries to compile from source, `maturin` invokes `puccinialin` to install a Rust toolchain — and `puccinialin` raises:

```
ValueError: Unknown macOS machine: iPad11,3
```

**Fix pattern:** pin to the last release before Rust became a hard dep.
- `openai>=1.30,<1.32` (last pre-jiter)
- `pydantic>=1.10,<2` (pydantic v1 is pure Python; openai 1.31 still supports both via a compat shim)
- avoid `anthropic` and `tokenizers` entirely

### 4. C compiler missing by default (PyYAML)

PyYAML ships its `_yaml` C extension as an optional accelerator. When pip can't find a wheel matching `cpython-39-darwin / iPad11,3`, it falls back to source and tries to build the C extension. Procursus does **not** ship a C compiler by default, so you get:

```
SystemError: Cannot locate working compiler
```

You can `apt install clang` (in Sileo: search "clang"), but that requires root and adds 100MB+. Simpler: **don't use PyYAML** — JSON is in the stdlib. iAgent's config is JSON.

### 5. `httpx 0.28` broke `openai 1.31`

`httpx` 0.28 dropped the deprecated `proxies` kwarg, but `openai 1.31`'s `AsyncHttpxClientWrapper` still passes it. Result:

```
TypeError: __init__() got an unexpected keyword argument 'proxies'
```

Pin `httpx>=0.25,<0.28`. The 0.27.x series is the last one that accepts the old signature.

### 6. Wheel-tag matching on iOS

iOS reports its platform as `darwin` with machine `iPad11,3`. Pip happily downloads wheels tagged `macosx_10_9_universal2` because the macOS portion matches and `universal2` covers arm64. Wheels tagged `macosx_11_0_arm64` also work. Anything with a model-specific tag won't match — but in practice, the universal2 wheels exist for `aiohttp`, `multidict`, `frozenlist`, `yarl`, `propcache` and that's enough.

If a package only ships `manylinux*` wheels (no `macosx`), you're stuck with source builds.

### 7. iOS forbids `fork()`

Anything that does `os.fork()` directly gets killed by the kernel:
- `multiprocessing.Process` ❌
- `subprocess.Popen` (uses fork on POSIX) ❌
- `concurrent.futures.ProcessPoolExecutor` ❌

The kernel **does** allow `posix_spawn`. Python's `asyncio.create_subprocess_exec` uses `posix_spawn` internally, so all shell tool calls go through that. iAgent's `tools/shell.py` is intentionally written to never touch a fork-based API.

### 8. The pip "scheme" warnings

Procursus's site-packages layout doesn't match what `distutils` and `sysconfig` agree on, so every pip invocation prints a wall of "Value for X does not match" warnings. They're noise — install actually works. Don't try to fix them.

### 9. Telegram polling vs webhooks

Webhooks need an inbound TCP port. iOS networking is hostile to inbound (NAT, sleep, no public IP). Use `Application.run_polling()` — Telegram's bot server pushes updates to an outbound long-poll, which works fine from any iPad on any WiFi.

### 10. SQLite WAL on a mobile device

Always `PRAGMA journal_mode=WAL` for any SQLite file the agent writes, otherwise concurrent coroutines (e.g. handler + history pruning) deadlock the connection.

### 11. The bot must be `Start`ed once

Telegram refuses to deliver messages from a bot to a user who hasn't opened the bot's chat at least once. If everything looks healthy but you see no messages: open the bot in Telegram and tap **Start**.

### 12. iOS Jetsam reaps long-running processes

Background processes get killed under memory pressure. There's no way around this — but a tmux-managed process (started from a real shell session as the `mobile` user) gets gentler treatment than a system-domain LaunchDaemon, and `main.py` is lean enough that Jetsam rarely fires.

### 13. **LaunchDaemons do not work for this on iOS rootless** ⚠️

This was the biggest dead end. We tried multiple plist configurations and every one of them got the daemon SIGKILLed:

| What we tried | What iOS did |
|---|---|
| `python main.py` directly as `ProgramArguments` | runs briefly, killed `-9` by AMFI when it touches the network |
| Same with `KeepAlive=true` and `ThrottleInterval=10` | restart loop until launchd permanently abandons the service |
| `UserName=mobile` to run as user instead of root | rejected with exit `78` (`EX_CONFIG`) — system-domain plists must run as root |
| `tick.py` single-shot model with `StartInterval=30` | still SIGKILLed each invocation |
| Wrapper shell script that does `sudo -u mobile python …` | rejected `78` when shebang was `/var/jb/bin/sh`; with `/bin/sh` invoked explicitly the wrapper ran but got SIGKILLed anyway |

The same scripts work **flawlessly** when launched manually from a NewTerm/SSH session as the `mobile` user. The kernel/AMFI sandbox treats system-domain root-launched processes differently from user-launched ones, even on a jailbreak.

**Verdict:** iAgent uses **tmux** instead. The `iagent` command spawns a tmux session running `main.py`, the bot lives there indefinitely, and you reattach with `iagent attach` whenever you want to see what it's doing. This is how every other persistent-process project on jailbroken iOS actually ships.

If you reboot the iPad, after the Dopamine re-jailbreak, just SSH in and run `iagent` again. Optionally add a one-line entry to your shell rc that auto-starts it on login.

---

## Daily operations

| Task | Command |
|---|---|
| Status | `iagent status` |
| Stop | `iagent stop` |
| Start | `iagent` |
| Live tail logs | `iagent logs` |
| Update to latest | `curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh \| sh` |
| Clear chat history | inside Telegram or CLI, send `/clear` |
| Foreground debug | `iagent fg` (see exceptions live) |
| Local CLI chat | `iagent chat` |

---

## Troubleshooting

**First, run `iagent doctor`.** It does most of the work for you:

```
✓ python: Python 3.9.9 at /var/jb/usr/bin/python3.9
✓ venv: 27 packages installed
✓ env: TELEGRAM_TOKEN + OPENAI_API_KEY present
✓ config: allowed_user_ids has 1 entry
✓ telegram: verified — bot @your_iagent_bot
✓ openai: verified
✓ bot: running in tmux session 'iagent' (pid=…)
✓ logs: iagent.log last modified 12s ago
✓ disk: 6087 MB free on /var/jb
✓ ca-certificates: /var/jb/etc/ssl/cert.pem
```

Then, if needed:

### Bot doesn't reply

1. Run `iagent status`. If "stopped", run `iagent`.
2. Have you tapped **Start** in the bot's Telegram chat? Bots can't message users until the user has initiated.
3. Is your numeric Telegram user ID in `allowed_user_ids`? `iagent doctor` checks; the bot silently drops unauthorised messages.
4. Is the bot username you're messaging the one your token belongs to? Run `iagent fg` and look for the `Bot: @<username>` line.

### `iagent: command not found`

Open a new shell (the install added it to `~/.zshrc` PATH). Or:

```bash
source ~/.zshrc
```

If still not found:

```bash
ls -la /var/jb/var/mobile/iagent/iagent  # should exist and be executable
echo $PATH | tr ':' '\n' | grep iagent   # should show /var/jb/var/mobile/iagent
```

### `tmux: need UTF-8 locale`

The `iagent` script sets `LC_ALL=en_US.UTF-8` automatically. If you still see this in some subshell, just `export LC_ALL=en_US.UTF-8` before retrying.

### `Cannot locate working compiler` while installing a dependency

You're trying to install something that needs to compile a C extension. Two options:
- Replace the dep with something pure-Python (best — what we did with PyYAML)
- `sudo apt install clang` via Sileo — adds ~100MB but enables every C-extension package

### `Unknown macOS machine: iPad11,3` while installing a dependency

You're trying to install a Rust-built package. Pin to the last pre-Rust version of the parent package, or replace it. See "Things we learned the hard way" → 3.

---

## License

MIT. See [LICENSE](LICENSE) (or just consider the code yours to play with — it's a personal-device tool).

---

## Acknowledgements

- [openclaw](https://github.com/openclaw/openclaw) — for the multi-channel personal-agent idea
- [hermes-agent](https://github.com/NousResearch/hermes-agent) — for the agentic tool-calling loop architecture
- [Dopamine](https://ellekit.space/dopamine/) — for making any of this possible on a stock iPad
- [Procursus](https://github.com/ProcursusTeam/Procursus) — for shipping a sane-enough Unix userland
- tmux — for being the only thing iOS lets you actually keep alive
