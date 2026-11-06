"""PipelineTrigger: runs on every inbound patient message, with no model gate (M1 sketch).

on_patient_message():
    * no open case          -> open a new case
    * waiting on the patient -> treat the message as the reply
    * waiting, but expired   -> hand the old case off (messages only), open a new one
    then screen -> follow up, or pre-fetch and deliver, or hand off incomplete.

sweep_timeouts():
    called on a schedule by Ring 4; hands off every case whose follow-up has gone
    unanswered for 24 hours, as messages only with no chart pull.
"""

from dataclasses import dataclass
from enum import Enum

from curaai.application.dto.messaging import InboundMessage
from curaai.application.mapping import conversation_from, sick_message_from, snapshot_from
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.conversation_store_port import ConversationStorePort
from curaai.application.use_cases._audit import Auditor
from curaai.application.use_cases.assemble_review_packet import AssembleReviewPacket
from curaai.application.use_cases.prefetch_history import PrefetchHistory
from curaai.application.use_cases.request_follow_up import RequestFollowUp
from curaai.application.use_cases.screen_sick_message import ScreenSickMessage
from curaai.domain.case_budget import CaseLimits
from curaai.domain.completeness import CompletenessPolicy
from curaai.domain.conversation import Conversation, ConversationState, NextStep
from curaai.domain.follow_up_timeout import FollowUpTimeout

ACTOR = "pipeline"


class PipelineOutcome(Enum):
    FOLLOW_UP_SENT = "follow_up_sent"
    PACKET_DELIVERED = "packet_delivered"
    HANDED_OFF_INCOMPLETE = "handed_off_incomplete"


@dataclass(frozen=True)
class TriggerResult:
    case_id: str
    patient_id: str
    outcome: PipelineOutcome


class PipelineTrigger:
    def __init__(self, store: ConversationStorePort, screen: ScreenSickMessage,
                 follow_up: RequestFollowUp, prefetch: PrefetchHistory,
                 assemble: AssembleReviewPacket, audit_log: AuditLogPort, clock: ClockPort,
                 *, limits: CaseLimits, timeout: FollowUpTimeout) -> None:
        # Governance configuration (caps, timeout) has no default here: Main owns it.
        self._store = store
        self._screen = screen
        self._follow_up = follow_up
        self._prefetch = prefetch
        self._assemble = assemble
        self._clock = clock
        self._limits = limits
        self._timeout = timeout
        self._audit = Auditor(audit_log, clock)

    # ---- entry points ---------------------------------------------------------
    def on_patient_message(self, inbound: InboundMessage) -> TriggerResult:
        message = sick_message_from(inbound)
        conversation = self._load_open(message.patient_id)

        if conversation is not None and conversation.is_expired(self._clock.now(), self._timeout):
            self._expire(conversation)
            conversation = None

        if conversation is not None and conversation.state is ConversationState.AWAITING_PATIENT:
            conversation = conversation.receive_reply(message)
            self._audit(ACTOR, "patient_reply_received", conversation.case_id, message_id=message.message_id)
        else:
            conversation = Conversation.start(message, self._limits)
            self._audit(ACTOR, "case_opened", conversation.case_id, patient_id=message.patient_id)

        return self._advance(conversation)

    def sweep_timeouts(self) -> tuple[TriggerResult, ...]:
        now = self._clock.now()
        results = []
        for snapshot in self._store.list_awaiting_patient():
            conversation = conversation_from(snapshot, self._limits)
            if conversation.is_expired(now, self._timeout):
                results.append(self._expire(conversation))
        return tuple(results)

    # ---- workflow ---------------------------------------------------------------
    def _advance(self, conversation: Conversation) -> TriggerResult:
        conversation = self._screen.execute(conversation)
        missing = CompletenessPolicy.missing(conversation.report)
        step = conversation.decide(missing)

        if step is NextStep.ASK_FOLLOW_UP:
            conversation = self._follow_up.execute(conversation, missing)
            return self._save(conversation, PipelineOutcome.FOLLOW_UP_SENT)

        if step is NextStep.HAND_OFF_INCOMPLETE:
            conversation = conversation.hand_off_incomplete()
            self._assemble.execute(conversation, None)
            return self._save(conversation, PipelineOutcome.HANDED_OFF_INCOMPLETE)

        conversation = conversation.mark_ready()
        result = self._prefetch.execute(conversation)
        conversation = result.conversation
        self._assemble.execute(conversation, result)
        conversation = conversation.mark_handed_off()
        return self._save(conversation, PipelineOutcome.PACKET_DELIVERED)

    def _expire(self, conversation: Conversation) -> TriggerResult:
        conversation = conversation.expire(self._clock.now(), self._timeout)
        self._audit(ACTOR, "follow_up_timed_out", conversation.case_id,
                    asked_at=conversation.last_asked_at.isoformat() if conversation.last_asked_at else None)
        self._assemble.execute(conversation, None)
        return self._save(conversation, PipelineOutcome.HANDED_OFF_INCOMPLETE)

    def _load_open(self, patient_id: str) -> Conversation | None:
        snapshot = self._store.get_open(patient_id)
        return conversation_from(snapshot, self._limits) if snapshot is not None else None

    def _save(self, conversation: Conversation, outcome: PipelineOutcome) -> TriggerResult:
        self._store.put(snapshot_from(conversation))
        return TriggerResult(conversation.case_id, conversation.patient_id, outcome)
