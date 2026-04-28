# iAgent — Roadmap

Planned features, ordered by what unlocks the most value per implementation effort. Each item lists files to touch, scope, and known blockers so future-me (or a contributor) can pick one up cold.

**Status legend:** ⬜ planned · 🚧 in progress · ✅ shipped

---

## Phase 1 — Setup wizard & Sileo gateway

### 1.1 `iagent setup` — interactive setup wizard ✅

5-step wizard: validates Telegram token + OpenAI key via HTTP before saving, persists `.env` + `config.json`, offers to open `SOUL.md` in editor.

### 1.2 `iagent doctor` — diagnose common issues ✅

10 health checks (Python, venv, .env, config, Telegram token, OpenAI key, tmux session, logs, disk, ca-certificates). Populates capability registry as a side effect.

### 1.3 `apt_install` tool ✅

`apt_install(package, reason)` and `apt_search(query)`. Allowlist-only in v1 (`apt_install_enabled` + `apt_install_allowlist` in `config.json`). Anything not on the list is refused with instructions to add it.

### 1.4 Capability registry ✅

`capabilities.py` + `$IAGENT_HOME/capabilities.json`. Records which Sileo packages and Shortcuts are available. Refreshed by `iagent doctor`.

---

## Phase 2 — Make the agent feel persistent ✅

### 2.1 SOUL.md — personality / standing instructions ✅

`$IAGENT_HOME/SOUL.md` is prepended to the system prompt on every turn. Create it with `iagent setup` or write it by hand. The `iagent setup` wizard offers to open the editor on it.

### 2.2 Heartbeat — periodic self-prompts ✅

`agent/heartbeat.py` — asyncio background task. Fires every `heartbeat_interval` seconds (0 = disabled). Sends a self-prompt to the agent loop; pushes replies to the first `allowed_user_ids` entry if the reply isn't a bare ".". Configurable prompt via `heartbeat_prompt` in `config.json`.

### 2.3 Skills (lite) ✅

`tools/skills.py` — `list_skills`, `view_skill`, `write_skill`. Skill files live in `skills/*.md` (shipped with the repo) and `$IAGENT_HOME/skills/*.md` (user-created, persist across updates). Starter skills: battery, disk_usage, wifi_info, uptime.

---

## Phase 3 — Native iPadOS access ✅

### 3.1 Shortcuts bridge ✅

`tools/shortcuts.py` — `run_shortcut(name, input)` and `list_shortcuts()`. Wraps the `shortcuts` CLI. Requires `shortcuts-cli` from Sileo if not already present. Gives access to HealthKit, HomeKit, Photos, Reminders, Calendar, iMessages, etc.

### 3.2 Notifications tool ✅

`tools/notify.py` — `send_notification(title, body)`. Uses `shortcuts run "iAgent Notify"`. The user creates one Shortcut once: **Receive Input → Show Notification**. Graceful degradation if `shortcuts-cli` is missing.

### 3.3 Clipboard tool ✅

`tools/clipboard.py` — `clipboard_read()` and `clipboard_write(text)`. Uses Procursus `pbcopy` / `pbpaste`. Install via Sileo if not present: `sudo apt install pbcopy`.

### 3.4 Photo / Camera tools ✅

`tools/photo.py` — `take_photo()`, `read_recent_photos(limit)`, `describe_photo(path, question)`.

- `take_photo` / `read_recent_photos` — Shortcuts bridge.
- `describe_photo` — base64-encodes the image and calls GPT-4o vision directly via httpx. Cap: 5 MB.

### 3.5 iOS Shortcuts bridges ✅

`tools/ios.py` — thin wrappers over named Shortcuts, all follow "receive text → do action → return text":

- `read_health(metric)` — HealthKit (steps, heart_rate, sleep, calories, …)
- `set_home_scene(name)` — HomeKit scenes
- `create_reminder(text, due)` — Reminders
- `create_calendar_event(title, start, end, notes)` — Calendar
- `get_location()` — GPS + address
- `play_music(query)` — Apple Music
- `save_to_files(filename, content)` — iCloud Drive / On My iPad
- `send_imessage(recipient, message)` — iMessage / SMS

Setup guide: ask the agent `view skill shortcuts_setup` for step-by-step Shortcut creation instructions.

---

## Phase 4 — Self-improvement

### 4.1 Autonomous skill creation ✅

`write_skill(name, content)` ships in Phase 2.3. The system prompt now explicitly instructs the agent to propose saving reusable procedures as skills after complex tasks, and to check `list_skills` before inventing a procedure that might already exist.

### 4.2 Persistent fact memory ✅

`agent/facts.py` + `tools/facts.py` — `remember_fact`, `recall_fact`, `list_facts`, `forget_fact`. Backed by `$IAGENT_HOME/facts.json`. Survives `/clear` and bot restarts. Distinct from conversation history.

### 4.3 Self-debugging ✅

`tools/self_debug.py`:
- `read_own_logs(lines)` — tail `iagent.log` + `stderr.log`
- `list_own_files()` — list Python files in `$IAGENT_HOME/code/`
- `read_own_source(file)` — read any file scoped to `code/`
- `patch_own_source(file, old_text, new_text, confirm)` — confirm=false shows diff only; confirm=true writes .bak and applies; path must stay inside `code/`
- `restart_self()` — fires `iagent restart` after 3 s delay so the reply is delivered first

---

## Non-goals

- **Local LLM (llama.cpp on iPad)** — RAM/battery constrained. OpenAI API is fine.
- **Voice mode** — use a Shortcuts "iAgent: Ask" shortcut instead.
- **Web UI** — terminal + Telegram covers everything for a single-user device.
- **Multi-tenant** — `allowed_user_ids` is the only access control needed.
- **Multi-channel** (WhatsApp/Discord/Signal) — Telegram + CLI is enough.

---

## Implementation status

| # | Feature | Status |
|---|---------|--------|
| 1.1 | Setup wizard | ✅ |
| 1.2 | Doctor | ✅ |
| 1.3 | apt_install tool | ✅ |
| 1.4 | Capability registry | ✅ |
| 2.1 | SOUL.md | ✅ |
| 2.2 | Heartbeat | ✅ |
| 2.3 | Skills lite | ✅ |
| 3.1 | Shortcuts bridge | ✅ |
| 3.2 | Notifications | ✅ |
| 3.3 | Clipboard | ✅ |
| 3.4 | Photo/Camera + GPT-4o vision | ✅ |
| 3.5 | Health/Home/Reminders/Location/Music/Files/iMessage | ✅ |
| 4.1 | Skill creation | ✅ |
| 4.2 | Fact memory | ✅ |
| 4.3 | Self-debugging | ✅ |
