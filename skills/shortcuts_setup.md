# shortcuts_setup
Guide to creating the iOS Shortcuts that power Phase 3 tools.

## Steps
Each iAgent tool that touches native iOS APIs needs one Shortcut. Create them
once in the Shortcuts app. All follow the same pattern:
receive text input → do the action → return text output.

### iAgent Notify (send_notification)
1. New Shortcut → Add Action: "Receive Input from Shortcut"
2. Add Action: "Show Notification" → Message = Shortcut Input
3. Name it exactly: iAgent Notify

### iAgent Take Photo (take_photo)
1. New Shortcut → "Take Photo"
2. "Save File" → save to /var/jb/var/mobile/iagent/workspace/photo.jpg
3. "Return" → text: /var/jb/var/mobile/iagent/workspace/photo.jpg
4. Name it: iAgent Take Photo

### iAgent Recent Photos (read_recent_photos)
1. New Shortcut → Receive Input (number)
2. "Find Photos" → limit = Shortcut Input (sort: latest first)
3. For each photo: "Save File" to workspace → collect paths
4. "Return" → newline-joined paths
5. Name it: iAgent Recent Photos

### iAgent Health (read_health)
1. New Shortcut → Receive Input (text = metric name)
2. "Find Health Samples" → type = Shortcut Input, limit 1, sort newest first
3. "Return" → value + unit
4. Name it: iAgent Health

### iAgent HomeKit (set_home_scene)
1. New Shortcut → Receive Input (scene name)
2. "Control Home" → run scene named Shortcut Input
3. "Return" → "Scene triggered: " + Shortcut Input
4. Name it: iAgent HomeKit

### iAgent Reminder (create_reminder)
1. New Shortcut → Receive Input (text: "title|due_date")
2. Split text by "|" → index 0 = title, index 1 = due (optional)
3. "Add New Reminder" → title, due date if present
4. "Return" → "Reminder created: " + title
5. Name it: iAgent Reminder

### iAgent Calendar (create_calendar_event)
1. New Shortcut → Receive Input (text: "title|start|end|notes")
2. Split by "|" → extract fields
3. "Add New Event" → fill fields
4. "Return" → "Event created: " + title
5. Name it: iAgent Calendar

### iAgent Location (get_location)
1. New Shortcut → "Get Current Location"
2. "Return" → latitude + "," + longitude + "\n" + street address
3. Name it: iAgent Location

### iAgent Music (play_music)
1. New Shortcut → Receive Input (search query)
2. "Search Music" → Shortcut Input
3. "Play Music" → first result
4. "Return" → "Playing: " + track name
5. Name it: iAgent Music

### iAgent Save File (save_to_files)
1. New Shortcut → Receive Input (text: "filename|content")
2. Split by "|" → index 0 = filename, index 1 = content
3. "Make Text File" → content
4. "Save File" to On My iPad/iAgent/ → filename
5. "Return" → "Saved: " + filename
6. Name it: iAgent Save File

### iAgent Message (send_imessage)
1. New Shortcut → Receive Input (text: "recipient|message")
2. Split by "|" → index 0 = recipient, index 1 = body
3. "Send Message" → recipient, body
4. "Return" → "Sent to " + recipient
5. Name it: iAgent Message
