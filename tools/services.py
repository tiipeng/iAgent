from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from tools.registry import register
from tools.shell_env import base_env, ios_env_prefix, shell_path
from tools.ops_journal import make_event, record_event

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", "/var/jb/var/mobile/iagent"))
_RUNBOOK_DIR = _IAGENT_HOME / "runbooks"


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def load_runbook(name: str) -> dict[str, Any]:
    slug = name.strip().lower().replace(" ", "_")
    path = _RUNBOOK_DIR / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"Runbook not found: {path}")
    data = json.loads(path.read_text())
    data["_path"] = str(path)
    return data


def _run(command: str, timeout: float = 30.0) -> dict[str, Any]:
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



def parse_listener_output(output: str) -> list[dict[str, Any]]:
    listeners: list[dict[str, Any]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("command"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        m = re.search(r":(\d{2,5})(?:\s|\(|$)", stripped)
        port = int(m.group(1)) if m else None
        listeners.append({"command": parts[0], "pid": pid, "port": port, "raw": line})
    return listeners


def parse_tmux_window_health(raw: str, expected: list[str] | None = None) -> dict[str, Any]:
    expected = expected or []
    windows: list[str] = []
    dead_panes: list[str] = []
    for line in raw.splitlines():
        if ":" not in line:
            continue
        name = line.split(":", 1)[1].split()[0].strip("-*+")
        if name:
            windows.append(name)
            if "dead" in line.lower() or "exited" in line.lower():
                dead_panes.append(name)
    missing = [w for w in expected if w not in windows]
    return {"ok": not missing and not dead_panes, "windows": windows, "expected": expected, "missing": missing, "dead_panes": dead_panes, "raw": raw}


def plan_targeted_cleanup(service: str, listeners: list[dict[str, Any]]) -> dict[str, Any]:
    commands: list[str] = []
    for item in listeners:
        pid = item.get("pid")
        if pid:
            commands.append(f"kill -TERM {pid}  # {item.get('command')} on port {item.get('port')}")
    return {"service": service, "action": "manual_targeted_cleanup", "safe_to_auto_run": False, "listeners": listeners, "commands": commands, "reason": "Port conflict cleanup must target exact PIDs; broad grep/kill and kill -9 are avoided."}

def _tmux_windows(rb: dict[str, Any]) -> dict[str, Any]:
    tmux = rb.get("tmux") or {}
    socket_path = tmux.get("socket")
    session = tmux.get("session")
    if not socket_path or not session:
        return {"configured": False, "ok": False, "windows": [], "raw": ""}
    result = _run(f"/var/jb/usr/bin/tmux -S {socket_path} list-windows -t {session} 2>&1", timeout=8)
    parsed = parse_tmux_window_health(result["output"], expected=tmux.get("windows") or [])
    parsed.update({"configured": True, "exit_code": result["exit_code"], "ok": result["exit_code"] == 0 and parsed["ok"]})
    return parsed


def _tail_logs(rb: dict[str, Any], lines: int = 40) -> dict[str, str]:
    logs: dict[str, str] = {}
    for path in rb.get("logs", []):
        p = Path(path)
        if p.exists():
            logs[path] = "\n".join(p.read_text(errors="replace").splitlines()[-lines:])
        else:
            logs[path] = "[missing]"
    return logs


def _all_log_text(diag: dict[str, Any]) -> str:
    return "\n".join(str(v) for v in (diag.get("logs") or {}).values())


def classify_service_issue(diag: dict[str, Any], rb: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify service state into known issue codes and confidence.

    Pure function so it can be regression-tested with synthetic diagnostics.
    """
    rb = rb or {}
    text = _all_log_text(diag)
    low = text.lower()
    issues: list[dict[str, Any]] = []

    def add(code: str, severity: str, evidence: str, explanation: str, safe: bool, recommendation: str):
        issues.append({
            "code": code,
            "severity": severity,
            "evidence": evidence[:500],
            "explanation": explanation,
            "safe_remediation_available": safe,
            "recommendation": recommendation,
        })

    if "invalid lc_all" in low or "invalid lc_ctype" in low or "invalid lc_all, lc_ctype or lang" in low:
        add(
            "invalid_locale", "critical", "tmux invalid locale",
            "tmux inherited an invalid LC_ALL/locale. LC_ALL overrides LC_CTYPE/LANG.",
            True, "run through shell_env/start script which unsets LC_ALL before setting UTF-8 locale",
        )
    if "eaddrinuse" in low or "address already in use" in low:
        m = re.search(r"(?:port|listen|:)(\d{4,5})", text, flags=re.I)
        port = m.group(1) if m else "unknown"
        add(
            "port_in_use", "critical", f"port {port} already in use",
            "A previous/orphan process probably still owns a required port.",
            False, "diagnose processes/listeners; perform targeted cleanup only, then restart",
        )
    if "exit:138" in low or "sigbus" in low:
        add(
            "ui_v5_sigbus", "critical", "EXIT:138/SIGBUS",
            "Homebridge Config UI X v5 is unstable on this iPad/Node runtime.",
            False, "keep/downgrade to homebridge-config-ui-x@4.65.0; do not reinstall v5",
        )
    if "plugin is not configured" in low and "[ring" in low:
        add(
            "ring_not_configured", "warning", "[Ring] Plugin is not configured",
            "Ring plugin is loaded but has no valid refreshToken yet.",
            False, "complete Ring auth in UI/CLI and add refreshToken as a secret",
        )
    if "failed to pair" in low and "allow" in low:
        add(
            "samsung_pairing_waiting", "warning", "Failed to pair / Allow popup",
            "Samsung TV local plugin needs the TV awake and the Allow popup accepted.",
            False, "wake TV and accept Allow popup physically",
        )

    ports = diag.get("ports") or {}
    tmux = diag.get("tmux") or {}
    closed = [p for p, state in ports.items() if state != "open"]
    if diag.get("status") == "starting_or_partial" and tmux.get("ok") and closed:
        add(
            "ports_not_ready", "info", f"closed ports: {', '.join(closed)}",
            "tmux windows exist but service ports are not open yet; this is often normal during startup.",
            True, "wait_for_ports before declaring failure",
        )
    if diag.get("status") == "stopped_or_crashed" and not any(state == "open" for state in ports.values()):
        add(
            "service_stopped", "warning", "all expected ports closed",
            "Service appears stopped or crashed.",
            True, "start_service using the runbook, then re-diagnose",
        )
    dead = (diag.get("tmux") or {}).get("dead_panes") or []
    if dead:
        add(
            "dead_tmux_pane", "critical", f"dead panes: {', '.join(dead)}",
            "One or more expected tmux windows exist but their pane has died.",
            True, "restart the service through its runbook and re-diagnose",
        )

    severity_order = {"info": 0, "warning": 1, "critical": 2}
    severity = "info"
    for issue in issues:
        if severity_order[issue["severity"]] > severity_order[severity]:
            severity = issue["severity"]
    if not issues and diag.get("status") == "running":
        add("healthy", "info", "status running", "Service is healthy.", False, "no action needed")
    return {"severity": severity, "issues": issues}


def plan_service_next_action(diag: dict[str, Any], analysis: dict[str, Any], rb: dict[str, Any] | None = None) -> dict[str, Any]:
    rb = rb or {}
    codes = [i.get("code") for i in analysis.get("issues", [])]
    ports = [int(p) for p in (rb.get("ports") or diag.get("ports") or [])]
    if "healthy" in codes or diag.get("status") == "running":
        return {"action": "none", "safe_to_auto_run": False, "reason": "service is healthy", "command": None}
    if "ports_not_ready" in codes:
        return {"action": "wait_for_ports", "safe_to_auto_run": True, "reason": "ports may still be binding", "ports": ports, "timeout": int(rb.get("retry_seconds", 30))}
    if "invalid_locale" in codes and diag.get("status") != "running":
        return {"action": "start_service", "safe_to_auto_run": True, "reason": "runbook start uses clean shell_env with LC_ALL unset", "service": rb.get("name")}
    if "dead_tmux_pane" in codes:
        return {"action": "restart_service", "safe_to_auto_run": True, "reason": "dead tmux panes indicate crashed process; runbook restart is safe", "service": rb.get("name")}
    if "service_stopped" in codes:
        return {"action": "start_service", "safe_to_auto_run": True, "reason": "service is stopped and runbook start is safe", "service": rb.get("name")}
    if "port_in_use" in codes:
        return {"action": "manual_targeted_cleanup", "safe_to_auto_run": False, "reason": "port conflict requires identifying exact owning process; avoid broad kill", "service": rb.get("name")}
    if "ring_not_configured" in codes:
        return {"action": "needs_secret_or_user_auth", "safe_to_auto_run": False, "reason": "Ring refreshToken is required and must not be requested casually in chat", "service": rb.get("name")}
    if "samsung_pairing_waiting" in codes:
        return {"action": "needs_physical_confirmation", "safe_to_auto_run": False, "reason": "TV Allow popup requires physical/user action", "service": rb.get("name")}
    return {"action": "inspect_logs", "safe_to_auto_run": False, "reason": "no safe automatic remediation selected", "service": rb.get("name")}


def diagnose_service_sync(name: str) -> dict[str, Any]:
    rb = load_runbook(name)
    host = rb.get("host", "127.0.0.1")
    ports = {str(p): ("open" if _port_open(host, int(p)) else "closed") for p in rb.get("ports", [])}
    tmux = _tmux_windows(rb)
    logs = _tail_logs(rb, lines=35)
    all_ports_open = bool(ports) and all(v == "open" for v in ports.values())
    if tmux.get("ok") and all_ports_open:
        status = "running"
        cause = "all expected tmux windows and ports are healthy"
    elif tmux.get("ok") and not all_ports_open:
        status = "starting_or_partial"
        cause = "tmux windows exist but at least one expected port is closed; wait/retry, then inspect logs"
    elif any(v == "open" for v in ports.values()):
        status = "partial"
        cause = "some ports are open but tmux verification is incomplete"
    else:
        status = "stopped_or_crashed"
        cause = "expected ports are closed and tmux verification is not healthy"
    diag = {
        "service": rb.get("name", name),
        "status": status,
        "likely_cause": cause,
        "ports": ports,
        "tmux": tmux,
        "logs": logs,
    }
    diag["analysis"] = classify_service_issue(diag, rb)
    diag["next_action"] = plan_service_next_action(diag, diag["analysis"], rb)
    return diag


def wait_for_ports_sync(ports: list[int], host: str = "127.0.0.1", timeout: int = 30, interval: float = 2.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    attempts = []
    while True:
        state = {str(p): ("open" if _port_open(host, int(p)) else "closed") for p in ports}
        attempts.append(state)
        if all(v == "open" for v in state.values()):
            return {"ok": True, "ports": state, "attempts": attempts}
        if time.time() >= deadline:
            return {"ok": False, "ports": state, "attempts": attempts}
        time.sleep(interval)


def start_service_sync(name: str) -> dict[str, Any]:
    rb = load_runbook(name)
    start_cmd = rb.get("start")
    if not start_cmd:
        raise ValueError(f"Runbook {name} has no start command")
    start = _run(start_cmd, timeout=float(rb.get("start_timeout", 90)))
    wait = wait_for_ports_sync([int(p) for p in rb.get("ports", [])], timeout=int(rb.get("retry_seconds", 30)))
    diag = diagnose_service_sync(name)
    return {"service": rb.get("name", name), "start": start, "wait": wait, "diagnosis": diag}


def stop_service_sync(name: str) -> dict[str, Any]:
    rb = load_runbook(name)
    stop_cmd = rb.get("stop")
    if not stop_cmd:
        raise ValueError(f"Runbook {name} has no stop command")
    stop = _run(stop_cmd, timeout=float(rb.get("stop_timeout", 30)))
    diag = diagnose_service_sync(name)
    return {"service": rb.get("name", name), "stop": stop, "diagnosis": diag}


def troubleshoot_service_sync(name: str, auto: bool = False, max_steps: int = 2) -> dict[str, Any]:
    rb = load_runbook(name)
    steps: list[dict[str, Any]] = []
    diag = diagnose_service_sync(name)
    steps.append({"step": "diagnose", "result": diag})
    for _ in range(max(0, int(max_steps))):
        plan = diag.get("next_action") or plan_service_next_action(diag, diag.get("analysis", {}), rb)
        if not auto or not plan.get("safe_to_auto_run") or plan.get("action") in ("none", None):
            break
        if plan["action"] == "wait_for_ports":
            result = wait_for_ports_sync([int(p) for p in rb.get("ports", [])], host=rb.get("host", "127.0.0.1"), timeout=int(plan.get("timeout", rb.get("retry_seconds", 30))))
            steps.append({"step": "wait_for_ports", "result": result})
        elif plan["action"] == "start_service":
            result = start_service_sync(name)
            steps.append({"step": "start_service", "result": {"wait": result.get("wait"), "start_exit_code": result.get("start", {}).get("exit_code")}})
        else:
            break
        diag = diagnose_service_sync(name)
        steps.append({"step": "re_diagnose", "result": diag})
        if diag.get("status") == "running":
            break
    result = {"service": rb.get("name", name), "auto": auto, "final_status": diag.get("status"), "final_next_action": diag.get("next_action"), "steps": steps}
    status = "ok" if result["final_status"] == "running" else "warn"
    record_event(make_event("service_troubleshoot", status, f"troubleshoot {result['service']} -> {result['final_status']}", component=result["service"], details={"auto": auto, "final_status": result["final_status"], "next_action": result.get("final_next_action"), "step_names": [s.get("step") for s in steps]}))
    return result


def inspect_service_listeners_sync(name: str) -> dict[str, Any]:
    rb = load_runbook(name)
    ports = [int(p) for p in rb.get("ports", [])]
    by_port: dict[str, list[dict[str, Any]]] = {}
    raw: dict[str, str] = {}
    for port in ports:
        cmd = f"/var/jb/usr/bin/lsof -nP -iTCP:{port} -sTCP:LISTEN 2>/dev/null || /usr/sbin/lsof -nP -iTCP:{port} -sTCP:LISTEN 2>/dev/null || true"
        result = _run(cmd, timeout=8)
        raw[str(port)] = result.get("output", "")
        by_port[str(port)] = parse_listener_output(result.get("output", ""))
    listeners = [item for rows in by_port.values() for item in rows]
    # iOS often lacks lsof. Fallback to conservative process candidates by runbook patterns;
    # these are NOT treated as exact port owners, only as evidence for targeted human review.
    patterns = rb.get("process_patterns") or [rb.get("name", name)]
    pat = "|".join(str(x) for x in patterns if x)
    proc_candidates: list[dict[str, Any]] = []
    if pat:
        ps = _run(f"ps aux | /var/jb/usr/bin/grep -E '{pat}' | /var/jb/usr/bin/grep -v grep || true", timeout=8).get("output", "")
        for line in ps.splitlines():
            parts = line.split(None, 10)
            if len(parts) >= 2:
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                proc_candidates.append({"pid": pid, "raw": line, "exact_port_owner": False})
    return {"service": rb.get("name", name), "ports": ports, "listeners": listeners, "by_port": by_port, "raw": raw, "process_candidates": proc_candidates, "listener_source": "lsof" if listeners else "ps_fallback_candidates"}


def repair_service_sync(name: str, auto: bool = False, max_steps: int = 2) -> dict[str, Any]:
    rb = load_runbook(name)
    steps: list[dict[str, Any]] = []
    diag = diagnose_service_sync(name)
    steps.append({"step": "diagnose", "result": diag})
    for _ in range(max(0, int(max_steps))):
        plan = diag.get("next_action") or plan_service_next_action(diag, diag.get("analysis", {}), rb)
        action = plan.get("action")
        if action == "manual_targeted_cleanup":
            listeners = inspect_service_listeners_sync(name)
            cleanup_plan = plan_targeted_cleanup(name, listeners.get("listeners", []))
            steps.append({"step": "inspect_listeners", "result": listeners})
            steps.append({"step": "targeted_cleanup_plan", "result": cleanup_plan})
            break
        if not auto or not plan.get("safe_to_auto_run") or action in ("none", None):
            break
        if action == "wait_for_ports":
            result = wait_for_ports_sync([int(p) for p in rb.get("ports", [])], host=rb.get("host", "127.0.0.1"), timeout=int(plan.get("timeout", rb.get("retry_seconds", 30))))
            steps.append({"step": "wait_for_ports", "result": result})
        elif action == "start_service":
            result = start_service_sync(name)
            steps.append({"step": "start_service", "result": {"wait": result.get("wait"), "start_exit_code": result.get("start", {}).get("exit_code")}})
        elif action == "restart_service":
            stop = stop_service_sync(name)
            start = start_service_sync(name)
            steps.append({"step": "restart_service", "result": {"stop_status": stop.get("diagnosis", {}).get("status"), "start_wait": start.get("wait")}})
        else:
            break
        diag = diagnose_service_sync(name)
        steps.append({"step": "re_diagnose", "result": diag})
        if diag.get("status") == "running":
            break
    result = {"service": rb.get("name", name), "auto": auto, "final_status": diag.get("status"), "final_next_action": diag.get("next_action"), "steps": steps}
    status = "ok" if result["final_status"] == "running" else "warn"
    record_event(make_event("service_repair", status, f"repair {result['service']} -> {result['final_status']}", component=result["service"], details={"auto": auto, "final_status": result["final_status"], "next_action": result.get("final_next_action"), "step_names": [s.get("step") for s in steps]}))
    return result

@register({
    "name": "diagnose_service",
    "description": "Diagnose a known service from its runbook: tmux windows, ports, logs, issue classification, and next action.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
})
async def diagnose_service(name: str) -> str:
    return _json(await asyncio.to_thread(diagnose_service_sync, name))


@register({
    "name": "wait_for_ports",
    "description": "Wait until TCP ports open, retrying before declaring failure.",
    "parameters": {
        "type": "object",
        "properties": {
            "ports": {"type": "array", "items": {"type": "integer"}},
            "host": {"type": "string", "default": "127.0.0.1"},
            "timeout": {"type": "integer", "default": 30},
        },
        "required": ["ports"],
    },
})
async def wait_for_ports(ports: list[int], host: str = "127.0.0.1", timeout: int = 30) -> str:
    return _json(await asyncio.to_thread(wait_for_ports_sync, ports, host, timeout))


@register({
    "name": "start_service",
    "description": "Start a known service using its runbook, wait for ports, then diagnose/verify.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
})
async def start_service(name: str) -> str:
    return _json(await asyncio.to_thread(start_service_sync, name))


@register({
    "name": "stop_service",
    "description": "Stop a known service using its runbook and diagnose the resulting state.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
})
async def stop_service(name: str) -> str:
    return _json(await asyncio.to_thread(stop_service_sync, name))


@register({
    "name": "troubleshoot_service",
    "description": "Run a service diagnosis loop: classify issues, choose a safe next action, and optionally auto-run only safe remediation steps such as waiting for ports or runbook start.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "auto": {"type": "boolean", "default": False, "description": "If true, run only safe automatic remediation steps."},
            "max_steps": {"type": "integer", "default": 2},
        },
        "required": ["name"],
    },
})
async def troubleshoot_service(name: str, auto: bool = False, max_steps: int = 2) -> str:
    return _json(await asyncio.to_thread(troubleshoot_service_sync, name, auto, max_steps))


@register({
    "name": "inspect_service_listeners",
    "description": "Inspect exact TCP listener processes for a known service's runbook ports. Use before any port-conflict cleanup; does not kill anything.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
})
async def inspect_service_listeners(name: str) -> str:
    return _json(await asyncio.to_thread(inspect_service_listeners_sync, name))


@register({
    "name": "repair_service",
    "description": "Run Sprint-3 service repair playbooks. It can inspect listeners and propose targeted cleanup; with auto=true it only runs safe actions like wait/start/restart, never broad kill or secret/physical steps.",
    "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "auto": {"type": "boolean", "default": False}, "max_steps": {"type": "integer", "default": 2}}, "required": ["name"]},
})
async def repair_service(name: str, auto: bool = False, max_steps: int = 2) -> str:
    return _json(await asyncio.to_thread(repair_service_sync, name, auto, max_steps))
