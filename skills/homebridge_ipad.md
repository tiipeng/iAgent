# homebridge_ipad
Use this when managing Homebridge, Homebridge Config UI X, plugins, Ring, Samsung TV, Dyson, or HomeKit on the jailbroken iPad.

## Known working state
- Homebridge v1.11.4, config dir `/var/mobile/homebridge`.
- Config: `/var/mobile/homebridge/config.json`.
- Logs: `/var/mobile/homebridge/homebridge.log` and `/var/mobile/homebridge/homebridge-ui.log`.
- Homebridge port: `51826`; UI port: `8581`.
- Homebridge Config UI X working version: `homebridge-config-ui-x@4.65.0`.
- Run via tmux, not LaunchDaemon: socket `/var/mobile/homebridge/tmux.sock`, session `homebridge`, windows `hb` and `ui`.
- Start: `/var/mobile/homebridge/start-hb-tmux.sh`; stop: `/var/mobile/homebridge/stop-hb-tmux.sh`.
- HomeKit PIN/setup code exists but is secret; never print it.

## Required environment
```sh
export PATH=/var/jb/usr/bin:/var/jb/usr/local/bin:/var/jb/bin:/var/jb/var/mobile/.npm-global/bin:$PATH
export HOME=/var/mobile
export LC_CTYPE=UTF-8
export LANG=en_US.UTF-8
export npm_config_prefix=/var/jb/var/mobile/.npm-global
```

## Plugin install pattern
1. Do not trust the UI plugin installer on iOS; it hides npm failures.
2. Install manually from `/var/mobile/homebridge`:
```sh
cd /var/mobile/homebridge
npm install <plugin>@<version> --force --ignore-scripts --unsafe-perm
```
3. Homebridge must scan both plugin paths:
```sh
-P /var/jb/var/mobile/.npm-global/lib/node_modules -P /var/mobile/homebridge/node_modules
```
4. Config UI standalone should use local plugin path as `-P` and include both global/local in `NODE_PATH`.
5. Restart via `/var/mobile/homebridge/start-hb-tmux.sh` and verify logs.

## Ring
- Installed plugin: `homebridge-ring@13.2.0` locally under `/var/mobile/homebridge/node_modules`.
- Ring requires a `refreshToken`; do not ask for or print Ring password/token in chat.
- Use Homebridge UI Ring login flow or ring auth CLI if needed.
- Ring logs should show `Loaded plugin: homebridge-ring@13.2.0` and `Registering platform 'homebridge-ring.Ring'`.

## Samsung The Frame 2024
- Discovered TV example: `75" The Frame`, model `QE75LS03DAUXXN`, IP `192.168.2.36`, Tizen, FrameTVSupport true.
- Prefer `homebridge-samsung-tizen@5.3.3` on Node 18; latest may require Node 20.
- TV must be ON/awake; user must accept Samsung pairing popup.
- Plugin publishes TV as external HomeKit accessory; user may add via Home App → Add Accessory → More Options.

## Dyson
- Use Homebridge plugin discovery carefully; inspect plugin Node engine/dependencies before installing.
- Prefer versions compatible with Node 18 and install manually with `--force --ignore-scripts --unsafe-perm`.
- Treat Dyson account tokens/passwords as secrets.

## Verification
```sh
/var/mobile/homebridge/start-hb-tmux.sh
LC_CTYPE=UTF-8 LANG=en_US.UTF-8 /var/jb/usr/bin/tmux -S /var/mobile/homebridge/tmux.sock list-windows -t homebridge
for p in 51826 8581; do ncat -z -w 2 127.0.0.1 $p && echo "$p OPEN" || echo "$p CLOSED"; done
grep -Ein 'plugin|Ring|Samsung|Tizen|Dyson|error|warn' /var/mobile/homebridge/homebridge.log | tail -160
```

## Pitfalls
- iOS has no writable `/bin/sh`; Node packages using shell commands may need source patches.
- Config UI X v5 crashes on this iPad; use v4.65.0.
- `node-pty` native module is stubbed; web terminal in UI is disabled.
- tmux requires `LC_CTYPE=UTF-8 LANG=en_US.UTF-8` and the short socket path.

## Starting Homebridge with tmux: exact working command

If asked to start the Homebridge gateway/Homebridge with tmux, do **not** inspect or install locales and do **not** install `adv-cmds`. The locale issue is already solved by setting environment variables inline.

Use the existing script first:

```sh
/var/mobile/homebridge/start-hb-tmux.sh
```

Then verify:

```sh
LC_CTYPE=UTF-8 LANG=en_US.UTF-8 /var/jb/usr/bin/tmux -S /var/mobile/homebridge/tmux.sock list-windows -t homebridge
/var/jb/usr/bin/python3 - <<'PY'
import socket
for port in (51826,8581):
    s=socket.socket(); s.settimeout(2)
    try:
        s.connect(('127.0.0.1', port)); print(port, 'OPEN')
    except Exception as e:
        print(port, 'CLOSED', e)
    finally:
        s.close()
PY
```

If tmux must be called manually, always use both the UTF-8 locale variables and the short socket path:

```sh
LC_CTYPE=UTF-8 LANG=en_US.UTF-8 /var/jb/usr/bin/tmux -S /var/mobile/homebridge/tmux.sock new-session -d -s homebridge -n hb
```

Never respond that `adv-cmds` is required for this. It is not required. On this rootless iPad, available locale discovery commands may be missing; the working fix is simply `LC_CTYPE=UTF-8 LANG=en_US.UTF-8`.

