#!/var/jb/bin/sh
# iAgent daemon shim.
#
# launchd spawns this as root because iOS rootless does not accept
# UserName=mobile in system-domain plists. Running tick.py as root,
# however, gets the process SIGKILL'd by the iOS kernel before it
# can do any network I/O — a system-daemon sandbox quirk.
#
# This shim drops privileges to mobile via `sudo -u mobile`, so the
# actual Python process runs with the same context as a manual run
# from a NewTerm session, which works reliably.
set -e

IAGENT_HOME="/var/jb/var/mobile/iagent"

# Re-export the env vars the plist set, so they survive the sudo hop.
exec /var/jb/usr/bin/sudo -n -u mobile \
    IAGENT_HOME="$IAGENT_HOME" \
    SSL_CERT_FILE=/var/jb/etc/ssl/cert.pem \
    PYTHONUNBUFFERED=1 \
    HOME=/var/mobile \
    PATH=/var/jb/usr/bin:/var/jb/bin:/usr/bin:/bin \
    "$IAGENT_HOME/venv/bin/python" "$IAGENT_HOME/code/tick.py"
