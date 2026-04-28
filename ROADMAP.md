# iAgent — Roadmap

Planned features, ordered by what unlocks the most value per implementation effort. Nothing here is built yet. Each item lists files to touch, scope, and known blockers so future-me (or a contributor) can pick one up cold.

---

## Phase 1 — Make the agent feel persistent

Today iAgent is a Q&A bot: it only thinks when you message it. These three features turn it into something that has a personality, runs in the background, and accumulates competence over time.

### 1.1 SOUL.md — personality / standing instructions

**What:** A free-form Markdown file at `$IAGENT_HOME/SOUL.md` that gets prepended to the system prompt. The user writes things like "you are terse", "always reply in German", "you have a sarcastic streak", "track the user's caffeine intake".

**Why:** Without this, the system prompt is a hardcoded string in `agent/context.py` and the agent has no consistent voice. With it, the agent feels like a specific entity, not a generic GPT-4o wrapper.

**Scope:** ~15 lines.
- [agent/context.py](agent/context.py) — read `$IAGENT_HOME/SOUL.md` (if exists) at `ChatContext.__init__`, store the contents, append to `system_prompt()` output.
- [install.sh](install.sh) — drop a `SOUL.md.example` if no SOUL.md exists.
- [README.md](README.md) — document.

**Risks:** None. Pure additive.

---

### 1.2 Heartbeat — periodic self-prompts

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

---

### 1.3 Skills (lite)

**What:** Every `.md` file in `$IAGENT_HOME/skills/` is treated as a skill. At startup we scan the directory and inject a one-line summary of each skill (filename + first H1 line) into the system prompt: *"Available skills: cooking, debug-network, write-blog-post — call `view_skill(name)` to read one in full."* The agent uses the new `view_skill` tool when it decides a skill is relevant.

**Why:** Lazy-loading skill bodies into context only when needed keeps the system prompt small (cheap tokens) but gives the agent access to a library of how-tos written in plain English. Same idea as agentskills.io / hermes-agent's skill system, minus the autonomous skill creation (which we're explicitly not building yet — see Phase 3).

**Scope:** ~60 lines.
- New file `tools/skills.py` — defines `view_skill(name)` and `list_skills()`.
- [agent/context.py](agent/context.py) — at startup, glob `skills/*.md`, parse first H1 of each, format as a bullet list, append to system prompt.
- [install.sh](install.sh) — `mkdir -p $IAGENT_HOME/skills` and drop a `skills/README.md.example`.

**Risks:** None significant. If the skills directory grows past ~50 entries the system prompt could get long; cap the list at first 30 and let the agent discover others via `list_skills()`.

---

## Phase 2 — Native iPadOS access

The current `shell` tool already gives access to anything in `/var/jb/usr/bin/`. These tools wrap specific iOS capabilities so the agent doesn't have to figure out the right invocation each time.

### 2.1 Shortcuts bridge — the big one

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

---

### 2.2 Notifications tool

**What:** Push a banner notification to the iPad from the agent.

**Why:** Heartbeats and async tasks need a way to grab attention without spamming the Telegram chat. Banner notifications are the right channel for "your reminder fired" / "build finished" / "process X is using 90% CPU".

**Scope:** ~20 lines, two implementation paths:
- **Path A** (preferred): use the Shortcuts bridge — make a `iAgent: Notify` shortcut that takes text input and shows a notification. Tool just calls `shortcuts run "iAgent: Notify" --input "..."`.
- **Path B** (fallback): use a Sileo notification tool like `libsbnotify` if available. More fragile.

**Risks:** Notifications require the host app (Shortcuts) to have notification permission granted.

---

### 2.3 Clipboard tool

**What:** `clipboard_read` and `clipboard_write` tools.

**Why:** Lets the user copy a URL/text on the iPad, message the agent "summarise what I just copied", and the agent reads the clipboard directly. Or the inverse — agent puts the result of a long computation on the clipboard for paste-in-app.

**Scope:** ~15 lines.
- Procursus ships `pbcopy` / `pbpaste` (yes, named after the macOS commands). Wrap as `asyncio.create_subprocess_exec` calls.

**Risks:** None.

---

### 2.4 Photo / Camera tools

**What:** `take_photo()`, `read_recent_photos(limit=5)`, `describe_photo(path)`.

**Why:** Agent can "look at" what's around. Combined with GPT-4o's vision, the agent can reason about what's in front of the camera or in the user's photo library.

**Scope:** ~80 lines. Three sub-pieces:
- `take_photo` — Shortcuts bridge to a `iAgent: Take Photo` shortcut.
- `read_recent_photos` — Shortcuts bridge to fetch the N most recent photos as files in `/tmp/`.
- `describe_photo` — base64-encode a JPG and send to GPT-4o vision via the OpenAI API. Returns the description text.

**Risks:**
- File size — photos are 3–5 MB, base64 inflates them. Resize to max 1024px before sending.
- Privacy — photo access on iOS requires the parent app (Shortcuts) to have the Photos permission. One-time setup the user has to do manually.

