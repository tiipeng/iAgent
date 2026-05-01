#!/var/jb/usr/bin/python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))
import os
os.environ.setdefault("IAGENT_HOME", str(ROOT))
from tools.selftest import selftest_sync

def main() -> int:
    parser = argparse.ArgumentParser(description="Run iAgent Sprint-4 self-test")
    parser.add_argument("--no-live", action="store_true", help="skip live HTTP/service probes")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()
    result = selftest_sync(live=not args.no_live)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"iAgent selftest: {result['status'].upper()} ({result['summary']['total']} checks)")
        for check in result["checks"]:
            print(f"{check['status'].upper():5} {check['name']}: {check['message']}")
    return 1 if result["status"] == "fail" else 0
if __name__ == "__main__":
    raise SystemExit(main())
