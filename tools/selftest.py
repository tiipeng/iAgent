from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from tools.registry import register
from tools.ops_journal import make_event, record_event
from tools.shell_env import base_env, ios_env_prefix, shell_path

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))


def _code_path(*parts: str) -> Path:
    """Return a source path in either deployed (`code/...`) or repo-flat layout."""
    deployed = _IAGENT_HOME / "code" / Path(*parts)
    if deployed.exists():
        return deployed
    return _IAGENT_HOME / Path(*parts)


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def _run(command: str, timeout: float = 10.0) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [shell_path(), "-c", ios_env_prefix() + command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=base_env(),
        )
        return {"exit_code": proc.returncode, "output": proc.stdout.strip()}
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {"exit_code": 124, "output": (out + f"\n[timed out after {timeout}s]").strip()}
    except Exception as exc:
        return {"exit_code": 125, "output": f"{type(exc).__name__}: {exc}"}


def make_check(name: str, status: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    if status not in {"ok", "warn", "fail", "skip"}:
        status = "fail"
        message = f"Invalid check status from selftest: {status}. Original message: {message}"
    return {"name": name, "status": status, "message": message, "details": details or {}}


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for check in checks:
        counts[check.get("status", "fail")] = counts.get(check.get("status", "fail"), 0) + 1
    status = "fail" if counts.get("fail") else "warn" if counts.get("warn") else "ok"
    return {"status": status, "counts": counts, "total": len(checks)}


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _http_get(url: str, timeout: float = 2.0) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read(512).decode("utf-8", "replace")
            return int(resp.status), data
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def check_iagent_runtime() -> dict[str, Any]:
    required = [
        _code_path("agent", "context.py"),
        _code_path("agent", "memory.py"),
        _code_path("tools", "services.py"),
        _IAGENT_HOME / "scripts" / "regression_check.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    cfg_ok = False
    cfg_details: dict[str, Any] = {}
    try:
        cfg_path = _IAGENT_HOME / "config.json"
        if not cfg_path.exists():
            cfg_path = _IAGENT_HOME / "config" / "config.json.example"
        cfg = json.loads(cfg_path.read_text())
        cfg_details = {k: cfg.get(k) for k in ("history_window", "max_iterations", "shell_timeout")}
        cfg_ok = int(cfg.get("history_window", 0)) >= 20 and int(cfg.get("max_iterations", 0)) >= 10
    except Exception as exc:
        cfg_details = {"error": f"{type(exc).__name__}: {exc}"}
    tmux = _run(f"/var/jb/usr/bin/tmux -S {_IAGENT_HOME}/tmux.sock has-session -t iagent 2>&1", timeout=5)
    details = {"missing": missing, "config": cfg_details, "tmux_exit_code": tmux["exit_code"], "tmux_output": tmux["output"][:300]}
    if missing:
        return make_check("iagent_runtime", "fail", "Required iAgent runtime files are missing.", details)
    if not cfg_ok:
        return make_check("iagent_runtime", "warn", "iAgent config exists but autonomy limits look lower than expected.", details)
    if tmux["exit_code"] != 0:
        return make_check("iagent_runtime", "warn", "iAgent files/config are OK, but tmux session was not confirmed.", details)
    return make_check("iagent_runtime", "ok", "iAgent runtime files, config, and tmux session look healthy.", details)


def check_tool_registry() -> dict[str, Any]:
    # Import modules with registered tools. Importing is idempotent; schemas may contain duplicates only in odd test reload cases.
    import tools.services  # noqa: F401
    import tools.self_debug  # noqa: F401
    import tools.selftest  # noqa: F401
    import tools.registry as registry
    names = [s["function"]["name"] for s in registry.get_schemas()]
    expected = {"diagnose_service", "troubleshoot_service", "repair_service", "inspect_service_listeners", "run_selftest", "restart_self"}
    missing = sorted(expected.difference(names))
    details = {"expected": sorted(expected), "missing": missing, "registered_count": len(names)}
    if missing:
        return make_check("tool_registry", "fail", "Some critical iAgent tools are not registered.", details)
    return make_check("tool_registry", "ok", "Critical service and self-management tools are registered.", details)


def check_homebridge_service(live: bool = True) -> dict[str, Any]:
    if not live:
        return make_check("homebridge_service", "skip", "Live Homebridge diagnosis skipped.", {})
    try:
        from tools.services import diagnose_service_sync
        diag = diagnose_service_sync("homebridge")
    except Exception as exc:
        return make_check("homebridge_service", "fail", "Homebridge diagnosis raised an exception.", {"error": f"{type(exc).__name__}: {exc}"})
    status = diag.get("status")
    details = {"status": status, "ports": diag.get("ports"), "tmux": diag.get("tmux"), "next_action": diag.get("next_action")}
    if status == "running":
        return make_check("homebridge_service", "ok", "Homebridge runbook diagnosis is healthy.", details)
    if status == "starting_or_partial":
        return make_check("homebridge_service", "warn", "Homebridge is partially up; repair/troubleshoot may be needed.", details)
    return make_check("homebridge_service", "fail", "Homebridge is not healthy.", details)


def check_xxtouch(live: bool = True) -> dict[str, Any]:
    if not live:
        return make_check("xxtouch_http", "skip", "Live XXTouch HTTP check skipped.", {})
    code, body = _http_get("http://127.0.0.1:46952/", timeout=2.0)
    details = {"http_status": code, "body_prefix": body[:120]}
    if code == 200:
        return make_check("xxtouch_http", "ok", "XXTouch HTTP API is reachable.", details)
    return make_check("xxtouch_http", "warn", "XXTouch HTTP API is not reachable; screen/tap tools may fail.", details)


def check_ios_mcp(live: bool = True) -> dict[str, Any]:
    if not live:
        return make_check("ios_mcp_http", "skip", "Live ios-mcp HTTP check skipped.", {})
    code, body = _http_get("http://127.0.0.1:8090/health", timeout=2.0)
    details = {"http_status": code, "body_prefix": body[:200]}
    if code == 200 and "ok" in body.lower():
        return make_check("ios_mcp_http", "ok", "ios-mcp /health is reachable.", details)
    return make_check("ios_mcp_http", "warn", "ios-mcp /health is not reachable.", details)


def check_battery_probe(live: bool = True) -> dict[str, Any]:
    if not live:
        return make_check("battery_probe", "skip", "Live battery probe skipped.", {})
    res = _run("ioreg -r -c AppleSmartBattery 2>/dev/null | grep -E '\"CurrentCapacity\"|\"IsCharging\"|\"ExternalConnected\"'", timeout=8)
    output = res.get("output", "")
    details = {"exit_code": res.get("exit_code"), "output_prefix": output[:300]}
    if res.get("exit_code") == 0 and "CurrentCapacity" in output:
        return make_check("battery_probe", "ok", "Battery information is available via ioreg fallback.", details)
    return make_check("battery_probe", "warn", "Battery ioreg probe did not return expected fields.", details)


def check_history_sanitizer() -> dict[str, Any]:
    path = _code_path("agent", "memory.py")
    try:
        text = path.read_text(errors="replace")
    except Exception as exc:
        return make_check("history_sanitizer", "fail", "Could not read memory.py.", {"error": f"{type(exc).__name__}: {exc}"})
    markers = ["tool_calls", 'role == "tool"', "orphan", "sanitize", "tool"]
    hits = [m for m in markers if m in text]
    details = {"markers_found": hits, "path": str(path)}
    if "tool" in text and ("tool_calls" in text or "orphan" in text or "sanitize" in text):
        return make_check("history_sanitizer", "ok", "Memory/history code contains tool-message sanitization safeguards.", details)
    return make_check("history_sanitizer", "warn", "Could not confirm tool-message history sanitizer markers in memory.py.", details)


def selftest_sync(live: bool = True) -> dict[str, Any]:
    checks = [
        check_iagent_runtime(),
        check_tool_registry(),
        check_homebridge_service(live=live),
        check_xxtouch(live=live),
        check_ios_mcp(live=live),
        check_battery_probe(live=live),
        check_history_sanitizer(),
    ]
    summary = _summarize(checks)
    result = {
        "component": "iagent_selftest",
        "status": summary["status"],
        "summary": summary,
        "checks": checks,
        "timestamp": int(time.time()),
        "live": live,
    }
    if live:
        record_event(make_event(
            "selftest",
            result["status"],
            f"selftest {result['status']} ({summary['counts'].get('ok', 0)} ok, {summary['counts'].get('warn', 0)} warn, {summary['counts'].get('fail', 0)} fail)",
            component="iagent",
            details={"summary": summary, "checks": checks},
            timestamp=result["timestamp"],
        ))
    return result


@register({
    "name": "run_selftest",
    "description": "Run Sprint-4 iAgent self-test: runtime/config, critical tool registry, Homebridge health, XXTouch HTTP, ios-mcp health, battery fallback, and history sanitizer markers. Does not change state.",
    "parameters": {"type": "object", "properties": {"live": {"type": "boolean", "default": True, "description": "If false, skip network/runtime probes and only run static checks."}}, "required": []},
})
async def run_selftest(live: bool = True) -> str:
    return _json(await asyncio.to_thread(selftest_sync, live))
