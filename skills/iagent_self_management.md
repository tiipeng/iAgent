# iagent_self_management
Use this when modifying, debugging, updating, or teaching iAgent itself.

## Runtime
- Home: `/var/jb/var/mobile/iagent`
- Wrapper: `/var/jb/var/mobile/iagent/iagent`
- tmux socket: `/var/jb/var/mobile/iagent/tmux.sock`
- Main code: `/var/jb/var/mobile/iagent/code`
- Logs: `/var/jb/var/mobile/iagent/logs/iagent.log`
- Config: `/var/jb/var/mobile/iagent/config.json`
- System prompt: `/var/jb/var/mobile/iagent/code/agent/context.py`
- User skills: `/var/jb/var/mobile/iagent/skills/*.md`

## Current important config
- `history_window`: 30
- `max_iterations`: 20
- `shell_timeout`: 120
- model currently configured: `gpt-4o`

## Steps
1. For debugging, read logs first: `tail -120 /var/jb/var/mobile/iagent/logs/iagent.log`.
2. Before patching, back up the file with a timestamp suffix.
3. Run Python syntax checks: `/var/jb/var/mobile/iagent/venv/bin/python -m py_compile <files>`.
4. Restart with: `cd /var/jb/var/mobile/iagent && ./iagent restart`.
5. Verify status: `./iagent status` and tail logs.
6. For local test without Telegram: pipe a prompt into `./iagent chat`.

## Known fixes already applied
- Prompt now lists exact tool names like `shell`, not wrong aliases like `shell_run`.
- Prompt instructs act-first, persistent troubleshooting and secret redaction.
- `screenshot_xx` unlinks stale screenshot file before capture.
- `get_battery` uses `ioreg -r -c AppleSmartBattery` fallback on iOS.

## Pitfalls
- Telegram `Conflict: terminated by other getUpdates request` means multiple bot instances are polling. Stop duplicate instances.
- Do not print `.env`, Telegram token, OpenAI key, HomeKit PIN, Ring refresh token, or passwords.


## Sprint 4 self-test
- Use `run_selftest` when the user asks for health/self-checks or when you need a broad sanity check before debugging.
- CLI script: `/var/jb/var/mobile/iagent/scripts/selftest.py`.
- Checks: iAgent runtime/config/tmux, critical tool registry, Homebridge service health, XXTouch HTTP on 46952, ios-mcp `/health` on 8090, battery `ioreg` fallback, and memory/history sanitizer markers.
- `run_selftest(live=false)` skips live network/service probes for static verification.
- A healthy result should be `status: ok` with all seven checks ok. If a check warns/fails, use the specific component tools next (`repair_service` for Homebridge, `look_at_screen`/`screenshot_xx` for XXTouch, logs/source tools for iAgent).


## Sprint 5 operations journal
- Use `summarize_ops_journal` before proposing new fixes if a problem may be recurring.
- Use `read_ops_journal(limit=...)` to inspect recent redacted events.
- Journal file: `/var/jb/var/mobile/iagent/logs/ops_journal.jsonl`.
- Events currently written by live `run_selftest` and service `troubleshoot_service`/`repair_service`.
- Events are intentionally compact/redacted: do not store raw Homebridge logs, HomeKit setup codes, tokens, passwords, or refresh tokens.
- If the journal reports repeated warnings/failures, use the component-specific tools next: `repair_service` for Homebridge, `run_selftest` for broad health, and logs/source tools for iAgent internals.


## Sprint 6 status cards
- Use `get_status_card(live=true, include_journal=true)` for user-facing Telegram health/status requests.
- `get_status_card` combines `run_selftest`, `summarize_ops_journal`, Homebridge port/tmux status, XXTouch, ios-mcp, battery fallback, history sanitizer, and known blockers.
- Use `format_status_card(selftest=..., journal_summary=...)` when selftest/journal data is already available.
- Status cards are Telegram-friendly plain text with ✅/⚠️/❌ icons and avoid raw logs/secrets.
- Known blockers currently shown: Ring refresh token/auth needed, Samsung TV physical Allow may be needed, Dyson not finalized.
