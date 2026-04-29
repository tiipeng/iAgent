#!/bin/sh
# iagent — one command to drive everything: start, stop, attach, chat, setup,
# doctor, logs. Backs the daemon with tmux, which is the only reliable way
# to keep a Python process alive on iOS.

set -e

export IAGENT_HOME=/var/jb/var/mobile/iagent
export SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem
export PYTHONUNBUFFERED=1
# Unset all locale vars globally so every tmux call (list-sessions, kill-session,
# new-session, attach, …) passes tmux's locale check on iOS. Python processes
# get en_US.UTF-8 applied inline on their exec lines below.
unset LC_ALL LANG LC_CTYPE LC_MESSAGES LC_COLLATE LC_NUMERIC LC_TIME
export LC_CTYPE=UTF-8

PY="$IAGENT_HOME/venv/bin/python"
CODE="$IAGENT_HOME/code"
SESSION=iagent
# Dopamine's /tmp symlink resolves to a path > 100 chars, which exceeds the
# Unix socket name limit. Use a short explicit socket path instead.
TMUX_SOCK="$IAGENT_HOME/tmux.sock"

_have_session() {
    tmux -S "$TMUX_SOCK" has-session -t "$SESSION" 2>/dev/null
}

_require_tmux() {
    if ! command -v tmux >/dev/null 2>&1; then
        echo "tmux is not installed. Install it via Sileo:  apt search tmux" >&2
        echo "Or use 'iagent fg' to run in the foreground without tmux." >&2
        exit 1
    fi
}

_print_usage() {
    cat <<EOF
iagent — personal AI agent for jailbroken iOS

Usage:
  iagent             Start the bot (in tmux). If already running, attaches.
  iagent start       Same as 'iagent'.
  iagent attach      Attach to the running tmux session.
                     Detach again with Ctrl+B then D.
  iagent stop        Stop the bot.
  iagent restart     Stop + start.
  iagent status      Print whether the bot is running.
  iagent logs        Tail the log files (Ctrl+C to exit).
  iagent fg          Run the bot in the foreground in this shell.
                     Useful for debugging (you see exceptions live).

  iagent chat        Open the local CLI REPL (offline from Telegram).
  iagent setup       Re-run the interactive setup wizard.
  iagent doctor      Run the health check.
  iagent activate    Install support pkgs, add sudoers rule, wire ios-mcp,
                     restart. Idempotent — re-run any time. Run once after
                     a fresh install to unlock all features.
  iagent update      git pull + sh install.sh + restart. One-stop refresh.

  iagent help        Show this message.
EOF
}

