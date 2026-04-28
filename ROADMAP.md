# iAgent — Roadmap

Planned features, ordered by what unlocks the most value per implementation effort. Each item lists files to touch, scope, and known blockers so future-me (or a contributor) can pick one up cold.

**Status legend:** ⬜ planned · 🚧 in progress · ✅ shipped

---

## Phase 1 — Setup wizard & Sileo gateway

The current install is "edit two files in nano, then paste four sudo commands". That works once you know the layout, but it's hostile for a fresh user, and there's no way for the agent itself to install Sileo packages it discovers it needs (e.g., `pbcopy` for the clipboard tool, `clang` if a future dep needs to compile). This phase fixes both, and lays the groundwork everything else builds on.

### 1.1 `iagent setup` — interactive setup wizard ⬜

**What:** A new `setup.py` (and a launcher at `$IAGENT_HOME/setup`) that walks a fresh user through onboarding in the terminal:

```
iAgent setup wizard
───────────────────
[1/6] Telegram bot token (from @BotFather): ******
      → Verifying… ok, bot is @your_iagent_bot
[2/6] OpenAI API key (sk-...): ******
      → Verifying… ok, account in good standing
[3/6] Your Telegram numeric user ID (from @userinfobot): 123456789
      → Saved to allowed_user_ids
[4/6] Personality / SOUL.md — open editor now? [y/N]: y
      (opens nano on $IAGENT_HOME/SOUL.md with a template)
[5/6] Heartbeat interval in minutes (0 = disabled) [0]:
[6/6] Install LaunchDaemon now (requires sudo)? [Y/n]: y
      → sudo cp / chown / chmod / launchctl load …
      → Daemon loaded. PID 6789.

✓ Setup complete. Send /start to your bot in Telegram.
```

**Why:**
- Deletes the manual nano steps from the README.
- Validates tokens / API keys *before* writing them, instead of failing at daemon startup.
- One canonical happy path, with sensible defaults.
- Makes re-running safe — detects existing values and offers to keep them.

