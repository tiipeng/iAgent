#!/var/jb/usr/bin/python3
from __future__ import annotations
import asyncio, importlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code" if (ROOT / "code").exists() else ROOT
if str(CODE) not in sys.path: sys.path.insert(0, str(CODE))
import os
os.environ.setdefault("IAGENT_HOME", str(ROOT))
failures: list[str] = []
def check(name: str, fn):
    try:
        result = fn()
        if result is False: failures.append(f"FAIL {name}: returned False")
        else: print(f"PASS {name}")
    except Exception as exc: failures.append(f"FAIL {name}: {type(exc).__name__}: {exc}")
async def acheck(name: str, fn):
    try:
        result = await fn()
        if result is False: failures.append(f"FAIL {name}: returned False")
        else: print(f"PASS {name}")
    except Exception as exc: failures.append(f"FAIL {name}: {type(exc).__name__}: {exc}")
def test_shell_env():
    mod=importlib.import_module("tools.shell_env"); env=mod.ios_env_prefix(); assert "unset LC_ALL" in env; assert "LC_CTYPE=UTF-8" in env; assert "/var/jb/usr/bin" in env
def test_homebridge_runbook():
    data=json.loads((ROOT/"runbooks"/"homebridge.json").read_text()); assert data["name"]=="homebridge"; assert 51826 in data["ports"] and 8581 in data["ports"]; assert data["tmux"]["session"]=="homebridge"; assert set(data["tmux"]["windows"]) >= {"hb","ui"}
def test_services_import_and_diagnose_shape():
    mod=importlib.import_module("tools.services"); rb=mod.load_runbook("homebridge"); diag=mod.diagnose_service_sync("homebridge"); assert rb["name"]=="homebridge"; assert "ports" in diag and "tmux" in diag and "status" in diag
async def test_service_tool_registered():
    import tools.services, tools.registry as registry; names=[s["function"]["name"] for s in registry.get_schemas()]; assert "start_service" in names; assert "diagnose_service" in names; assert "wait_for_ports" in names
def test_sprint2_issue_classification():
    mod=importlib.import_module("tools.services"); diag={"status":"starting_or_partial","ports":{"51826":"closed","8581":"closed"},"tmux":{"ok":True,"windows":["hb","ui"]},"logs":{"homebridge.log":"tmux: invalid LC_ALL, LC_CTYPE or LANG\nError: listen EADDRINUSE: address already in use 8581"}}
    analysis=mod.classify_service_issue(diag, mod.load_runbook("homebridge")); codes={item["code"] for item in analysis["issues"]}; assert "invalid_locale" in codes; assert "port_in_use" in codes; assert analysis["severity"] in {"warning","critical"}
def test_sprint2_next_action_selection():
    mod=importlib.import_module("tools.services"); rb=mod.load_runbook("homebridge"); diag={"status":"starting_or_partial","ports":{"51826":"closed","8581":"closed"},"tmux":{"ok":True,"windows":["hb","ui"]},"logs":{}}
    analysis=mod.classify_service_issue(diag, rb); plan=mod.plan_service_next_action(diag, analysis, rb); assert plan["action"]=="wait_for_ports"; assert plan["safe_to_auto_run"] is True
async def test_sprint2_troubleshoot_tool_registered():
    import tools.services, tools.registry as registry; names=[s["function"]["name"] for s in registry.get_schemas()]; assert "troubleshoot_service" in names
def test_sprint3_parse_listener_output():
    mod=importlib.import_module("tools.services"); sample="COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\nnode    12345 mobile 22u  IPv4 0      0t0  TCP *:8581 (LISTEN)"; listeners=mod.parse_listener_output(sample); assert listeners[0]["pid"]==12345; assert listeners[0]["port"]==8581; assert listeners[0]["command"]=="node"
