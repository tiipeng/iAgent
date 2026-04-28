# iAgent

Personal AI agent that runs **natively on a jailbroken iPad** — Telegram bot + local CLI, powered by **OpenAI GPT-4o** with tool calling. The agent can run shell commands, read/write files, and fetch URLs directly on the device. No cloud, no Docker, no relay server.

Inspired by [openclaw](https://github.com/openclaw/openclaw) and [hermes-agent](https://github.com/NousResearch/hermes-agent), but built specifically for the constraints of rootless Dopamine on iOS 15–16.

---

## Why this exists

Both `openclaw` and `hermes-agent` failed to install on a jailbroken iPad:

- **openclaw** — its installer demands Homebrew, which on iOS thinks the user must be in the macOS `admin` group. Dead end.
- **hermes-agent** — `pyproject.toml` declares `requires-python >= 3.11`, but Procursus ships only Python 3.9.9. Even with `--no-deps`, transitive deps like `jiter` and `tokenizers` need a Rust toolchain that doesn't recognise the iPad's machine triple (`iPad11,3`).

iAgent is the same idea, rebuilt around what actually works on the device:

| Constraint | iAgent's answer |
|---|---|
| Python 3.9.9 (Procursus default) | All code is Python 3.9-compatible (`from __future__ import annotations` + `typing.Optional`/`Union`) |
| No Rust toolchain | Pin `openai<1.32` (no `jiter`) and `pydantic<2` (no `pydantic-core`) — both pure-Python paths |
| No C compiler by default | Avoid PyYAML — config is JSON (stdlib) |
| iOS forbids `fork()` | All subprocesses use `asyncio.create_subprocess_exec` (= `posix_spawn`) |
| `mobile` user can't write to `/var/jb/usr/local/lib/` | Code lives at `/var/jb/var/mobile/iagent/code/`, daemon plist install is the only sudo step |
| Procursus venv quirk drops `proxies` from httpx | Pin `httpx<0.28` (compat with openai 1.31) |

If anything else in the Python ecosystem decides to require Rust, the fix pattern is the same: pin to the last pre-Rust release.

---

## Requirements

**Hardware / OS**
- iPad or iPhone, **arm64e**, jailbroken with **Dopamine** (iOS 15.0–16.5.1, rootless)

**Sileo packages** (install from the default Procursus repo)
- `python3` (3.9.9 — bundled with Dopamine)
- `git`, `curl`, `ca-certificates` — usually present
- `openssh` — recommended for editing `.env` and `config.json` from a Mac
- `sudo` — needed once to install the LaunchDaemon

**Accounts you need**
- A [Telegram bot token](https://t.me/BotFather) (chat with `@BotFather` → `/newbot`)
- Your Telegram numeric user ID — message `@userinfobot` to get it
- An [OpenAI API key](https://platform.openai.com/api-keys)

---

## Install — one command

Open a terminal on the iPad (NewTerm 3, or SSH from your Mac with `ssh mobile@<iPad-IP>`) and run:

```bash
curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh
```

That clones the repo to `/tmp/iagent_src`, runs `install.sh`, which:

1. Detects the highest available `python3.x` (≥ 3.9)
2. Creates a virtualenv at `/var/jb/var/mobile/iagent/venv`
3. Installs all dependencies from prebuilt wheels
4. Copies the application to `/var/jb/var/mobile/iagent/code/`
5. Renders the LaunchDaemon plist
6. Prints the **four sudo commands** you run next to load the daemon

Then add your secrets:

```bash
nano /var/jb/var/mobile/iagent/.env
```

```env
TELEGRAM_TOKEN=7891234567:AAH...your-bot-token...
OPENAI_API_KEY=sk-proj-...
```

```bash
nano /var/jb/var/mobile/iagent/config.json
```

```json
{
  "openai_model": "gpt-4o",
  "allowed_user_ids": [123456789],   // ← your Telegram user ID
  "history_window": 20,
  "max_iterations": 10,
  "shell_timeout": 30,
  "shell_allowlist": null
}
```

Then load the daemon (root, one time):

```bash
sudo cp /var/jb/var/mobile/iagent/com.tiipeng.iagent.plist /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist
sudo chown root:wheel /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist
sudo chmod 644 /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist
sudo launchctl load /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist
```

Verify:

```bash
launchctl list | grep iagent
# expect:  <PID>   0   com.tiipeng.iagent
```

Search for your bot's `@username` in Telegram, tap **Start** once, send a message. The agent replies.

---

## Two ways to chat

### Telegram (production)

The LaunchDaemon keeps `main.py` alive across crashes and reboots. `KeepAlive=true`, `ThrottleInterval=10` (no restart storms). All conversations are persisted in SQLite.

### CLI REPL (debugging)

Telegram is awkward when something is broken — the daemon writes to a log file and you can't see what's happening live. `chat.py` reuses the **exact same** OpenAI client, memory, tools, and agent loop, but reads from stdin / prints to stdout:

```bash
IAGENT_HOME=/var/jb/var/mobile/iagent /var/jb/var/mobile/iagent/venv/bin/python /var/jb/var/mobile/iagent/code/chat.py
```

```
────────────────────────────────────────────────────────────
 iAgent CLI — model: gpt-4o
 Commands: /clear  reset history   |   /quit  exit
────────────────────────────────────────────────────────────
you> what kernel am i running? use the shell tool
agent> Darwin iPad-von-Tuan-Anh 23.x.0 ...
```

The CLI uses `chat_id = -1` in SQLite so its history stays separate from Telegram conversations. Same tools, same model, same memory store.

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
                   │  │     └─ tools.http_fetch            │
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

### Agent loop in 10 lines

```python
messages = [system] + history(last_N) + [user]
for _ in range(max_iterations):
    rsp = await openai.chat.completions.create(messages, tools=schemas)
    if rsp.finish_reason == "stop":
        return rsp.message.content
    # tool_calls — dispatch in parallel, append results, loop
    results = await asyncio.gather(*[dispatch(tc) for tc in rsp.message.tool_calls])
    messages.append(rsp.message)
    messages += [{"role": "tool", "tool_call_id": tc.id, "content": r} for tc, r in ...]
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

All tool handlers are pure async, registered with a `@register({"name": ..., "parameters": ...})` decorator that simultaneously stores both the OpenAI tool schema and the dispatch function. Adding a new tool is one decorator + one async function.

---

## Configuration reference

### `.env` (secrets — never commit)

| Key | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | From @BotFather |
| `OPENAI_API_KEY` | From platform.openai.com |

### `config.json` (settings)

| Key | Default | Purpose |
|---|---|---|
| `openai_model` | `gpt-4o` | Any model your key has access to |
| `allowed_user_ids` | `[]` (open) | Telegram numeric IDs allowed to talk to the bot. **Keep this set on a personal device** — without it, anyone who finds the bot username can run shell commands on your iPad |
| `history_window` | `20` | Messages kept in context per chat |
| `max_iterations` | `10` | Max tool-call rounds per user message |
| `shell_timeout` | `30` | Seconds before a shell command is killed |
| `shell_allowlist` | `null` | If set, only these commands may run via the `shell` tool |

---

## Project structure

```
iAgent/
├── main.py                       # Telegram bot entry point (LaunchDaemon target)
├── chat.py                       # Local CLI REPL — same agent, no Telegram
├── bootstrap.sh                  # On-device curl|sh installer
├── install.sh                    # The actual installer (called by bootstrap)
├── com.tiipeng.iagent.plist      # LaunchDaemon definition (KeepAlive, sudo install)
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
│   └── http_fetch.py             # aiohttp GET/POST
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
- LaunchDaemons live at `/var/jb/Library/LaunchDaemons/` (rootless), not `/Library/LaunchDaemons/`. Their plist must be owned `root:wheel` mode `644`, and `launchctl load` requires root — that's the only sudo step in the install.

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

…because `iPad11,3` isn't in its target-triple table.

**Fix pattern:** pin to the last release before Rust became a hard dep.
- `openai>=1.30,<1.32` (last pre-jiter)
- `pydantic>=1.10,<2` (pydantic v1 is pure Python; openai 1.31 still supports both via a compat shim)
- avoid `anthropic` and `tokenizers` entirely

### 4. C compiler missing by default (PyYAML)

PyYAML ships its `_yaml` C extension as an optional accelerator. When pip can't find a wheel matching `cpython-39-darwin / iPad11,3`, it falls back to source and tries to build the C extension. Procursus does **not** ship a C compiler by default, so you get:

```
SystemError: Cannot locate working compiler
```

You can `apt install clang` (in Sileo: search "clang"), but that requires root and adds 100MB+. The simpler fix: **don't use PyYAML** — JSON is in the stdlib. iAgent's config is JSON.

### 5. `httpx 0.28` broke `openai 1.31`

`httpx` 0.28 dropped the deprecated `proxies` kwarg, but `openai 1.31`'s `AsyncHttpxClientWrapper` still passes it. Result:

```
TypeError: __init__() got an unexpected keyword argument 'proxies'
```

Pin `httpx>=0.25,<0.28`. The 0.27.x series is the last one that accepts the old signature.

### 6. Wheel-tag matching on iOS

iOS reports its platform as `darwin` with machine `iPad11,3` (or similar). Pip happily downloads wheels tagged `macosx_10_9_universal2` because the macOS portion matches and `universal2` covers arm64. Wheels tagged `macosx_11_0_arm64` also work. Anything with a model-specific tag won't match — but in practice, the universal2 wheels exist for `aiohttp`, `multidict`, `frozenlist`, `yarl`, `propcache` and that's enough.

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

Telegram refuses to deliver messages from a bot to a user who hasn't opened the bot's chat at least once. If the daemon is healthy but you see no messages: open the bot in Telegram and tap **Start**. The bot will then receive your messages going forward.

### 12. iOS Jetsam

Background processes get killed under memory pressure. `KeepAlive=true` in the LaunchDaemon plist auto-restarts within 10 seconds. SQLite's WAL mode means no history is lost across restarts.

---

## Daily operations

| Task | Command |
|---|---|
| Status | `launchctl list \| grep iagent` |
| Stop daemon | `sudo launchctl unload /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist` |
| Start daemon | `sudo launchctl load /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist` |
| Live tail logs | `tail -f /var/jb/var/mobile/iagent/logs/stderr.log` |
| Update to latest | re-run the bootstrap one-liner — it pulls the repo, reinstalls deps, redeploys code |
| Clear chat history | inside Telegram or CLI, send `/clear` |
| Run agent in foreground (for debugging) | `IAGENT_HOME=/var/jb/var/mobile/iagent /var/jb/var/mobile/iagent/venv/bin/python /var/jb/var/mobile/iagent/code/main.py` |
| Local CLI chat | `IAGENT_HOME=/var/jb/var/mobile/iagent /var/jb/var/mobile/iagent/venv/bin/python /var/jb/var/mobile/iagent/code/chat.py` |

---

## Troubleshooting

### `launchctl list` shows `-  -9  com.tiipeng.iagent`

The daemon is being killed (signal 9) immediately on startup. `KeepAlive` keeps trying to restart, eventually `ThrottleInterval` slows it down. Causes, in order of likelihood:

1. `.env` missing or `TELEGRAM_TOKEN` blank → `RuntimeError: TELEGRAM_TOKEN is not set`
2. `OPENAI_API_KEY` blank or wrong → `openai.AuthenticationError 401`
3. Wrong path in plist → `FileNotFoundError`

**Diagnose by running in foreground:**

```bash
sudo launchctl unload /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist
IAGENT_HOME=/var/jb/var/mobile/iagent /var/jb/var/mobile/iagent/venv/bin/python /var/jb/var/mobile/iagent/code/main.py
```

You'll see the real error in the terminal. Fix it, then `sudo launchctl load ...` again.

### Bot doesn't reply but daemon is healthy

1. Have you tapped **Start** in the bot's Telegram chat? Bots can't message users until the user has initiated.
2. Is your numeric Telegram user ID in `allowed_user_ids`? The bot silently drops unauthorised messages — check the log for `Blocked message from user ...`.
3. Is the bot username you're messaging the one your token belongs to? When `main.py` boots it logs `iAgent started. Bot: @<username>` — that's the only correct one.

### `ModuleNotFoundError` after install

You're probably running `python3` (Procursus user-site) instead of the venv. Use the absolute venv path:

```bash
/var/jb/var/mobile/iagent/venv/bin/python ...
```

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