**Scope:** ~250 lines.
- New file `setup.py` at the project root. Pure stdlib + `httpx` (already a dep) for the validation HTTP calls.
- Validates Telegram token by calling `getMe`; rejects on 401.
- Validates OpenAI key by calling `/v1/models` (cheap); rejects on 401.
- Re-uses the JSON config writer from `config/settings.py` so the format stays canonical.
- Wraps the four sudo commands behind a single `[Y/n]` prompt and runs them via `subprocess.run` (with `sudo -p` so the user sees a real prompt for their password).
- New launcher at `$IAGENT_HOME/setup` (created by `install.sh`) that sets `IAGENT_HOME` and `SSL_CERT_FILE` like the `chat` launcher already does.
- `bootstrap.sh` runs `setup.py` automatically on first install (when `.env` doesn't yet exist), turning the install one-liner into a complete onboarding.

**Risks:**
- Token validation requires network. If the iPad is offline at setup time, fall back to "save without verifying, warn user".
- Re-running setup must never overwrite existing values silently — always confirm.

### 1.2 `iagent doctor` — diagnose common issues ⬜

**What:** A read-only diagnostics command that checks every known failure mode and reports green/red:

```
$ iagent doctor
✓ Python 3.9.9 at /var/jb/usr/bin/python3.9
✓ venv exists with 27 packages installed
✓ .env present, TELEGRAM_TOKEN set, OPENAI_API_KEY set
✓ config.json valid, allowed_user_ids has 1 entry
✓ Telegram token verified — bot @your_iagent_bot
✓ OpenAI key verified — gpt-4o accessible
✓ LaunchDaemon loaded, PID 6789, exit 0
✓ Last log entry 2 minutes ago, no errors
✓ Disk space: 8.3 GB free
✗ ca-certificates: not installed (TLS may fail)
   → fix: sudo apt install ca-certificates
```

**Why:** When something breaks, the user shouldn't have to read 12 troubleshooting paragraphs to figure out which step failed. This collapses all of them into one command.

**Scope:** ~150 lines, single file `doctor.py`. Each check is a small function that returns `(name, ok: bool, message, fix_suggestion)`.

**Risks:** None — read-only.

### 1.3 `apt_install` tool — agent installs its own Sileo packages ⬜

**What:** A new tool that lets the agent install Procursus packages on demand, with explicit user approval. The agent calls `apt_install(package="pbcopy", reason="needed for the clipboard tool")`. Implementation:

1. The tool sends a confirmation message to the user (Telegram or CLI prompt): *"iAgent wants to install `pbcopy` — reason: needed for the clipboard tool. Approve? [y/N]"*
2. If approved, runs `sudo apt-get install -y <package>` non-interactively.
3. Returns the install output (or `"denied by user"`) to the agent.

A small allowlist of "always safe" packages (e.g., `pbcopy`, `terminal-notifier`, `ca-certificates`) can be configured for one-tap approval.

**Why:**
- iAgent already discovers it needs packages (we hit `clang` and `ca-certificates` during install). Letting the agent ask is more transparent than a static `requirements.txt`.
- Future tools (clipboard, notifications, photo) will fail gracefully if their underlying CLI isn't installed, then propose installing it.
- Combined with `iagent doctor`, the agent can self-heal common breakage: "ca-certificates is missing, want me to install it? [y/N]".

**Scope:** ~80 lines.
- New file `tools/apt.py`.
- Two tools: `apt_install(package, reason)` and `apt_search(query)` (the latter is read-only, no approval needed).
- Approval flow: v1 ships **allowlist-only** (config-driven `apt_install_allowlist`). Anything not in the allowlist is refused with the suggestion *"add `<package>` to apt_install_allowlist in config.json to permit this"*. Interactive approval (CLI prompt + Telegram inline keyboard) lands in v2 once the rest of the gateway is stable.
- New config keys: `apt_install_enabled` (bool, default `false` — opt-in), `apt_install_allowlist` (list of pre-approved package names).

**Risks:**
- **Sudo password.** Running `sudo apt-get install` non-interactively requires either a passwordless sudoers rule for `mobile` (one-line edit to `/var/jb/etc/sudoers.d/iagent`) or pre-cached sudo credentials. The setup wizard (1.1) offers to add the sudoers rule with a clear explanation: *"This lets iAgent install packages without asking for your password each time. Decline if you'd rather approve every install manually."*
- **Supply chain.** `apt-get install` from the Procursus repo is as trusted as the repo itself. Don't accept arbitrary `.deb` URLs. The tool validates the package name format (`^[a-z0-9.+-]+$`) and refuses anything else.
- **Disk space.** Some Sileo packages are huge (`clang` ≈ 100 MB). Tool refuses if free disk < 500 MB and reports back.

### 1.4 Capability registry ⬜

**What:** A small registry at `$IAGENT_HOME/capabilities.json` that records which Sileo packages and Shortcuts the agent has confirmed are available. Tools query it before running so they can fail fast with a useful suggestion.

```json
{
  "shortcuts": ["iAgent: Notify", "iAgent: Take Photo"],
  "apt": {"pbcopy": "installed", "clang": "missing"},
  "verified_at": "2026-04-28T12:34:56Z"
}
```

**Why:** Without this, every tool call has to probe its dependency. With it, the agent knows up front what's available and can route around what's missing — e.g., the notification tool can fall back to a Telegram message if `iAgent: Notify` shortcut isn't installed.

**Scope:** ~50 lines.
- New file `capabilities.py` — lazy loader, refresh-on-doctor.
- `iagent doctor` populates it.
- Tools read it via a single `has_capability("apt:pbcopy")` helper.

**Risks:** Stale entries — registry should be invalidated whenever `apt-get install/remove` runs. Tie this to the `apt_install` tool.

---

## Phase 2 — Make the agent feel persistent

Today iAgent is a Q&A bot: it only thinks when you message it. These three features turn it into something that has a personality, runs in the background, and accumulates competence over time.

### 2.1 SOUL.md — personality / standing instructions ⬜

**What:** A free-form Markdown file at `$IAGENT_HOME/SOUL.md` that gets prepended to the system prompt. The user writes things like "you are terse", "always reply in German", "you have a sarcastic streak", "track the user's caffeine intake".

**Why:** Without this, the system prompt is a hardcoded string in `agent/context.py` and the agent has no consistent voice. With it, the agent feels like a specific entity, not a generic GPT-4o wrapper.

**Scope:** ~15 lines.
- [agent/context.py](agent/context.py) — read `$IAGENT_HOME/SOUL.md` (if exists) at `ChatContext.__init__`, store the contents, append to `system_prompt()` output.
- [install.sh](install.sh) — drop a `SOUL.md.example` if no SOUL.md exists.
- [README.md](README.md) — document.

**Risks:** None. Pure additive.

### 2.2 Heartbeat — periodic self-prompts ⬜

**What:** An asyncio background task that wakes the agent every N minutes (configurable, default 30) with a self-prompt: *"It's HH:MM. Anything you should do, check, or remember? If not, say 'nothing'."* Replies are persisted to memory but not pushed to Telegram unless the agent explicitly calls a `notify` tool.

**Why:** This is what separates a bot from an agent. With heartbeats the agent can:
- Check on running processes ("is the daemon I started still alive?")
- Watch a value over time ("the battery dropped from 80% to 30% in an hour — flag this")
- Run scheduled errands ("every weekday at 09:00, summarise yesterday's notes")
- Update a journal file
- Decide on its own to message you when something changes

**Scope:** ~80 lines.
- New file `agent/heartbeat.py` — `async def run_heartbeat_loop(app, interval_seconds)` that loops, sleeps, calls `agent.loop.run` with a synthesized system message.
- [main.py](main.py) — start the heartbeat task in `on_startup` if `config.heartbeat_interval > 0`.
- [config/settings.py](config/settings.py) — new fields: `heartbeat_interval` (seconds, 0 = disabled), `heartbeat_chat_id` (target for `notify` tool messages).
- New tool `tools/notify.py` — sends a Telegram message via the bot's existing token to the configured chat. Required so the agent can choose when a heartbeat result deserves user attention.

**Risks:**
- **Cost.** Heartbeat = a GPT-4o call every N minutes, even when idle. At default 30 min that's ~48 calls/day. Cap with a small `gpt-4o-mini` for the heartbeat self-prompt and only escalate to `gpt-4o` if the agent decides to take action.
- **Loops.** A heartbeat tool call result that triggers another heartbeat → runaway loop. Mitigate: the heartbeat synthesizer marks its prompt with a sentinel role, and `agent/loop.py` increments a separate counter that's allowed at most 3 actions per heartbeat tick.
- **Memory bloat.** 48 ticks/day × 365 = ~17k extra rows. Add a config-driven `prune_heartbeat_messages_after_days` and run it nightly.

### 2.3 Skills (lite) ⬜

**What:** Every `.md` file in `$IAGENT_HOME/skills/` is treated as a skill. At startup we scan the directory and inject a one-line summary of each skill (filename + first H1 line) into the system prompt: *"Available skills: cooking, debug-network, write-blog-post — call `view_skill(name)` to read one in full."* The agent uses the new `view_skill` tool when it decides a skill is relevant.

**Why:** Lazy-loading skill bodies into context only when needed keeps the system prompt small (cheap tokens) but gives the agent access to a library of how-tos written in plain English. Same idea as agentskills.io / hermes-agent's skill system, minus the autonomous skill creation (which we're explicitly not building yet — see Phase 4).

