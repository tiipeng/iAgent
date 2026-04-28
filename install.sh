#!/var/jb/bin/sh
# iAgent installer for Dopamine rootless jailbreak (iOS 15–16, arm64e).
# Designed to run as the 'mobile' user; the LaunchDaemon step needs root
# and is printed as a sudo command for you to run afterwards.
set -e

IAGENT_SRC="$(cd "$(dirname "$0")" && pwd)"
IAGENT_HOME="/var/jb/var/mobile/iagent"
IAGENT_CODE="$IAGENT_HOME/code"
PLIST_NAME="com.tiipeng.iagent.plist"
PLIST_DEST="/var/jb/Library/LaunchDaemons/$PLIST_NAME"

# ── Locate Python (3.9+) ─────────────────────────────────────────────────
find_python() {
    for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
        bin="/var/jb/usr/bin/$candidate"
        if [ -x "$bin" ]; then
            echo "$bin"
            return
        fi
    done
    echo ""
}

PYTHON="$(find_python)"
if [ -z "$PYTHON" ]; then
    echo "ERROR: No python3 found in /var/jb/usr/bin/. Install via Sileo first."
    exit 1
fi

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' || {
    echo "ERROR: $PYTHON is too old. iAgent requires Python 3.9+."
    exit 1
}

VER=$("$PYTHON" -c "import sys; print('.'.join(map(str, sys.version_info[:3])))")
echo "[OK] Using Python $VER at $PYTHON"

# ── Create directories (all under user-writable IAGENT_HOME) ─────────────
echo "[1/5] Creating directories..."
mkdir -p "$IAGENT_HOME/logs"
mkdir -p "$IAGENT_HOME/workspace"
mkdir -p "$IAGENT_CODE"

# ── Seed config files if missing ─────────────────────────────────────────
if [ ! -f "$IAGENT_HOME/.env" ]; then
    cp "$IAGENT_SRC/.env.example" "$IAGENT_HOME/.env"
    chmod 600 "$IAGENT_HOME/.env"
    echo "      Created $IAGENT_HOME/.env (edit your tokens before starting)"
fi
if [ ! -f "$IAGENT_HOME/config.json" ]; then
    cp "$IAGENT_SRC/config/config.json.example" "$IAGENT_HOME/config.json"
    echo "      Created $IAGENT_HOME/config.json (edit allowed_user_ids)"
fi
# Clean up legacy YAML config from older installs
[ -f "$IAGENT_HOME/config.yaml" ] && rm -f "$IAGENT_HOME/config.yaml"

# ── Create virtualenv ────────────────────────────────────────────────────
echo "[2/5] Creating Python virtualenv..."
"$PYTHON" -m venv "$IAGENT_HOME/venv"

# ── Install dependencies ─────────────────────────────────────────────────
echo "[3/5] Installing Python dependencies (this may take a minute)..."
PIP="$IAGENT_HOME/venv/bin/pip"
export SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem
"$PIP" install --upgrade pip
# Prefer binary wheels; fall back to source only when no wheel matches.
"$PIP" install --prefer-binary -r "$IAGENT_SRC/requirements.txt"
echo "      Dependencies installed."

# ── Copy application code ────────────────────────────────────────────────
echo "[4/5] Installing application code to $IAGENT_CODE ..."
cp -R "$IAGENT_SRC/main.py" \
      "$IAGENT_SRC/tick.py" \
      "$IAGENT_SRC/chat.py" \
      "$IAGENT_SRC/setup.py" \
      "$IAGENT_SRC/doctor.py" \
      "$IAGENT_SRC/capabilities.py" \
      "$IAGENT_SRC/daemon_wrapper.sh" \
      "$IAGENT_SRC/iagent.sh" \
      "$IAGENT_SRC/config" \
      "$IAGENT_SRC/agent" \
      "$IAGENT_SRC/tools" \
      "$IAGENT_SRC/bot" \
      "$IAGENT_SRC/utils" \
      "$IAGENT_CODE/"

