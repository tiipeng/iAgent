# ipad_native_data
Use this when reading Photos, Calendar, Contacts, Reminders, Messages, Safari history, Voice Memos, or other on-device iOS databases.

## Working tools
- `read_recent_photos`, `describe_photo`, `send_photo`
- `read_messages`
- `read_contacts`
- `read_calendar_events`
- `read_safari_history`
- `list_voice_memos`
- `shell` + `/var/jb/usr/bin/sqlite3` for direct database queries

## Important paths
- Photos DB: `/var/mobile/Media/PhotoData/Photos.sqlite`
- Photos files: `/var/mobile/Media/DCIM/`
- Calendar DB: `/var/mobile/Library/Calendar/Calendar.sqlitedb`
- Contacts DB: `/var/mobile/Library/AddressBook/AddressBook.sqlitedb`
- Messages DB: `/var/mobile/Library/SMS/sms.db`
- Safari history: `/var/mobile/Library/Safari/History.db`
- Reminders DB: `/var/mobile/Library/Reminders/Container_v1/Stores/Data-local.sqlite`

## Steps
1. Prefer built-in tools first (`read_contacts`, `read_calendar_events`, etc.).
2. If a built-in tool is insufficient, use `shell` with `/var/jb/usr/bin/sqlite3` and read-only SQLite URI.
3. For most iOS databases use `?immutable=1` to avoid lock contention.
4. For Shortcuts.sqlite specifically, do NOT use `immutable=1`; it can return stale/empty data.
5. Never expose private message/contact contents unnecessarily; summarize only what the user asked for.

## Pitfalls
- Directly inserting Shortcuts into Shortcuts.sqlite does not make them runnable; Shortcuts daemon uses an in-memory cache and ignores DB-inserted shortcuts.
- There is no `shortcuts` CLI package on this iOS.