**Scope:** ~60 lines.
- New file `tools/skills.py` — defines `view_skill(name)` and `list_skills()`.
- [agent/context.py](agent/context.py) — at startup, glob `skills/*.md`, parse first H1 of each, format as a bullet list, append to system prompt.
- [install.sh](install.sh) — `mkdir -p $IAGENT_HOME/skills` and drop a `skills/README.md.example`.

**Risks:** None significant. If the skills directory grows past ~50 entries the system prompt could get long; cap the list at first 30 and let the agent discover others via `list_skills()`.

---

## Phase 3 — Native iPadOS access

The current `shell` tool already gives access to anything in `/var/jb/usr/bin/`. These tools wrap specific iOS capabilities so the agent doesn't have to figure out the right invocation each time. Most are thin wrappers over the iOS Shortcuts CLI — once the bridge exists, adding a new capability is one shortcut + one tool registration.

### 3.1 Shortcuts bridge — the big one ⬜

**What:** A `run_shortcut` tool that invokes a named entry from the user's iOS Shortcuts library via the `shortcuts` CLI (built into iOS 13+, exposed by Procursus on jailbreak). Optionally accepts input text/URL/file. Captures and returns output.

**Why:** Shortcuts is iOS's official scripting layer. A single shortcut can:
- Take a photo, then OCR it
- Read HealthKit data (steps, heart rate, sleep)
- Set HomeKit scenes ("turn off all lights")
- Play music, control playback
- Send iMessages
- Read/create Reminders, Calendar events, Notes
- Get current location, weather, calendar
- Run an Apple Script-style multi-step automation