# Render thin launcher shims so the user can run ~/iagent/{chat,setup,doctor}
_render_launcher() {
    local name="$1"
    local script="$2"
    cat > "$IAGENT_HOME/$name" <<EOF
#!/var/jb/bin/sh
export IAGENT_HOME=/var/jb/var/mobile/iagent
export SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem
exec /var/jb/var/mobile/iagent/venv/bin/python /var/jb/var/mobile/iagent/code/$script "\$@"
EOF
    chmod +x "$IAGENT_HOME/$name"
}
_render_launcher chat   chat.py
_render_launcher setup  setup.py
_render_launcher doctor doctor.py

# The daemon wrapper must be executable for launchd to invoke it.
chmod +x "$IAGENT_CODE/daemon_wrapper.sh"

# Drop the unified `iagent` command at $IAGENT_HOME/iagent and make it the
# canonical launcher. Replaces the per-tool {chat,setup,doctor} shims.
cp "$IAGENT_CODE/iagent.sh" "$IAGENT_HOME/iagent"
chmod +x "$IAGENT_HOME/iagent"

# Make `iagent` callable from anywhere: add to ~/.zshrc PATH if not already.
ZSHRC="$HOME/.zshrc"
PATH_LINE='export PATH="/var/jb/var/mobile/iagent:$PATH"  # iagent'
if [ -f "$ZSHRC" ] && ! grep -q '/var/jb/var/mobile/iagent' "$ZSHRC" 2>/dev/null; then
    printf '\n%s\n' "$PATH_LINE" >> "$ZSHRC"
    echo "      Added iagent to PATH in $ZSHRC"
elif [ ! -f "$ZSHRC" ]; then
    printf '%s\n' "$PATH_LINE" > "$ZSHRC"
    echo "      Created $ZSHRC with iagent in PATH"
fi

# ── Render the LaunchDaemon plist with current paths ────────────────────
echo "[5/5] Rendering LaunchDaemon plist..."
RENDERED_PLIST="$IAGENT_HOME/$PLIST_NAME"
cp "$IAGENT_SRC/$PLIST_NAME" "$RENDERED_PLIST"

# ── Try to install the daemon if we have root, otherwise print sudo cmd ──
INSTALLED=0
if [ "$(id -u)" -eq 0 ]; then
    if launchctl list 2>/dev/null | grep -q "com.tiipeng.iagent"; then
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi
    cp "$RENDERED_PLIST" "$PLIST_DEST"
    chmod 644 "$PLIST_DEST"
    chown root:wheel "$PLIST_DEST"
    launchctl load "$PLIST_DEST"
    INSTALLED=1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " iAgent code installed to $IAGENT_CODE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# First-run? Auto-launch the setup wizard. It validates tokens, writes
# .env / config.json, and offers to install the LaunchDaemon.
if [ ! -f "$IAGENT_HOME/.env" ] || ! grep -q "^TELEGRAM_TOKEN=." "$IAGENT_HOME/.env" 2>/dev/null; then
    echo "First-time install — launching setup wizard…"
    echo ""
    "$IAGENT_HOME/setup"
else
    echo "Existing config detected. To reconfigure, run:  $IAGENT_HOME/setup"
    echo ""
    if [ "$INSTALLED" -eq 1 ]; then
        echo "Daemon reloaded with the latest code."
    else
        echo "Reload the daemon to pick up code changes:"
        echo "  sudo launchctl unload $PLIST_DEST"
        echo "  sudo launchctl load   $PLIST_DEST"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " The 'iagent' command is now installed."
echo " Open a NEW shell (or run: source ~/.zshrc) and try:"
echo ""
echo "   iagent          start the bot in tmux"
echo "   iagent attach   attach to the bot's session"
echo "   iagent stop     stop the bot"
echo "   iagent status   see if the bot is running"
echo "   iagent logs     tail the logs"
echo "   iagent chat     local CLI REPL (offline from Telegram)"
echo "   iagent doctor   health check"
echo "   iagent setup    re-run the setup wizard"
echo "   iagent help     full help"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "If 'iagent' is not found, install tmux from Sileo first:  apt install tmux"
