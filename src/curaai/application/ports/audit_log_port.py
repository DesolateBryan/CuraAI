"""AuditLogPort: append-only (ADR-003, ADR-007). There is no update or delete."""

from abc import ABC, abstractmethod

from curaai.application.dto.audit import AuditEvent


class AuditLogPort(ABC):
    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Append one event."""
