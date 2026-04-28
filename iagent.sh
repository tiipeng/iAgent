#!/bin/sh
# iagent — one command to drive everything: start, stop, attach, chat, setup,
# doctor, logs. Backs the daemon with tmux, which is the only reliable way
# to keep a Python process alive on iOS.

set -e

export IAGENT_HOME=/var/jb/var/mobile/iagent
export SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem
export PYTHONUNBUFFERED=1
# iOS locale DB is sparse — don't set LC_ALL/LANG globally because tmux
# validates them at startup and rejects anything not in the device's locale DB.
# We pass them inline to each command that actually needs UTF-8 output.

PY="$IAGENT_HOME/venv/bin/python"
CODE="$IAGENT_HOME/code"
SESSION=iagent

_have_session() {
    tmux has-session -t "$SESSION" 2>/dev/null
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
        # iOS locale DB is sparse. Unset everything except LC_CTYPE=UTF-8:
        # tmux only needs that single value to satisfy its UTF-8 check, and
        # it doesn't validate it against the locale DB the way en_US.UTF-8 is.
        unset LC_ALL LANG LC_MESSAGES LC_COLLATE LC_NUMERIC LC_TIME
        LC_CTYPE=UTF-8 tmux new-session -d -s "$SESSION" \
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
        unset LC_ALL LANG LC_MESSAGES LC_COLLATE LC_NUMERIC LC_TIME
        LC_CTYPE=UTF-8 exec tmux attach -t "$SESSION"
        ;;

    stop|kill)
        _require_tmux
        if _have_session; then
            tmux kill-session -t "$SESSION"
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
            pid=$(tmux list-panes -t "$SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
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

    help|--help|-h)
        _print_usage
        ;;

    *)
        echo "iagent: unknown command '$cmd'." >&2
        echo "Try 'iagent help'." >&2
        exit 1
        ;;
esac
