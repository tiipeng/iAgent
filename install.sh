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
if [ ! -f "$IAGENT_HOME/config.yaml" ]; then
    cp "$IAGENT_SRC/config/config.yaml.example" "$IAGENT_HOME/config.yaml"
    echo "      Created $IAGENT_HOME/config.yaml (edit allowed_user_ids)"
fi

# ── Create virtualenv ────────────────────────────────────────────────────
echo "[2/5] Creating Python virtualenv..."
"$PYTHON" -m venv "$IAGENT_HOME/venv"

# ── Install dependencies ─────────────────────────────────────────────────
echo "[3/5] Installing Python dependencies (this may take a minute)..."
PIP="$IAGENT_HOME/venv/bin/pip"
SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem "$PIP" install --upgrade pip --quiet
SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem "$PIP" install -r "$IAGENT_SRC/requirements.txt" --quiet
echo "      Dependencies installed."

# ── Copy application code ────────────────────────────────────────────────
echo "[4/5] Installing application code to $IAGENT_CODE ..."
cp -R "$IAGENT_SRC/main.py" \
      "$IAGENT_SRC/config" \
      "$IAGENT_SRC/agent" \
      "$IAGENT_SRC/tools" \
      "$IAGENT_SRC/bot" \
      "$IAGENT_SRC/utils" \
      "$IAGENT_CODE/"

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
echo "1. Edit secrets:   nano $IAGENT_HOME/.env"
echo "                    → TELEGRAM_TOKEN and OPENAI_API_KEY"
echo ""
echo "2. Edit allowlist: nano $IAGENT_HOME/config.yaml"
echo "                    → put your Telegram user ID under allowed_user_ids"
echo ""

if [ "$INSTALLED" -eq 1 ]; then
    echo "3. Daemon already loaded as root. Restart it after editing:"
    echo "     launchctl unload $PLIST_DEST"
    echo "     launchctl load   $PLIST_DEST"
else
    echo "3. Install the LaunchDaemon (needs root). Copy/paste:"
    echo ""
    echo "     sudo cp $RENDERED_PLIST $PLIST_DEST"
    echo "     sudo chown root:wheel $PLIST_DEST"
    echo "     sudo chmod 644 $PLIST_DEST"
    echo "     sudo launchctl load $PLIST_DEST"
    echo ""
    echo "   (If 'sudo' is missing, install it from Sileo first.)"
fi

echo ""
echo "Logs:    tail -f $IAGENT_HOME/logs/stderr.log"
echo "Status:  launchctl list | grep iagent"
