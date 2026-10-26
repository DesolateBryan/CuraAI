"""Audit boundary. Table rows, SQL and connections stay behind the repository."""

from dataclasses import dataclass, field
from datetime import datetime

Primitive = str | int | float | bool | None


@dataclass(frozen=True)
class AuditEvent:
    at: datetime
    actor: str          # "pipeline", "validator", "model:<port>", "physician"
    action: str         # e.g. "model_output_rejected", "follow_up_sent"
    subject_id: str     # case id
    detail: dict[str, Primitive] = field(default_factory=dict)   # primitives only
