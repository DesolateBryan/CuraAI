"""RequestFollowUp: ask the patient only for the details that are missing.

The model may choose WHICH catalog question to send, from candidates the core
picked. It never writes the text. If the model cannot help, the catalog's
deterministic default is used, so a question always goes out (ADR-009).
"""

from curaai.application.dto.messaging import OutboundFollowUp
from curaai.application.dto.model import FollowUpRequest
from curaai.application.errors import ModelOutputRejected, ModelUnavailable
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.messaging_port import PatientMessagingPort
from curaai.application.ports.model_ports import SelectFollowUpPort
from curaai.application.use_cases._audit import Auditor
from curaai.application.validation.model_output_validator import ModelOutputValidator
from curaai.domain.conversation import Conversation
from curaai.domain.follow_up_catalog import AUTOMATED_SENDER_LABEL, FollowUpCatalog, FollowUpQuestion
from curaai.domain.values import MissingField

ACTOR = "request_follow_up"


class RequestFollowUp:
    def __init__(self, selector: SelectFollowUpPort, validator: ModelOutputValidator,
                 catalog: FollowUpCatalog, messaging: PatientMessagingPort,
                 audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._selector = selector
        self._validator = validator
        self._catalog = catalog
        self._messaging = messaging
        self._clock = clock
        self._audit = Auditor(audit_log, clock)

    def execute(self, conversation: Conversation, missing: frozenset[MissingField]) -> Conversation:
        case = conversation.case_id
        eligible_ids = frozenset(q.id for q in self._catalog.eligible(missing))
        question: FollowUpQuestion | None = None
        chosen_by = "catalog_default"

        if not conversation.ai_disabled and conversation.budget.can_call_model():
            request = FollowUpRequest(
                request_id=f"{case}:follow_up:{conversation.budget.model_calls + 1}",
                missing=frozenset(m.value for m in missing),
                candidate_question_ids=eligible_ids,
            )
            conversation = conversation.spend_model_call()
            try:
                question_id = self._validator.follow_up(self._selector.select(request), eligible_ids)
                question = self._catalog.get(question_id)
                chosen_by = "model"
            except ModelUnavailable as exc:
                self._audit(ACTOR, "model_unavailable", case, request_id=request.request_id, error=str(exc))
            except ModelOutputRejected as exc:
                self._audit("validator", "model_output_rejected", case, request_id=request.request_id,
                            port="select_follow_up", reason=exc.reason)

        if question is None:
            question = self._catalog.best_for(missing)

        self._messaging.send_follow_up(OutboundFollowUp(conversation.patient_id, question.id,
                                                        question.text, AUTOMATED_SENDER_LABEL))
        conversation = conversation.record_follow_up(question.id, self._clock.now())
        self._audit(ACTOR, "follow_up_sent", case, question_id=question.id, chosen_by=chosen_by,
                    missing=",".join(sorted(m.value for m in missing)),
                    follow_up_number=conversation.budget.follow_ups)
        return conversation