def test_sprint3_targeted_cleanup_plan_is_not_broad_kill():
    mod=importlib.import_module("tools.services"); listeners=[{"pid":12345,"command":"node","port":8581,"raw":"node 12345 ...:8581"}]; plan=mod.plan_targeted_cleanup("homebridge", listeners); assert plan["safe_to_auto_run"] is False; assert "kill -9" not in " ".join(plan.get("commands", [])); assert "12345" in " ".join(plan.get("commands", []))
def test_sprint3_dead_pane_detection():
    mod=importlib.import_module("tools.services"); raw="0: hb- (1 panes) [80x24] @0 [dead]\n1: ui* (1 panes) [80x24] @1"; panes=mod.parse_tmux_window_health(raw, expected=["hb","ui"]); assert panes["dead_panes"]==["hb"]; assert panes["ok"] is False
async def test_sprint3_repair_tool_registered():
    import tools.services, tools.registry as registry; names=[s["function"]["name"] for s in registry.get_schemas()]; assert "repair_service" in names; assert "inspect_service_listeners" in names

def test_sprint4_selftest_module_shape():
    mod=importlib.import_module("tools.selftest"); result=mod.selftest_sync(live=False); assert result["component"]=="iagent_selftest"; assert "checks" in result and isinstance(result["checks"], list); assert "summary" in result and "status" in result

def test_sprint4_selftest_tool_registered():
    import tools.selftest, tools.registry as registry; names=[s["function"]["name"] for s in registry.get_schemas()]; assert "run_selftest" in names

def test_sprint4_selftest_check_schema():
    mod=importlib.import_module("tools.selftest"); check=mod.make_check("example", "ok", "hello", {"x":1}); assert set(["name","status","message","details"]).issubset(check); assert check["status"]=="ok"


def test_sprint5_ops_journal_module_shape():
    mod=importlib.import_module("tools.ops_journal"); event=mod.make_event("selftest", "ok", "hello", component="iagent", details={"x":1}); assert event["event_type"]=="selftest"; assert event["status"]=="ok"; assert event["component"]=="iagent"; assert "timestamp" in event

def test_sprint5_ops_journal_record_and_summary_tmp():
    mod=importlib.import_module("tools.ops_journal"); import tempfile; p=Path(tempfile.gettempdir())/"iagent_sprint5_regression_journal.jsonl"; p.unlink(missing_ok=True); mod.record_event(mod.make_event("repair", "warn", "ports delayed", component="homebridge", details={"code":"ports_not_ready"}), path=p); mod.record_event(mod.make_event("selftest", "ok", "all ok", component="iagent"), path=p); summary=mod.summarize_events(path=p, limit=10); assert summary["total"]==2; assert summary["by_status"]["ok"]==1; assert summary["by_status"]["warn"]==1; assert "ports_not_ready" in summary["issue_codes"]

def test_sprint5_ops_journal_tools_registered():
    import tools.ops_journal, tools.registry as registry; names=[s["function"]["name"] for s in registry.get_schemas()]; assert "read_ops_journal" in names; assert "summarize_ops_journal" in names


def test_sprint5_ops_journal_redacts_secrets():
    mod=importlib.import_module("tools.ops_journal")
    pin = "733" + "-" + "43" + "-" + "403"
    token = "123" + "456"
    refresh = "ab" + "cd"
    refresh_key = "refresh" + "Token"
    event=mod.make_event("service_repair", "ok", f"Setup Code: {pin} token: '{token}' password=abc", component="homebridge", details={"log":f"pincode: {pin} {refresh_key}={refresh} token: '{token}'"})
    clean=mod.sanitize_event(event); blob=json.dumps(clean); assert pin not in blob; assert token not in blob; assert refresh not in blob; assert "[REDACTED]" in blob


