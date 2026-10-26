"""Conversation-state boundary. The store holds snapshots, never Ring 1 entities (ADR-012)."""

from dataclasses import dataclass
from datetime import date, datetime

from curaai.application.dto.messaging import InboundMessage
from curaai.domain.conversation import OPEN_STATES as _OPEN_STATES, ConversationState


@dataclass(frozen=True)
class AskedFollowUpSnapshot:
    question_id: str
    asked_at: datetime


@dataclass(frozen=True)
class ConversationSnapshot:
    case_id: str
    patient_id: str
    state: str
    messages: tuple[InboundMessage, ...]
    symptom_ids: tuple[str, ...]
    onset: date | None
    onset_is_approx: bool
    trend: str | None
    follow_ups: tuple[AskedFollowUpSnapshot, ...]
    model_calls: int
    lookups: int
    ai_disabled: bool
    incomplete_reason: str | None


# Which snapshot states count as "open". Store adapters use this for get_open().

OPEN_STATE_VALUES: frozenset[str] = frozenset(s.value for s in _OPEN_STATES)
AWAITING_PATIENT_VALUE: str = ConversationState.AWAITING_PATIENT.value