By wrapping `shortcuts run`, the agent gets access to all of those without writing native Swift/ObjC. The user creates shortcuts visually, the agent calls them by name.

**Scope:** ~50 lines + a small set of starter shortcuts.
- New file `tools/shortcuts.py` — wraps `shortcuts run "<name>" --input-path /tmp/...`. Returns stdout.
- New tool `list_shortcuts` — runs `shortcuts list` and returns the names so the agent can discover what's available.
- README section on building shortcuts (how to create one, how to expose input/output).
- Recommended starter shortcut: `iAgent: Notify` that takes text input and shows a banner notification — gives us a clean notification path without writing a native bridge.

**Risks:**
- The `shortcuts` CLI may not be in the default Procursus repo — verify before merging. Fallback path: AltDaemon or a small ObjC helper.
- Shortcuts that require user interaction (taps, permissions) will hang the tool call. Document: only fully-automated shortcuts work.
- Some shortcuts return files, not text. Tool should accept `output_path` and write the result to disk for follow-up tools to pick up.

### 3.2 Notifications tool ⬜

**What:** Push a banner notification to the iPad from the agent.

**Why:** Heartbeats and async tasks need a way to grab attention without spamming the Telegram chat.

**Scope:** ~20 lines.
- **Path A** (preferred): use the Shortcuts bridge — make a `iAgent: Notify` shortcut that takes text input and shows a notification. Tool just calls `shortcuts run "iAgent: Notify" --input "..."`.
- **Path B** (fallback): use a Sileo notification tool like `libsbnotify` if available.

### 3.3 Clipboard tool ⬜

**What:** `clipboard_read` and `clipboard_write` tools.

**Scope:** ~15 lines. Procursus ships `pbcopy` / `pbpaste`. Wrap as `asyncio.create_subprocess_exec` calls. If missing, the agent can use Phase 1.3 `apt_install` to add them.

### 3.4 Photo / Camera tools ⬜

**What:** `take_photo()`, `read_recent_photos(limit=5)`, `describe_photo(path)`.

**Why:** Agent can "look at" what's around. Combined with GPT-4o's vision, the agent can reason about what's in front of the camera or in the user's photo library.

**Scope:** ~80 lines. Three sub-pieces:
- `take_photo` — Shortcuts bridge to a `iAgent: Take Photo` shortcut.
- `read_recent_photos` — Shortcuts bridge to fetch the N most recent photos as files in `/tmp/`.
- `describe_photo` — base64-encode a JPG and send to GPT-4o vision via the OpenAI API. Returns the description text.

**Risks:**
- File size — photos are 3–5 MB, base64 inflates them. Resize to max 1024px before sending.
- Privacy — photo access on iOS requires the parent app (Shortcuts) to have the Photos permission. One-time setup the user has to do manually.

### 3.5 Pasteboard / Files / AirDrop bridges ⬜

Lower-priority Shortcuts-based wrappers. Each is one shortcut + one tool. Build on demand:

- `airdrop_to(file, contact)` — share a file via AirDrop to a named contact
- `save_to_files(content, path)` — write into the iOS Files app (which is just iCloud Drive / On My iPad)
- `read_health(metric)` — get steps / heart rate / sleep from HealthKit
- `set_home_scene(name)` — trigger a HomeKit scene
- `play_music(query)` — search and play in Music app
- `create_reminder(text, when)` — add to Reminders
- `get_location()` — current GPS coords

---

## Phase 4 — Self-improvement

These features turn iAgent from "a tool that calls tools" into "an agent that grows". Significantly more complex than Phase 1–3 — do not start until earlier phases are solid.

