"""JsonlAuditLog: AuditLogPort that appends one JSON line per AuditEvent (ADR-003, ADR-007).

Prototype store per ADR-017: JSONL now, append-only PostgreSQL later. The port
stays the same, so swapping the store touches only this file and app/main.py.

Humble-object split (ADR-014):
  * audit_event_to_json / audit_event_from_json are pure, tested with plain data
  * JsonlAuditLog.record does one append per call, with no branching

Append-only: the file is opened in "a" mode for every write and there is no
update or delete method. Each line is flushed and fsync'd so a crash loses at
most the event being written. A lock keeps concurrent requests from interleaving lines.

PHI note (ADR-006): AuditEvent.detail is primitives only and Ring 2 logs counts,
ids and reasons, never chart text. Retention rules for this file are deferred
with the rest of the retention policy.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from curaai.application.dto.audit import AuditEvent
from curaai.application.ports.audit_log_port import AuditLogPort

SCHEMA_VERSION = 1


def audit_event_to_json(event: AuditEvent) -> str:
    return json.dumps({
        "v": SCHEMA_VERSION,
        "at": event.at.isoformat(),
        "actor": event.actor,
        "action": event.action,
        "subject_id": event.subject_id,
        "detail": event.detail,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def audit_event_from_json(line: str) -> AuditEvent:
    data = json.loads(line)
    return AuditEvent(at=datetime.fromisoformat(data["at"]), actor=data["actor"], action=data["action"],
                      subject_id=data["subject_id"], detail=dict(data.get("detail") or {}))


def read_audit_log(path: str | Path) -> list[AuditEvent]:
    """For tests, audit review and the readable run log. Never used by the pipeline itself."""
    with open(path, encoding="utf-8") as handle:
        return [audit_event_from_json(line) for line in handle if line.strip()]


class JsonlAuditLog(AuditLogPort):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        line = audit_event_to_json(event) + "\n"
        with self._lock, open(self._path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
