"""Logging decorators around each model port (ADR-007, ADR-008).

Each wrapper implements the same port it wraps, writes an AuditEvent with the
request id, prompt version, raw output and validated result, and updates the
per-case counters. Created once in Main and shared.
"""

from curaai.application.dto.model import ExtractionRequest, SymptomExtraction
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.model_ports import ExtractSymptomsPort


class LoggedExtractSymptoms(ExtractSymptomsPort):
    def __init__(self, inner: ExtractSymptomsPort, audit_log: AuditLogPort) -> None:
        self._inner = inner
        self._audit = audit_log

    def extract(self, request: ExtractionRequest) -> SymptomExtraction:
        raise NotImplementedError("Ring 3 stub: log, delegate to inner, log result")