### 4.1 Autonomous skill creation ⬜

**What:** When the agent successfully completes a multi-step task, it offers to save the procedure as a skill. The user approves with one word, the skill is written to `skills/<name>.md`. Next time a similar task comes up, the skill is suggested.

**Why:** This is hermes-agent's killer feature. The agent gets better the more you use it.

**Scope:** ~200 lines, plus careful prompt engineering.
- New tool `save_skill(name, body, when_to_use)` — writes a skill file.
- New system prompt suffix: "After completing complex tasks, consider whether the procedure is reusable. If so, propose saving it as a skill."
- Heartbeat side: occasionally read the last day of conversation history and propose skills proactively.

**Risks:**
- Token cost — proposing skills means re-reading history.
- Skill quality — bad early skills will mislead the agent. Gate skill creation behind explicit user `yes` (per-skill, never auto-save).

### 4.2 Memory beyond conversation history ⬜

**What:** A separate "facts" table in SQLite. The agent can `remember(fact)` and `recall(query)`. Distinct from conversation messages — facts are permanent until removed.

**Why:** Conversation history rolls off after `history_window` messages. Facts shouldn't.

**Scope:** ~100 lines. New table, new tools, FTS5 index for `recall`.

**Risks:** What counts as a fact vs. a conversation detail is fuzzy. The agent will over-remember. Add a soft cap (e.g., 200 facts) and an `important: true/false` flag.

### 4.3 Self-debugging ⬜

**What:** When a tool errors out, the agent can read its own logs (`/var/jb/var/mobile/iagent/logs/stderr.log`), grep for the error, and propose a fix — possibly even a diff against its own source code. The user approves, the agent writes the file, the daemon restarts.

**Why:** Closing the loop on iteration speed.

**Scope:** Significant. Needs:
- A "self" tool family that scopes file ops to `code/`
- A `restart_daemon` tool (probably wraps `launchctl unload && launchctl load`)
- A safety net — never run unattended; always require user approval before writing to `code/`

**Risks:** This is the "the AI rewrote itself and broke" risk. Always require explicit approval. Always keep a known-good copy in git so the user can `git reset --hard origin/main && bootstrap.sh` to recover.

---

## Non-goals

These are deliberately out of scope. Don't add them without a concrete reason:

- **Local LLM (llama.cpp on iPad)** — RAM and battery are too constrained. The OpenAI API works fine.
- **Voice mode** — Shortcuts already exposes Siri. If the user wants voice, build a "iAgent: Ask" shortcut that captures speech, runs the agent, speaks the reply. Don't build a native audio loop in Python.
- **Web UI** — terminals and Telegram cover everything. A web UI is more attack surface for no real gain on a single-user device.
- **Multi-tenant** — this is a personal device. The `allowed_user_ids` allowlist is the only access control. Don't add OAuth, RBAC, accounts, etc.
- **Multi-channel** (WhatsApp / Discord / Signal / iMessage) — iAgent is built for one user on one device. Telegram + CLI is enough.

---

## Implementation order (recommended)

1. **Setup wizard** (1.1) — 1 evening, deletes the manual onboarding nano dance · 🚧 starting now
2. **Doctor** (1.2) — 2 hours, one command replaces 12 troubleshooting paragraphs
3. **`apt_install` tool** (1.3) — 1 evening, lets the agent fill its own gaps
4. **Capability registry** (1.4) — 2 hours, glue between 1.2 and 1.3
5. **SOUL.md** (2.1) — 15 minutes, instant feel improvement
6. **Skills lite** (2.3) — 1 evening, large capability multiplier
7. **Shortcuts bridge** (3.1) — 1 evening, unlocks Phase 3 entirely
8. **Notifications** (3.2) — 30 minutes once 3.1 is done
9. **Heartbeat** (2.2) — 1 weekend, requires care around cost & loops
10. **Clipboard** (3.3) — 15 minutes, useful daily
11. Photo / vision (3.4) — when there's a use case
12. Memory facts (4.2) — when conversation history isn't enough
13. Skill creation (4.1) — only after the user has manually written 5+ skills and seen the value

Phase 4.3 (self-debug) — likely never. Listed for completeness.
