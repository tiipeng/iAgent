from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = ":".join([
    "/var/jb/usr/bin",
    "/var/jb/usr/local/bin",
    "/var/jb/bin",
    "/var/jb/var/mobile/.npm-global/bin",
    "$PATH",
])


def ios_env_prefix(extra_path: str | None = None) -> str:
    """Return a shell prefix that makes commands reliable on rootless iOS.

    Important: `LC_ALL` overrides LC_CTYPE/LANG. If it is inherited with an
    invalid value, tmux fails with "invalid LC_ALL, LC_CTYPE or LANG". Always
    unset it before setting the UTF-8 variables.
    """
    path = DEFAULT_PATH if not extra_path else f"{extra_path}:" + DEFAULT_PATH
    return (
        "unset LC_ALL; "
        "export LC_CTYPE=UTF-8; "
        "export LANG=en_US.UTF-8; "
        f"export PATH={path}; "
        "export HOME=/var/mobile; "
        "export npm_config_prefix=/var/jb/var/mobile/.npm-global; "
    )


def shell_path() -> str:
    for candidate in ("/var/jb/bin/sh", "/var/jb/usr/bin/sh", "/bin/sh"):
        if Path(candidate).exists():
            return candidate
    return "/var/jb/bin/sh"


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("LC_ALL", None)
    env.update({
        "LC_CTYPE": "UTF-8",
        "LANG": "en_US.UTF-8",
        "HOME": "/var/mobile",
        "npm_config_prefix": "/var/jb/var/mobile/.npm-global",
    })
    env["PATH"] = ":".join([
        "/var/jb/usr/bin",
        "/var/jb/usr/local/bin",
        "/var/jb/bin",
        "/var/jb/var/mobile/.npm-global/bin",
        env.get("PATH", ""),
    ])
    return env
