# ipad_xxtouch_control
Use this when controlling the iPad screen, taking screenshots, reading iOS app state, using XXTouch, or operating apps by UI.

## Key facts
- Device: jailbroken/rootless Dopamine iPad, iPad11,3, iOS 16.3.1.
- XXTouch HTTP API runs on `http://127.0.0.1:46952`.
- Working screen capture tool is `screenshot_xx`; visual analysis tool is `look_at_screen`.
- Synthetic touch tools: `tap`, `swipe`, `scroll`, `press_home`.
- App tools: `open_app`, `open_url`, `list_apps`.
- Clipboard tools: `clipboard_read`, `clipboard_write`; pbcopy/pbpaste warnings can be harmless.
- iOS has no normal `/bin/sh`; prefer `/var/jb/bin/sh` and full paths under `/var/jb/usr/bin`.

## Steps
1. For “what is on screen”, “tap this button”, or “find UI element”, first call `look_at_screen` with a concrete question. It sends the screenshot and returns visual coordinates.
2. For “take/send screenshot”, call `screenshot_xx`, then `send_photo` with the returned path.
3. For launching apps, first use `open_app` or `open_url`; only use tap/swipe after seeing the screen.
4. If `screenshot_xx` fails, call `touch_backend_status`, then inspect XXTouch logs or use `shell` to verify port `46952`.
5. When using shell, export PATH: `/var/jb/usr/bin:/var/jb/usr/local/bin:/var/jb/bin:/var/jb/var/mobile/.npm-global/bin:$PATH`.
6. Do not tell the user to manually take screenshots unless XXTouch and all alternatives are verified unavailable.

## Pitfalls
- Old screenshot files can be stale/root-owned; `screenshot_xx` should remove stale PNG first.
- `nLog()` output from XXTouch is not a reliable simple stdout; write data to files from Lua when debugging.
- Avoid relying on iOS Shortcuts CLI: `/var/jb/usr/bin/shortcuts` does not exist on this device.
