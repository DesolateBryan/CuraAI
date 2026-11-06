"""Ports: abstract interfaces owned by Ring 2 and implemented by Ring 3 adapters.

Least privilege (ADR-010): every data port is READ-ONLY. There is no method
anywhere in this package that writes to the chart or places an order, and the AI
pipeline can send a patient only fixed catalog questions. The one way text reaches a
patient is PhysicianReplyPort, which carries a reply a physician approved at the HITL
gate (Governance ADR 3) and is held only by RecordPhysicianDecision.
tests/unit/application/test_ports.py enforces all of that.
"""

from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.conversation_store_port import ConversationStorePort
from curaai.application.ports.drug_db_port import DrugDbPort
from curaai.application.ports.ehr_port import EhrPort
from curaai.application.ports.messaging_port import PatientMessagingPort
from curaai.application.ports.model_ports import (
    ExtractSymptomsPort,
    MatchFlagsPort,
    PickRelevantItemsPort,
    SelectFollowUpPort,
)
from curaai.application.ports.physician_reply_port import PhysicianReplyPort
from curaai.application.ports.review_gate_port import ReviewGatePort
from curaai.application.ports.review_output_port import ReviewOutputPort

__all__ = [
    "AuditLogPort", "ClockPort", "ConversationStorePort", "DrugDbPort", "EhrPort",
    "ExtractSymptomsPort", "MatchFlagsPort", "PatientMessagingPort", "PhysicianReplyPort",
    "PickRelevantItemsPort", "ReviewGatePort", "ReviewOutputPort", "SelectFollowUpPort",
]