cmd="${1:-start}"
case "$cmd" in
    start|run)
        _require_tmux
        if _have_session; then
            echo "iAgent is already running."
            echo "Attach with:  iagent attach"
            exit 0
        fi
        echo "Starting iAgent in tmux session '$SESSION'…"
        tmux -S "$TMUX_SOCK" new-session -d -s "$SESSION" \
            "LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 exec '$PY' '$CODE/main.py'"
        sleep 2
        if _have_session; then
            echo "✓ iAgent running."
            echo "  Attach:   iagent attach"
            echo "  Logs:     iagent logs"
            echo "  Stop:     iagent stop"
            echo
            echo "Tip: send a message to your bot in Telegram now."
        else
            echo "✗ Failed to start. The python process exited immediately." >&2
            echo "  Run 'iagent fg' to see the traceback." >&2
            exit 1
        fi
        ;;

    attach|a)
        _require_tmux
        if ! _have_session; then
            echo "iAgent is not running. Start it with:  iagent" >&2
            exit 1
        fi
        exec tmux -S "$TMUX_SOCK" attach -t "$SESSION"
        ;;

    stop|kill)
        _require_tmux
        if _have_session; then
            tmux -S "$TMUX_SOCK" kill-session -t "$SESSION"
            echo "iAgent stopped."
        else
            echo "iAgent is not running."
        fi
        ;;

    restart)
        "$0" stop || true
        sleep 1
        exec "$0" start
        ;;

    status)
        if _have_session 2>/dev/null; then
            pid=$(tmux -S "$TMUX_SOCK" list-panes -t "$SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
            echo "iAgent: running (tmux session '$SESSION', pane pid=$pid)"
        else
            echo "iAgent: stopped"
        fi
        ;;

    logs|log|tail)
        # Concat both log files since they capture different things.
        exec tail -f "$IAGENT_HOME/logs/stderr.log" "$IAGENT_HOME/logs/iagent.log" 2>/dev/null
        ;;

    fg|foreground|run-fg)
        echo "Running iAgent in foreground (Ctrl+C to stop)…"
        LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 exec "$PY" "$CODE/main.py"
        ;;

    chat)
        LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 exec "$PY" "$CODE/chat.py"
        ;;

    setup)
        exec "$PY" "$CODE/setup.py"
        ;;

    doctor)
        exec "$PY" "$CODE/doctor.py"
        ;;

    update|upgrade)
        # One-stop: locate source clone, git pull, run install.sh, restart.
        SRC=""
        for cand in "$HOME/iAgent" "/var/jb/var/mobile/iAgent" "/tmp/iagent_src"; do
            if [ -d "$cand/.git" ]; then SRC="$cand"; break; fi
        done
        if [ -z "$SRC" ]; then
            echo "No iAgent source clone found. Bootstrapping fresh from GitHub…"
            curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh
            exec "$0" restart
        fi
        echo "Source clone: $SRC"
        echo "[1/3] git pull…"
        (cd "$SRC" && git pull --rebase --autostash)
        echo "[2/3] install.sh…"
        (cd "$SRC" && sh install.sh)
        echo "[3/3] restarting bot…"
        exec "$0" restart
        ;;

    activate)
        # Idempotent: install support packages, sudoers rule, locate ios-mcp,
        # wire it into config, restart bot.
        echo "iAgent activate — wiring up everything Phase 1–4 needs."
        echo

        # 1. Sudoers rule for passwordless apt
        SUDOERS=/var/jb/etc/sudoers.d/iagent
        if [ ! -f "$SUDOERS" ]; then
            echo "[1/4] Adding passwordless apt sudoers rule (one-time, needs your password once)…"
            echo "      File: $SUDOERS"
            echo "      Rule: mobile ALL=NOPASSWD: /var/jb/usr/bin/apt"
            printf "      Continue? [Y/n] "
            read -r answer
            case "$answer" in
                ""|y|Y|yes|YES)
                    echo 'mobile ALL=NOPASSWD: /var/jb/usr/bin/apt' | sudo tee "$SUDOERS" >/dev/null
                    sudo chmod 440 "$SUDOERS"
                    echo "      ✓ sudoers rule added"
                    ;;
                *) echo "      Skipped — apt_install will fail until you add it manually." ;;
            esac
        else
            echo "[1/4] Sudoers rule already in place: $SUDOERS"
        fi

        # 2. Install support packages (best-effort; missing ones are skipped)
        echo
        echo "[2/4] Installing support packages…"

        # Most jailbroken iPads have several third-party repos with unsigned
        # Release files. We tell apt to tolerate them so update doesn't fail.
        APT_OPTS="-o Acquire::AllowInsecureRepositories=true \
-o Acquire::AllowDowngradeToInsecureRepositories=true"

        printf "      apt update… "
        if sudo -n /var/jb/usr/bin/apt $APT_OPTS update >/dev/null 2>&1; then
            echo "ok"
        else
            echo "had warnings (unsigned repos) — continuing anyway"
        fi

        for pkg in com.witchan.ios-mcp uikittools-ng upower wifiman screencapture-ios pbcopy; do
            printf "      installing %s … " "$pkg"
            if sudo -n /var/jb/usr/bin/apt $APT_OPTS install -y \
                    --allow-unauthenticated --no-install-recommends "$pkg" \
                    >/dev/null 2>&1; then
                echo "ok"
            else
                echo "skipped (not in repo or already installed)"
            fi
        done

        # 3. Locate ios-mcp and wire it into config.json
        echo
        echo "[3/4] Locating ios-mcp binary…"
        IOSMCP=""
        for cand in /var/jb/usr/bin/ios-mcp /var/jb/usr/bin/ios-mcp-server /var/jb/usr/local/bin/ios-mcp; do
            if [ -x "$cand" ]; then IOSMCP="$cand"; break; fi
        done
        if [ -z "$IOSMCP" ] && command -v dpkg >/dev/null 2>&1; then
            IOSMCP=$(dpkg -L com.witchan.ios-mcp 2>/dev/null \
                     | grep -E '/(bin|sbin)/' \
                     | head -1)
        fi

        if [ -n "$IOSMCP" ] && [ -x "$IOSMCP" ]; then
            echo "      Found: $IOSMCP"
            "$PY" - "$IAGENT_HOME/config.json" "$IOSMCP" <<'PYEOF'
import json, sys
path, binary = sys.argv[1], sys.argv[2]
with open(path) as f: cfg = json.load(f)
servers = cfg.get("mcp_servers", [])
# Replace any existing 'ios' entry, otherwise append
servers = [s for s in servers if s.get("name") != "ios"]
servers.append({"name": "ios", "command": binary})
cfg["mcp_servers"] = servers
with open(path, "w") as f:
    json.dump(cfg, f, indent=2); f.write("\n")
print(f"      ✓ wired '{binary}' into mcp_servers")
PYEOF
        else
            echo "      Not found. Install via Sileo or apt: sudo apt install com.witchan.ios-mcp"
            echo "      You can add it to config.json later under 'mcp_servers'."
        fi

        # 4. Restart bot
        echo
        echo "[4/4] Restarting bot…"
        "$0" restart
        echo
        echo "Done. Check 'iagent logs' for 'MCP \"ios\" connected' line."
        echo "In Telegram: /mcp to see registered tools."
        ;;

    help|--help|-h)
        _print_usage
        ;;

    *)
        echo "iagent: unknown command '$cmd'." >&2
        echo "Try 'iagent help'." >&2
        exit 1
        ;;
esac
