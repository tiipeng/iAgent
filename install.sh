#!/var/jb/bin/sh
# iAgent installer for Dopamine rootless jailbreak (iOS 15–16, arm64e).
# Runs as the 'mobile' user, no sudo required.
set -e

IAGENT_SRC="$(cd "$(dirname "$0")" && pwd)"
IAGENT_HOME="/var/jb/var/mobile/iagent"
IAGENT_CODE="$IAGENT_HOME/code"

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
echo "[1/4] Creating directories..."
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
else
    # Backfill apt_install_enabled=true if the existing config still has false
    if grep -q '"apt_install_enabled": false' "$IAGENT_HOME/config.json" 2>/dev/null; then
        sed -i 's/"apt_install_enabled": false/"apt_install_enabled": true/' "$IAGENT_HOME/config.json"
        echo "      Enabled apt_install in existing config.json"
    fi
fi
# Clean up legacy YAML config from older installs
[ -f "$IAGENT_HOME/config.yaml" ] && rm -f "$IAGENT_HOME/config.yaml"

# ── Create virtualenv ────────────────────────────────────────────────────
echo "[2/4] Creating Python virtualenv..."
"$PYTHON" -m venv "$IAGENT_HOME/venv"

# ── Install dependencies ─────────────────────────────────────────────────
echo "[3/4] Installing Python dependencies (this may take a minute)..."
PIP="$IAGENT_HOME/venv/bin/pip"
export SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem
"$PIP" install --upgrade pip
# Prefer binary wheels; fall back to source only when no wheel matches.
"$PIP" install --prefer-binary -r "$IAGENT_SRC/requirements.txt"
echo "      Dependencies installed."

# ── Copy application code ────────────────────────────────────────────────
echo "[4/4] Installing application code to $IAGENT_CODE ..."
cp -R "$IAGENT_SRC/main.py" \
      "$IAGENT_SRC/chat.py" \
      "$IAGENT_SRC/setup.py" \
      "$IAGENT_SRC/doctor.py" \
      "$IAGENT_SRC/capabilities.py" \
      "$IAGENT_SRC/iagent.sh" \
      "$IAGENT_SRC/config" \
      "$IAGENT_SRC/agent" \
      "$IAGENT_SRC/tools" \
      "$IAGENT_SRC/bot" \
      "$IAGENT_SRC/utils" \
      "$IAGENT_SRC/skills" \
      "$IAGENT_CODE/"

# Drop the unified `iagent` command at $IAGENT_HOME/iagent.
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

# Clean up artifacts from older daemon-based installs
rm -f "$IAGENT_HOME/com.tiipeng.iagent.plist" 2>/dev/null
rm -f "$IAGENT_HOME/chat" "$IAGENT_HOME/setup" "$IAGENT_HOME/doctor" 2>/dev/null
rm -f "$IAGENT_CODE/tick.py" "$IAGENT_CODE/daemon_wrapper.sh" 2>/dev/null

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " iAgent installed to $IAGENT_CODE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# First-run: launch the setup wizard automatically.
if [ ! -f "$IAGENT_HOME/.env" ] || ! grep -q "^TELEGRAM_TOKEN=." "$IAGENT_HOME/.env" 2>/dev/null; then
    echo "First-time install — launching setup wizard…"
    echo ""
    "$IAGENT_HOME/iagent" setup
else
    echo "Existing config detected. To reconfigure: iagent setup"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
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
echo "Need tmux? Install it via Sileo:  sudo apt install tmux"
