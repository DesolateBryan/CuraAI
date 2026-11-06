"""python -m curaai.app.runlog [audit.jsonl] [--last N]

Prints the audit log as a readable run log (Governance ADR 1 and 2): one block per case,
one plain-English line per event, off-ramps and failed guardrails marked "!!", then the
ADR-008 numbers and the HITL gate counts. The same text is served at /runlog while the
server runs (that page shows only the current server session).
"""

import argparse
import sys
from pathlib import Path

from curaai.adapters.observability import format_run_log
from curaai.adapters.persistence import read_audit_log
from curaai.app.main import Config, load_env_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m curaai.app.runlog", description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", help="audit log file (default: CURAAI_AUDIT_LOG_PATH from .env)")
    parser.add_argument("--last", type=int, default=0, help="only the last N cases")
    args = parser.parse_args(argv)
    path = Path(args.path or load_env_file(".env").get("CURAAI_AUDIT_LOG_PATH") or Config().audit_log_path)
    if not path.is_file():
        print(f"No audit log at {path}. Run the demo first (python -m curaai.app.main).")
        return 1
    events = read_audit_log(path)
    if args.last > 0:
        keep = list(dict.fromkeys(e.subject_id for e in events))[-args.last:]
        events = [e for e in events if e.subject_id in set(keep)]
    sys.stdout.write(format_run_log(events, source=str(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
