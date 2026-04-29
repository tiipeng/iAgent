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
        echo "[1/4] Setting up passwordless apt…"

        # Check if it already works
        if sudo -n /var/jb/usr/bin/apt --version >/dev/null 2>&1; then
            echo "      ✓ already working — sudo -n apt succeeds"
        else
            APT_BIN=$(command -v apt 2>/dev/null || echo /var/jb/usr/bin/apt)
            APT_GET=$(command -v apt-get 2>/dev/null || echo /var/jb/usr/bin/apt-get)
            MAIN_SUDOERS=/var/jb/etc/sudoers
            DROPIN=/var/jb/etc/sudoers.d/iagent
            RULE_LINE="mobile ALL=NOPASSWD: $APT_BIN, $APT_GET"

            echo "      apt: $APT_BIN"
            echo "      Rule: $RULE_LINE"
            printf "      Add it now? (will prompt for your password once) [Y/n] "
            read -r answer
            case "$answer" in
                ""|y|Y|yes|YES)
                    # Write to /etc/sudoers.d (modern style)
                    echo "$RULE_LINE" | sudo tee "$DROPIN" >/dev/null
                    sudo chmod 440 "$DROPIN"

                    # Ensure main sudoers actually includes sudoers.d
                    if ! sudo grep -qE '^[#@]includedir /var/jb/etc/sudoers.d' "$MAIN_SUDOERS" 2>/dev/null \
                       && ! sudo grep -qE '^[#@]includedir /etc/sudoers.d' "$MAIN_SUDOERS" 2>/dev/null; then
                        echo "      sudoers main file does not include sudoers.d — adding rule directly there as well"
                        if ! sudo grep -qF "$RULE_LINE" "$MAIN_SUDOERS" 2>/dev/null; then
                            echo "$RULE_LINE" | sudo tee -a "$MAIN_SUDOERS" >/dev/null
                        fi
                    fi
                    sudo -k     # flush cached credentials so the test below is honest
                    if sudo -n /var/jb/usr/bin/apt --version >/dev/null 2>&1; then
                        echo "      ✓ verified — passwordless apt works"
                    else
                        echo "      ⚠ rule added but sudo -n still asks for a password."
                        echo "        Step 2 below will prompt you once and continue regardless."
                        echo "        Diagnose later with:  sudo -l -U mobile | grep apt"
                    fi
                    ;;
                *) echo "      Skipped — apt_install will require a password." ;;
            esac
        fi

        # 2. Install support packages
        echo
        echo "[2/4] Installing support packages…"

        # Most jailbroken iPads have several third-party repos with unsigned
        # Release files. We tell apt to tolerate them so update doesn't fail.
        APT_OPTS="-o Acquire::AllowInsecureRepositories=true \
-o Acquire::AllowDowngradeToInsecureRepositories=true"

        # Pick sudo mode: -n if passwordless works, plain sudo otherwise.
        # Plain sudo will prompt once and cache credentials for the loop below.
        if sudo -n /var/jb/usr/bin/apt --version >/dev/null 2>&1; then
            SUDO="sudo -n"
        else
            echo "      (passwordless sudo not active — you'll be prompted once)"
            SUDO="sudo"
        fi

        printf "      apt update… "
        if $SUDO /var/jb/usr/bin/apt $APT_OPTS update >/dev/null 2>&1; then
            echo "ok"
        else
            echo "had warnings (unsigned repos) — continuing anyway"
        fi

        installed=0; skipped=0; failed=0; missing_optional=""
        try_install() {
            pkg=$1; required=$2
            printf "      installing %s … " "$pkg"
            output=$($SUDO /var/jb/usr/bin/apt $APT_OPTS install -y \
                    --allow-unauthenticated --no-install-recommends "$pkg" 2>&1)
            rc=$?
            if [ $rc -eq 0 ]; then
                if echo "$output" | grep -q "is already the newest version"; then
                    echo "already installed"; skipped=$((skipped+1))
                else
                    echo "ok"; installed=$((installed+1))
                fi
            elif echo "$output" | grep -q "Unable to locate package"; then
                if [ "$required" = "yes" ]; then
                    echo "MISSING (required, no repo has it)"
                    failed=$((failed+1))
                else
                    echo "not in any repo (optional)"
                    skipped=$((skipped+1))
                    missing_optional="$missing_optional $pkg"
                fi
            else
                echo "FAILED ($rc) — $(echo "$output" | tail -1)"
                failed=$((failed+1))
            fi
        }

        # Required: uikittools (uiopen, lsappinfo) — backbone for
        # open_url/open_app/list_apps tools.
        try_install uikittools yes

        # Optional helpers
        for pkg in uikittools-extra activator; do
            try_install "$pkg" no
        done

        # NOTE: com.witchan.ios-mcp despite its name is NOT an MCP server.
        # It's an AppSync rebrand. We don't install it. If you have a real
        # MCP server (stdio-speaking, JSON-RPC), add it manually to
        # config.json under mcp_servers.
        echo "      → $installed installed, $skipped skipped, $failed failed"
        if [ -n "$missing_optional" ]; then
            echo "      Optional packages not in any configured repo:$missing_optional"
            echo "      (slash commands still work, but report 'unavailable' for those features)"
        fi

        # 3. Probe configured MCP servers.
        # We don't auto-install anything claiming to be an MCP server — most
        # are misleading. We only probe what's already in config.json
        # mcp_servers and verify each binary actually speaks JSON-RPC.
        echo
        echo "[3/4] Verifying configured MCP servers…"

        # Read existing mcp_servers from config and probe each one
        SERVER_LIST=$("$PY" - "$IAGENT_HOME/config.json" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f: cfg = json.load(f)
for s in cfg.get("mcp_servers", []):
    print(f"{s.get('name','')}\t{s.get('command','')}")
PYEOF
)
        if [ -z "$SERVER_LIST" ]; then
            echo "      No MCP servers configured. iOS automation uses uikittools directly;"
            echo "      add an MCP server to config.json mcp_servers if you have one."
        else
            INIT_REQ='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"iAgent-probe","version":"1.0"}}}'
            BAD_NAMES=""
            while IFS=$'\t' read -r name command; do
                [ -z "$name" ] && continue
                printf "      %-20s [%s] … " "$name" "$command"
                if [ ! -x "$command" ]; then
                    echo "binary not found — removing"
                    BAD_NAMES="$BAD_NAMES $name"
                    continue
                fi
                resp=$(printf '%s\n' "$INIT_REQ" | timeout 2 "$command" 2>/dev/null | head -1)
                if echo "$resp" | grep -q '"jsonrpc":"2.0"' \
                   && (echo "$resp" | grep -q '"result"' || echo "$resp" | grep -q '"protocolVersion"'); then
                    echo "MCP ✓"
                else
                    echo "not an MCP server — removing"
                    BAD_NAMES="$BAD_NAMES $name"
                fi
            done <<EOFPROBE
$SERVER_LIST
EOFPROBE
            if [ -n "$BAD_NAMES" ]; then
                "$PY" - "$IAGENT_HOME/config.json" "$BAD_NAMES" <<'PYEOF'
import json, sys
path, bad = sys.argv[1], sys.argv[2].split()
with open(path) as f: cfg = json.load(f)
cfg["mcp_servers"] = [s for s in cfg.get("mcp_servers", []) if s.get("name") not in bad]
with open(path, "w") as f:
    json.dump(cfg, f, indent=2); f.write("\n")
print(f"      ✓ pruned {len(bad)} stale entries from mcp_servers")
PYEOF
            fi
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
