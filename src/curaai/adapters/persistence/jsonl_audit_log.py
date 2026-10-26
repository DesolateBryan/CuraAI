"""JsonlAuditLog (humble): append one JSON line per AuditEvent. Postgres deferred (ADR-017)."""

from curaai.application.dto.audit import AuditEvent
from curaai.application.ports.audit_log_port import AuditLogPort


class JsonlAuditLog(AuditLogPort):
    def __init__(self, path: str) -> None:
        self._path = path

    def record(self, event: AuditEvent) -> None:
        raise NotImplementedError("Ring 3 stub")
