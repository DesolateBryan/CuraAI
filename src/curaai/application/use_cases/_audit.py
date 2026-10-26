"""Small helper so every use case writes audit events the same way (ADR-007)."""

from curaai.application.dto.audit import AuditEvent, Primitive
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort


class Auditor:
    def __init__(self, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._log = audit_log
        self._clock = clock

    def __call__(self, actor: str, action: str, case_id: str, **detail: Primitive) -> None:
        self._log.record(AuditEvent(at=self._clock.now(), actor=actor, action=action,
                                    subject_id=case_id, detail=dict(detail)))
