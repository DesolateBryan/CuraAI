"""ScreenSickMessage: read the latest patient message for symptoms, onset and trend.

Only the patient's own words go to the model (ADR-002). The answer is validated
by the core before it touches the case. If the model is unavailable, over its
cap, or gives an answer the validator rejects, AI is switched off for the case
and the fixed chart pull takes over (ADR-011).
"""

from curaai.application.dto.model import ExtractionRequest
from curaai.application.errors import ModelOutputRejected, ModelUnavailable
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.model_ports import ExtractSymptomsPort
from curaai.application.use_cases._audit import Auditor
from curaai.application.validation.model_output_validator import ModelOutputValidator
from curaai.domain.conversation import Conversation
from curaai.domain.symptom_catalog import SymptomCatalog

ACTOR = "screen_sick_message"


class ScreenSickMessage:
    def __init__(self, extractor: ExtractSymptomsPort, validator: ModelOutputValidator,
                 catalog: SymptomCatalog, audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._extractor = extractor
        self._validator = validator
        self._catalog = catalog
        self._audit = Auditor(audit_log, clock)

    def execute(self, conversation: Conversation) -> Conversation:
        case = conversation.case_id
        if conversation.ai_disabled:
            return conversation
        if not conversation.budget.can_call_model():
            self._audit(ACTOR, "ai_cap_reached", case, limit="max_model_calls")
            return conversation.disable_ai()

        message = conversation.latest_message
        request = ExtractionRequest(
            request_id=f"{case}:extract:{conversation.budget.model_calls + 1}",
            message_text=message.text,
            reference_date=message.sent_at.date(),
            catalog_ids=self._catalog.ids(),
        )
        conversation = conversation.spend_model_call()
        try:
            raw = self._extractor.extract(request)
            report = self._validator.extraction(raw, request.reference_date)
        except ModelUnavailable as exc:
            self._audit(ACTOR, "model_unavailable", case, request_id=request.request_id, error=str(exc))
            return conversation.disable_ai()
        except ModelOutputRejected as exc:
            self._audit("validator", "model_output_rejected", case, request_id=request.request_id,
                        port="extract_symptoms", reason=exc.reason)
            return conversation.disable_ai()

        self._audit("validator", "model_output_accepted", case, request_id=request.request_id,
                    port="extract_symptoms", symptom_count=len(report.symptom_ids),
                    onset_found=report.onset is not None, trend_found=report.trend is not None)
        return conversation.with_report(report)
