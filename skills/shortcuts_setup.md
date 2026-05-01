# shortcuts_setup
Reality check and safe workflow for iOS Shortcuts on this jailbroken iPad.

## Key facts
- There is NO working `shortcuts` CLI binary on this iOS device, and no apt package for it.
- iAgent tools that depend on `/var/jb/usr/bin/shortcuts` should be treated as unavailable unless a real binary is later verified.
- Direct SQLite INSERT into `/var/mobile/Library/Shortcuts/Shortcuts.sqlite` can create DB rows, but the Shortcuts runtime ignores them because it uses in-memory cache/proper import/runtime state.
- Only Shortcuts created through the Shortcuts app UI or proper Apple import flow reliably run.
- Query Shortcuts.sqlite WITHOUT `immutable=1`; immutable mode returned stale/empty data here.

## Steps
1. Do not tell the user to install `shortcuts-cli`; it is not available here.
2. Prefer native tools and databases: photos/calendar/contacts/messages/reminders via built-in iAgent tools or SQLite.
3. Prefer XXTouch for UI automation and screen workflows.
4. To open the Shortcuts app or run a user-created Shortcut, use `open_url` with URL schemes like `shortcuts://` or `shortcuts://run-shortcut?name=<encoded-name>`.
5. If a Shortcut must exist, ask the user to create it manually in the Shortcuts app, then verify via screen observation.

## Pitfalls
- Do not promise automated Shortcut creation via DB insert; it was tested and does not work reliably.
- Do not confuse macOS `shortcuts` CLI with this iOS device.
