"""Ports: abstract interfaces owned by Ring 2 and implemented by Ring 3 adapters.

Least privilege (ADR-010): every data port is READ-ONLY. There is no method
anywhere in this package that writes to the chart, places an order, or sends
free text to a patient. tests/unit/application/test_ports.py enforces that.
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
from curaai.application.ports.review_output_port import ReviewOutputPort

__all__ = [
    "AuditLogPort", "ClockPort", "ConversationStorePort", "DrugDbPort", "EhrPort",
    "ExtractSymptomsPort", "MatchFlagsPort", "PatientMessagingPort",
    "PickRelevantItemsPort", "ReviewOutputPort", "SelectFollowUpPort",
]