---

### 2.5 Pasteboard / Files / AirDrop bridges

Lower-priority Shortcuts-based wrappers. Each is one shortcut + one tool. List for completeness:

- `airdrop_to(file, contact)` — share a file via AirDrop to a named contact
- `save_to_files(content, path)` — write into the iOS Files app (which is just iCloud Drive / On My iPad)
- `read_health(metric)` — get steps / heart rate / sleep from HealthKit
- `set_home_scene(name)` — trigger a HomeKit scene
- `play_music(query)` — search and play in Music app
- `create_reminder(text, when)` — add to Reminders
- `get_location()` — current GPS coords

Build these on demand. Don't pre-implement — wait until there's a concrete use case.

---

## Phase 3 — Self-improvement

These features turn iAgent from "a tool that calls tools" into "an agent that grows". Significantly more complex than Phase 1 & 2 — do not start until Phase 1 is solid.

### 3.1 Autonomous skill creation

**What:** When the agent successfully completes a multi-step task, it offers to save the procedure as a skill. The user approves with one word, the skill is written to `skills/<name>.md`. Next time a similar task comes up, the skill is suggested.

**Why:** This is hermes-agent's killer feature. The agent gets better the more you use it.

**Scope:** ~200 lines, plus careful prompt engineering.
- New tool `save_skill(name, body, when_to_use)` — writes a skill file.
- New system prompt suffix: "After completing complex tasks, consider whether the procedure is reusable. If so, propose saving it as a skill."
- Heartbeat side: occasionally read the last day of conversation history and propose skills proactively.

**Risks:**
- Token cost — proposing skills means re-reading history.
- Skill quality — bad early skills will mislead the agent. Gate skill creation behind explicit user `yes` (per-skill, never auto-save).

### 3.2 Memory beyond conversation history

**What:** A separate "facts" table in SQLite. The agent can `remember(fact)` and `recall(query)`. Distinct from conversation messages — facts are permanent until removed.

**Why:** Conversation history rolls off after `history_window` messages. Facts shouldn't.

**Scope:** ~100 lines. New table, new tools, FTS5 index for `recall`.

**Risks:** What counts as a fact vs. a conversation detail is fuzzy. The agent will over-remember. Add a soft cap (e.g., 200 facts) and an `important: true/false` flag.

### 3.3 Self-debugging

**What:** When a tool errors out, the agent can read its own logs (`/var/jb/var/mobile/iagent/logs/stderr.log`), grep for the error, and propose a fix — possibly even a diff against its own source code. The user approves, the agent writes the file, the daemon restarts.

**Why:** Closing the loop on iteration speed.

**Scope:** Significant. Needs:
- A "self" tool family that scopes file ops to `code/`
- A `restart_daemon` tool (probably wraps `launchctl unload && launchctl load`)
- A safety net — never run unattended; always require user approval before writing to `code/`

**Risks:** This is the "the AI rewrote itself and broke" risk. Always require explicit approval. Always keep a known-good copy in git so the user can `git reset --hard origin/main && bootstrap.sh` to recover.

---

## Phase 4 — Multi-channel (parking lot)

If iAgent needs to handle more than Telegram + CLI, the abstraction should look like openclaw's gateway model: a unified "inbound message" event source that channel adapters publish to.

Likely the wrong direction for a personal-device agent. Most users want one channel (Telegram). Don't build until there's a concrete second channel that's actually useful — probably **iMessage** via BlueBubbles, since the iPad already has the Messages app.

Listed for completeness, not for execution.

---

## Non-goals

These are deliberately out of scope. Don't add them without a concrete reason:

- **Local LLM (llama.cpp on iPad)** — RAM and battery are too constrained. The OpenAI API works fine.
- **Voice mode** — Shortcuts already exposes Siri. If the user wants voice, build a "iAgent: Ask" shortcut that captures speech, runs the agent, speaks the reply. Don't build a native audio loop in Python.
- **Web UI** — terminals and Telegram cover everything. A web UI is more attack surface for no real gain on a single-user device.
- **Multi-tenant** — this is a personal device. The `allowed_user_ids` allowlist is the only access control. Don't add OAuth, RBAC, accounts, etc.

---

## Implementation order (recommended)

1. **SOUL.md** (1.1) — 15 minutes, instant feel improvement
2. **Skills lite** (1.3) — 1 evening, large capability multiplier
3. **Shortcuts bridge** (2.1) — 1 evening, unlocks Phase 2 entirely
4. **Notifications** (2.2) — 30 minutes once 2.1 is done
5. **Heartbeat** (1.2) — 1 weekend, requires care around cost & loops
6. **Clipboard** (2.3) — 15 minutes, useful daily
7. Photo / vision (2.4) — when there's a use case
8. Memory facts (3.2) — when conversation history isn't enough
9. Skill creation (3.1) — only after the user has manually written 5+ skills and seen the value

Phase 3.3 (self-debug) and Phase 4 (multi-channel) — likely never. Listed for completeness.
