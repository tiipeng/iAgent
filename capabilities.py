"""Capability registry — what's installed and what's not.

Persists to $IAGENT_HOME/capabilities.json. Doctor populates it.
apt_install invalidates it on changes. Tools query it via has_capability().
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))
REGISTRY_PATH = IAGENT_HOME / "capabilities.json"


def _empty() -> dict:
    return {"shortcuts": [], "apt": {}, "verified_at": None}


def load() -> dict:
    if not REGISTRY_PATH.exists():
        return _empty()
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except json.JSONDecodeError:
        return _empty()


def save(reg: dict) -> None:
    reg["verified_at"] = datetime.utcnow().isoformat() + "Z"
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2) + "\n")


def has_capability(name: str) -> bool:
    """Query a capability key like 'apt:pbcopy' or 'shortcut:iAgent: Notify'."""
    reg = load()
    if name.startswith("apt:"):
        pkg = name.split(":", 1)[1]
        return reg.get("apt", {}).get(pkg) == "installed"
    if name.startswith("shortcut:"):
        sc = name.split(":", 1)[1]
        return sc in reg.get("shortcuts", [])
    return False


def invalidate() -> None:
    """Drop the registry — forces a fresh probe on next access."""
    if REGISTRY_PATH.exists():
        REGISTRY_PATH.unlink()


# ── Probes (used by doctor / setup) ─────────────────────────────────────
def probe_apt(packages: list[str]) -> dict:
    """Return {pkg: 'installed' | 'missing'} for each package."""
    out: dict = {}
    if not shutil.which("dpkg-query") and not _find_in_jb("dpkg-query"):
        # No dpkg available — every package marked missing.
        return {p: "missing" for p in packages}

    dpkg = shutil.which("dpkg-query") or _find_in_jb("dpkg-query") or "dpkg-query"
    for pkg in packages:
        try:
            r = subprocess.run(
                [dpkg, "-W", "-f=${Status}", pkg],
                capture_output=True,
                text=True,
                check=False,
            )
            out[pkg] = "installed" if "install ok installed" in r.stdout else "missing"
        except Exception:
            out[pkg] = "missing"
    return out


def probe_shortcuts() -> Optional[list[str]]:
    """Return the list of installed shortcuts, or None if shortcuts CLI unavailable."""
    sc = shutil.which("shortcuts") or _find_in_jb("shortcuts")
    if not sc:
        return None
    try:
        r = subprocess.run([sc, "list"], capture_output=True, text=True, check=False, timeout=5)
        if r.returncode != 0:
            return None
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        return None


def _find_in_jb(name: str) -> Optional[str]:
    candidate = Path("/var/jb/usr/bin") / name
    return str(candidate) if candidate.exists() else None
