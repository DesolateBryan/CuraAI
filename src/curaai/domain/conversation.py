"""Conversation: one sick-message case, from first message to physician handoff.

State machine (every transition returns a new, immutable Conversation):

    SCREENING --complete or AI off--> READY --> HANDED_OFF          (chart pre-fetched)
    SCREENING --still missing, follow-ups left--> AWAITING_PATIENT
    AWAITING_PATIENT --patient replies--> SCREENING
    AWAITING_PATIENT --24 h, no reply--> HANDED_OFF_INCOMPLETE (TIMED_OUT)
    SCREENING --still missing, no follow-ups left--> HANDED_OFF_INCOMPLETE (FOLLOW_UPS_EXHAUSTED)

HANDED_OFF_INCOMPLETE means messages only, no chart pre-fetch (team decision, 2026-10-26).
If the AI is disabled for the case (cap hit or output rejected, ADR-011), the fixed
chart pull still runs, anchored to the first message date when onset is unknown.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum

from curaai.domain.case_budget import CaseBudget, CaseLimits
from curaai.domain.errors import InvalidConversationTransition
from curaai.domain.follow_up_timeout import FollowUpTimeout
from curaai.domain.sick_message import SickMessage
from curaai.domain.symptom_report import SymptomReport
from curaai.domain.values import MissingField, PatientId, QuestionId, require_aware


class ConversationState(Enum):
    SCREENING = "screening"
    AWAITING_PATIENT = "awaiting_patient"
    READY = "ready"
    HANDED_OFF = "handed_off"
    HANDED_OFF_INCOMPLETE = "handed_off_incomplete"


class IncompleteReason(Enum):
    TIMED_OUT = "timed_out"
    FOLLOW_UPS_EXHAUSTED = "follow_ups_exhausted"
    AI_UNAVAILABLE = "ai_unavailable"     # pre-fetch ran, but onset/trend were never established


class NextStep(Enum):
    PREFETCH = "prefetch"
    ASK_FOLLOW_UP = "ask_follow_up"
    HAND_OFF_INCOMPLETE = "hand_off_incomplete"


OPEN_STATES = frozenset({ConversationState.SCREENING, ConversationState.AWAITING_PATIENT, ConversationState.READY})


@dataclass(frozen=True)
class AskedFollowUp:
    question_id: QuestionId
    asked_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.asked_at, "AskedFollowUp.asked_at")


@dataclass(frozen=True)
class Conversation:
    case_id: str
    patient_id: PatientId
    messages: tuple[SickMessage, ...]
    state: ConversationState = ConversationState.SCREENING
    report: SymptomReport = field(default_factory=SymptomReport)
    follow_ups: tuple[AskedFollowUp, ...] = ()
    budget: CaseBudget = field(default_factory=CaseBudget)
    ai_disabled: bool = False
    incomplete_reason: IncompleteReason | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("a conversation needs at least one patient message")
        if any(m.patient_id != self.patient_id for m in self.messages):
            raise ValueError("every message in a conversation must belong to its patient")
        is_incomplete = self.state is ConversationState.HANDED_OFF_INCOMPLETE
        if is_incomplete != (self.incomplete_reason is not None):
            raise ValueError("incomplete_reason is set exactly when the case was handed off incomplete")

    # ---- construction -------------------------------------------------------
    @classmethod
    def start(cls, message: SickMessage, limits: CaseLimits = CaseLimits()) -> "Conversation":
        return cls(
            case_id=message.message_id,
            patient_id=message.patient_id,
            messages=(message,),
            budget=CaseBudget(limits=limits),
        )

    # ---- read-only views ----------------------------------------------------
    @property
    def latest_message(self) -> SickMessage:
        return self.messages[-1]

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    @property
    def last_asked_at(self) -> datetime | None:
        return self.follow_ups[-1].asked_at if self.follow_ups else None

    @property
    def onset_established(self) -> bool:
        return self.report.onset is not None

    @property
    def anchor_date(self) -> date:
        """The date the 3-week window is measured from: onset, or the first message date."""
        return self.report.onset if self.report.onset is not None else self.messages[0].sent_at.date()

    # ---- rules --------------------------------------------------------------
    def decide(self, missing: frozenset[MissingField]) -> NextStep:
        self._require(ConversationState.SCREENING, "decide")
        if not missing or self.ai_disabled:
            return NextStep.PREFETCH
        if self.budget.can_follow_up():
            return NextStep.ASK_FOLLOW_UP
        return NextStep.HAND_OFF_INCOMPLETE

    def is_expired(self, now: datetime, timeout: FollowUpTimeout = FollowUpTimeout()) -> bool:
        return (
            self.state is ConversationState.AWAITING_PATIENT
            and self.last_asked_at is not None
            and timeout.is_expired(self.last_asked_at, now)
        )

    # ---- transitions --------------------------------------------------------
    def with_report(self, report: SymptomReport) -> "Conversation":
        self._require(ConversationState.SCREENING, "with_report")
        return replace(self, report=self.report.merge(report))

    def spend_model_call(self) -> "Conversation":
        return replace(self, budget=self.budget.record_model_call())

    def spend_lookup(self) -> "Conversation":
        return replace(self, budget=self.budget.record_lookup())

    def disable_ai(self) -> "Conversation":
        return replace(self, ai_disabled=True)

    def record_follow_up(self, question_id: QuestionId, asked_at: datetime) -> "Conversation":
        self._require(ConversationState.SCREENING, "record_follow_up")
        return replace(
            self,
            state=ConversationState.AWAITING_PATIENT,
            follow_ups=self.follow_ups + (AskedFollowUp(question_id, asked_at),),
            budget=self.budget.record_follow_up(),
        )

    def receive_reply(self, message: SickMessage) -> "Conversation":
        self._require(ConversationState.AWAITING_PATIENT, "receive_reply")
        if message.patient_id != self.patient_id:
            raise InvalidConversationTransition("reply is from a different patient")
        return replace(self, state=ConversationState.SCREENING, messages=self.messages + (message,))

    def expire(self, now: datetime, timeout: FollowUpTimeout = FollowUpTimeout()) -> "Conversation":
        if not self.is_expired(now, timeout):
            raise InvalidConversationTransition("follow-up has not timed out")
        return replace(self, state=ConversationState.HANDED_OFF_INCOMPLETE,
                       incomplete_reason=IncompleteReason.TIMED_OUT)

    def hand_off_incomplete(self) -> "Conversation":
        """Follow-ups are used up and details are still missing."""
        self._require(ConversationState.SCREENING, "hand_off_incomplete")
        return replace(self, state=ConversationState.HANDED_OFF_INCOMPLETE,
                       incomplete_reason=IncompleteReason.FOLLOW_UPS_EXHAUSTED)

    def mark_ready(self) -> "Conversation":
        self._require(ConversationState.SCREENING, "mark_ready")
        return replace(self, state=ConversationState.READY)

    def mark_handed_off(self) -> "Conversation":
        self._require(ConversationState.READY, "mark_handed_off")
        return replace(self, state=ConversationState.HANDED_OFF)

    def _require(self, state: ConversationState, action: str) -> None:
        if self.state is not state:
            raise InvalidConversationTransition(f"cannot {action} while {self.state.value}")
