# iAgent

Personal AI agent for jailbroken iOS (Dopamine, arm64e). Runs as a **Telegram bot** on your device, using **OpenAI GPT-4o with tool calling** to execute shell commands, read/write files, and fetch URLs — all locally on your iPad.

Inspired by [openclaw](https://github.com/openclaw/openclaw) and [hermes-agent](https://github.com/NousResearch/hermes-agent).

---

## Requirements

- Jailbroken iPad/iPhone — Dopamine (iOS 15–16.5.1, arm64e, rootless)
- **Python 3.9+** — already shipped by Procursus as `python3` (3.9.9)
- `ca-certificates` via Sileo
- A [Telegram bot token](https://t.me/BotFather)
- An [OpenAI API key](https://platform.openai.com/api-keys)

> **Note on Python version:** Procursus's default `python3` package is Python 3.9.9.
> iAgent is written to work on 3.9+. If Sileo offers a newer `python3.10/3.11/3.12`
> package later, the installer will pick the highest available automatically.

---

## Quick Start (Mac / Linux development)

```bash
git clone https://github.com/tiipeng/iAgent.git
cd iAgent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in TELEGRAM_TOKEN and OPENAI_API_KEY
python main.py
```

---

## Deploy on the iPad (one-liner)

Open a terminal on the iPad (NewTerm 3 or SSH in). Make sure `git`, `curl`, and `python3` are installed via Sileo, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh
```

This clones the repo to `/tmp/iagent_src` and runs `install.sh`, which:

1. Detects the highest available `python3.x` (≥ 3.9)
2. Creates a venv at `/var/jb/var/mobile/iagent/venv`
3. Installs the Python dependencies
4. Copies the application code to `/var/jb/usr/local/lib/iagent/`
5. Installs the LaunchDaemon plist and starts it

After the installer finishes, edit your secrets and restart the daemon:

```bash
nano /var/jb/var/mobile/iagent/.env          # TELEGRAM_TOKEN, OPENAI_API_KEY
nano /var/jb/var/mobile/iagent/config.yaml   # allowed_user_ids

launchctl unload /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist
launchctl load   /var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist

tail -f /var/jb/var/mobile/iagent/logs/stderr.log
```

### Alternative: SCP from another machine

```bash
scp -r iAgent/ root@<iPad-IP>:/tmp/iagent_src
ssh root@<iPad-IP> sh /tmp/iagent_src/install.sh
```

---

## Configuration

Copy `config/config.yaml.example` to `~/.iagent/config.yaml` (or `$IAGENT_HOME/config.yaml`) and edit:

| Key | Default | Description |
|---|---|---|
| `allowed_user_ids` | `[]` (open) | Telegram user IDs allowed to use the bot |
| `openai_model` | `gpt-4o` | Model to use |
| `history_window` | `20` | Messages kept in context per chat |
| `shell_timeout` | `30` | Seconds before a shell command is killed |
| `shell_allowlist` | `null` | If set, only listed commands are allowed |

---

## Available Tools

| Tool | Description |
|---|---|
| `shell` | Run a shell command on the device |
| `read_file` | Read a file from the workspace |
| `write_file` | Write text to a file in the workspace |
| `list_files` | List files in a workspace directory |
| `http_get` | Fetch a URL |
| `http_post` | Send an HTTP POST request |

---

## Project Structure

```
iAgent/
├── main.py              # Entry point
├── config/
│   ├── settings.py      # Config loader
│   └── config.yaml.example
├── agent/
│   ├── loop.py          # OpenAI tool-calling loop
│   ├── memory.py        # SQLite conversation history
│   └── context.py       # Per-chat state
├── tools/
│   ├── registry.py      # Tool registration
│   ├── shell.py         # Shell execution
│   ├── file_io.py       # File read/write
│   └── http_fetch.py    # HTTP requests
├── bot/
│   ├── handlers.py      # Telegram handlers
│   └── middleware.py    # User allowlist
├── utils/
│   └── logger.py        # Rotating file logger
├── com.tiipeng.iagent.plist   # iOS LaunchDaemon
└── install.sh           # One-shot iOS installer
```

---

## License

MIT
