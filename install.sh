#!/var/jb/bin/sh
# iAgent installer for Dopamine rootless jailbreak (iOS 15–16, arm64e)
# Run via SSH: sh /tmp/iagent_src/install.sh
set -e

IAGENT_SRC="$(cd "$(dirname "$0")" && pwd)"
IAGENT_HOME="/var/jb/var/mobile/iagent"
IAGENT_CODE="/var/jb/usr/local/lib/iagent"
PLIST_DEST="/var/jb/Library/LaunchDaemons/com.tiipeng.iagent.plist"

# ── Locate Python 3.11+ ──────────────────────────────────────────────────
find_python() {
    for candidate in python3.12 python3.11; do
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
    echo ""
    echo "ERROR: Python 3.11 or 3.12 not found."
    echo "Open Sileo and install the 'python3.11' package from the Procursus repo, then re-run this script."
    exit 1
fi

VER=$("$PYTHON" -c "import sys; print(sys.version)")
echo "[OK] Found Python: $VER at $PYTHON"

# ── Create directories ───────────────────────────────────────────────────
echo "[1/6] Creating directories..."
mkdir -p "$IAGENT_HOME/logs"
mkdir -p "$IAGENT_HOME/workspace"
mkdir -p "$IAGENT_CODE"

# ── Create .env if missing ───────────────────────────────────────────────
if [ ! -f "$IAGENT_HOME/.env" ]; then
    cp "$IAGENT_SRC/.env.example" "$IAGENT_HOME/.env"
    echo "      Created $IAGENT_HOME/.env — edit it to add your tokens before starting!"
fi

# ── Create config.yaml if missing ───────────────────────────────────────
if [ ! -f "$IAGENT_HOME/config.yaml" ]; then
    cp "$IAGENT_SRC/config/config.yaml.example" "$IAGENT_HOME/config.yaml"
    echo "      Created $IAGENT_HOME/config.yaml — edit allowed_user_ids!"
fi

# ── Create virtualenv ────────────────────────────────────────────────────
echo "[2/6] Creating Python virtualenv..."
"$PYTHON" -m venv "$IAGENT_HOME/venv"

# ── Install dependencies ─────────────────────────────────────────────────
echo "[3/6] Installing Python dependencies..."
PIP="$IAGENT_HOME/venv/bin/pip"
"$PIP" install --upgrade pip --quiet
SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem \
    "$PIP" install -r "$IAGENT_SRC/requirements.txt" --quiet
echo "      Dependencies installed."

# ── Copy application code ────────────────────────────────────────────────
echo "[4/6] Installing application code..."
cp -r "$IAGENT_SRC/main.py" \
      "$IAGENT_SRC/config" \
      "$IAGENT_SRC/agent" \
      "$IAGENT_SRC/tools" \
      "$IAGENT_SRC/bot" \
      "$IAGENT_SRC/utils" \
      "$IAGENT_CODE/"
echo "      Code installed to $IAGENT_CODE"

# ── Install LaunchDaemon ─────────────────────────────────────────────────
echo "[5/6] Installing LaunchDaemon..."
if launchctl list | grep -q "com.tiipeng.iagent" 2>/dev/null; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi
cp "$IAGENT_SRC/com.tiipeng.iagent.plist" "$PLIST_DEST"
chmod 644 "$PLIST_DEST"
chown root:wheel "$PLIST_DEST"
echo "      Plist installed to $PLIST_DEST"

# ── Start the daemon ─────────────────────────────────────────────────────
echo "[6/6] Starting iAgent..."
launchctl load "$PLIST_DEST"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " iAgent installed and started!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "  1. Edit secrets:  nano $IAGENT_HOME/.env"
echo "     → Set TELEGRAM_TOKEN and OPENAI_API_KEY"
echo "  2. Edit config:   nano $IAGENT_HOME/config.yaml"
echo "     → Set your Telegram user ID in allowed_user_ids"
echo "  3. Restart daemon after editing:"
echo "     launchctl unload $PLIST_DEST"
echo "     launchctl load   $PLIST_DEST"
echo ""
echo "Logs:  tail -f $IAGENT_HOME/logs/stderr.log"
echo "Status: launchctl list | grep iagent"