def test_sprint6_status_card_from_selftest():
    mod=importlib.import_module("tools.status_cards"); sample={"status":"ok","summary":{"counts":{"ok":7,"warn":0,"fail":0,"skip":0},"total":7},"checks":[{"name":"homebridge_service","status":"ok","message":"healthy","details":{"ports":{"51826":"open","8581":"open"}}},{"name":"xxtouch_http","status":"ok","message":"reachable","details":{}},{"name":"ios_mcp_http","status":"ok","message":"reachable","details":{}}]}; card=mod.format_selftest_card(sample); assert "✅" in card; assert "Homebridge" in card; assert "XXTouch" in card; assert "ios-mcp" in card

def test_sprint6_status_card_combines_journal():
    mod=importlib.import_module("tools.status_cards"); card=mod.format_ops_status_card({"status":"ok","checks":[],"summary":{"counts":{"ok":1},"total":1}}, {"total":3,"by_status":{"ok":3},"issue_codes":{},"last_event":{"event_type":"selftest","component":"iagent","status":"ok","message":"selftest ok"}}); assert "Journal" in card; assert "3" in card; assert "selftest" in card

def test_sprint6_status_card_tools_registered():
    import tools.status_cards, tools.registry as registry; names=[s["function"]["name"] for s in registry.get_schemas()]; assert "get_status_card" in names; assert "format_status_card" in names

def test_sprint7_prompt_allows_owner_ssh_admin():
    mod=importlib.import_module("agent.context")
    prompt=mod.ChatContext(chat_id=-1).system_prompt()
    assert "SSH commands to the user's own/local/Tailscale devices" in prompt
    assert "Do not say you cannot access external devices for security reasons" in prompt
    assert "reboot/shutdown" in prompt

def test_sprint7_shell_schema_mentions_ssh():
    import tools.shell, tools.registry as registry
    schemas={s["function"]["name"]:s["function"] for s in registry.get_schemas()}
    desc=schemas["shell"]["description"]
    assert "SSH/scp" in desc and "owner-authorized" in desc

async def main():
    check("shell_env", test_shell_env); check("homebridge_runbook", test_homebridge_runbook); check("services_import_and_diagnose_shape", test_services_import_and_diagnose_shape); await acheck("service_tool_registered", test_service_tool_registered)
    check("sprint2_issue_classification", test_sprint2_issue_classification); check("sprint2_next_action_selection", test_sprint2_next_action_selection); await acheck("sprint2_troubleshoot_tool_registered", test_sprint2_troubleshoot_tool_registered)
    check("sprint3_parse_listener_output", test_sprint3_parse_listener_output); check("sprint3_targeted_cleanup_plan_is_not_broad_kill", test_sprint3_targeted_cleanup_plan_is_not_broad_kill); check("sprint3_dead_pane_detection", test_sprint3_dead_pane_detection); await acheck("sprint3_repair_tool_registered", test_sprint3_repair_tool_registered)
    check("sprint4_selftest_module_shape", test_sprint4_selftest_module_shape); check("sprint4_selftest_check_schema", test_sprint4_selftest_check_schema); check("sprint4_selftest_tool_registered", test_sprint4_selftest_tool_registered)
    check("sprint5_ops_journal_module_shape", test_sprint5_ops_journal_module_shape); check("sprint5_ops_journal_record_and_summary_tmp", test_sprint5_ops_journal_record_and_summary_tmp); check("sprint5_ops_journal_tools_registered", test_sprint5_ops_journal_tools_registered)
    check("sprint5_ops_journal_redacts_secrets", test_sprint5_ops_journal_redacts_secrets)
    check("sprint6_status_card_from_selftest", test_sprint6_status_card_from_selftest); check("sprint6_status_card_combines_journal", test_sprint6_status_card_combines_journal); check("sprint6_status_card_tools_registered", test_sprint6_status_card_tools_registered)
    check("sprint7_prompt_allows_owner_ssh_admin", test_sprint7_prompt_allows_owner_ssh_admin); check("sprint7_shell_schema_mentions_ssh", test_sprint7_shell_schema_mentions_ssh)
    if failures: print("\n".join(failures)); raise SystemExit(1)
    print("ALL REGRESSION CHECKS PASSED")
if __name__ == "__main__": asyncio.run(main())
