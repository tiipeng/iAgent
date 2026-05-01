# autonomous_troubleshooting
Use this skill whenever a command, service start, verification, package install, UI automation, or Homebridge/iOS task fails or gives an unexpected result.

Core policy: do not stop at the first failed command. Read the exact error, reproduce minimally, inspect logs/state/processes/ports/env, form one hypothesis, apply the smallest safe fix or wait/retry, then verify again. Ask the user only for physical input or secrets.

Verification discipline:
- If tmux windows exist but ports are closed, wait/retry up to 30 seconds and inspect logs before calling failure.
- If tmux says locale invalid, clear inherited LC_ALL with `unset LC_ALL` before setting `LC_CTYPE=UTF-8 LANG=en_US.UTF-8`.
- Do not suggest random packages like adv-cmds unless apt_search proves they exist and the error specifically requires them.
- On iOS/rootless, Linux assumptions are often wrong; prefer known local scripts and verified paths.
