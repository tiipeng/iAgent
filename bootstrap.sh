#!/var/jb/bin/sh
# iAgent on-device bootstrap. Run directly on the jailbroken iPad:
#
#   curl -fsSL https://raw.githubusercontent.com/tiipeng/iAgent/main/bootstrap.sh | sh
#
# This clones the repo to /tmp/iagent_src and then runs install.sh.
set -e

REPO_URL="https://github.com/tiipeng/iAgent.git"
# Clone to a stable, user-writable path so the user can `cd ~/iAgent && git pull`
# later without re-running the curl one-liner. /tmp on Dopamine resolves to
# /private/preboot/<hash>/... and is volatile — don't put the source there.
SRC_DIR="$HOME/iAgent"

# ── Check prerequisites (Sileo-installable) ──────────────────────────────
need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: '$1' is not installed. Install it via Sileo first."
        exit 1
    fi
}
need git
need curl

# ── Clone or update ──────────────────────────────────────────────────────
if [ -d "$SRC_DIR/.git" ]; then
    echo "[bootstrap] Updating existing checkout in $SRC_DIR..."
    git -C "$SRC_DIR" fetch --quiet origin
    git -C "$SRC_DIR" reset --hard --quiet origin/main
else
    echo "[bootstrap] Cloning $REPO_URL → $SRC_DIR..."
    rm -rf "$SRC_DIR"
    git clone --depth=1 "$REPO_URL" "$SRC_DIR"
fi

echo "[bootstrap] Handing off to install.sh..."
exec sh "$SRC_DIR/install.sh"
