"""Mappers between DTOs and Ring 1 entities (ADR-012).

Inward: DTO -> entity (the entity's own checks run, e.g. missing source_ref).
Outward: entity -> DTO (no entity ever leaves Ring 2).
All functions are pure.
"""

from curaai.application.dto.conversation import AskedFollowUpSnapshot, ConversationSnapshot
from curaai.application.dto.drug import DrugRecord
from curaai.application.dto.ehr import ChartItemRecord
from curaai.application.dto.messaging import InboundMessage
from curaai.application.dto.review import ReviewResponse, ReviewRow
from curaai.application.errors import RejectedInboundMessage
from curaai.domain.case_budget import CaseBudget, CaseLimits
from curaai.domain.chart_item import ChartItem
from curaai.domain.conversation import AskedFollowUp, Conversation, ConversationState, IncompleteReason
from curaai.domain.drug_info import DrugInfo
from curaai.domain.sick_message import SickMessage
from curaai.domain.symptom_catalog import SymptomCatalog
from curaai.domain.symptom_report import SymptomReport
from curaai.domain.timeline import ReviewPacket
from curaai.domain.values import (
    ChartItemKind, ItemId, MessageId, Origin, PatientId, QuestionId, SymptomId, Trend,
)


# ---- messages -------------------------------------------------------------
def sick_message_from(dto: InboundMessage) -> SickMessage:
    if dto.origin != Origin.PATIENT.value:
        raise RejectedInboundMessage("only patient-originated messages start or continue a case")
    try:
        return SickMessage(MessageId(dto.message_id), PatientId(dto.patient_id), dto.sent_at, dto.text)
    except ValueError as exc:
        raise RejectedInboundMessage(str(exc)) from exc


def inbound_from(message: SickMessage) -> InboundMessage:
    return InboundMessage(message.message_id, message.patient_id, message.sent_at, message.text,
                          message.origin.value)


# ---- chart and drug records ----------------------------------------------
def chart_item_from(record: ChartItemRecord) -> ChartItem:
    return ChartItem(
        item_id=ItemId(record.item_id), kind=ChartItemKind(record.kind), date=record.date,
        title=record.title, detail=record.detail, source_ref=record.source_ref,
        author=record.author, end_date=record.end_date, flag=record.flag,
        code=record.code, code_system=record.code_system, stopped=record.stopped,
    )


def drug_info_from(record: DrugRecord) -> DrugInfo:
    return DrugInfo(drug_name=record.drug_name, source_ref=record.source_ref,
                    class_text=record.class_text, adverse_text=record.adverse_text,
                    interactions_text=record.interactions_text,
                    boxed_warning_text=record.boxed_warning_text,
                    contraindications_text=record.contraindications_text)


# ---- conversation snapshots ----------------------------------------------
def snapshot_from(conversation: Conversation) -> ConversationSnapshot:
    report = conversation.report
    return ConversationSnapshot(
        case_id=conversation.case_id,
        patient_id=conversation.patient_id,
        state=conversation.state.value,
        messages=tuple(inbound_from(m) for m in conversation.messages),
        symptom_ids=tuple(sorted(report.symptom_ids)),
        onset=report.onset,
        onset_is_approx=report.onset_is_approx,
        trend=report.trend.value if report.trend else None,
        follow_ups=tuple(AskedFollowUpSnapshot(f.question_id, f.asked_at) for f in conversation.follow_ups),
        model_calls=conversation.budget.model_calls,
        lookups=conversation.budget.lookups,
        ai_disabled=conversation.ai_disabled,
        incomplete_reason=conversation.incomplete_reason.value if conversation.incomplete_reason else None,
    )


def conversation_from(snapshot: ConversationSnapshot, limits: CaseLimits) -> Conversation:
    return Conversation(
        case_id=snapshot.case_id,
        patient_id=PatientId(snapshot.patient_id),
        messages=tuple(sick_message_from(m) for m in snapshot.messages),
        state=ConversationState(snapshot.state),
        report=SymptomReport(
            symptom_ids=frozenset(SymptomId(s) for s in snapshot.symptom_ids),
            onset=snapshot.onset,
            onset_is_approx=snapshot.onset_is_approx,
            trend=Trend(snapshot.trend) if snapshot.trend else None,
        ),
        follow_ups=tuple(AskedFollowUp(QuestionId(f.question_id), f.asked_at) for f in snapshot.follow_ups),
        budget=CaseBudget(limits=limits, model_calls=snapshot.model_calls, lookups=snapshot.lookups,
                          follow_ups=len(snapshot.follow_ups)),
        ai_disabled=snapshot.ai_disabled,
        incomplete_reason=IncompleteReason(snapshot.incomplete_reason) if snapshot.incomplete_reason else None,
    )


# ---- review output --------------------------------------------------------
def review_response_from(packet: ReviewPacket, catalog: SymptomCatalog) -> ReviewResponse:
    report = packet.report
    return ReviewResponse(
        case_id=packet.case_id,
        patient_id=packet.patient_id,
        status=packet.status.value,
        incomplete_reason=packet.incomplete_reason.value if packet.incomplete_reason else None,
        anchor_date=packet.anchor_date,
        onset=report.onset,
        onset_is_approx=report.onset_is_approx,
        trend=report.trend.value if report.trend else None,
        symptom_labels=tuple(sorted(catalog.get(s).label for s in report.symptom_ids)),
        rows=tuple(
            ReviewRow(
                section=e.section.value, text=e.text, source_ref=e.source_ref, origin=e.origin.value,
                title=e.title, day=e.day, days_from_anchor=e.days_from_anchor, author=e.author,
                documented_flag=e.documented_flag, flags=tuple(sorted(f.value for f in e.flags)),
                ai_selected=e.ai_selected,
            )
            for e in packet.entries
        ),
        ai_fallback=packet.ai_fallback,
        rejected_item_count=packet.rejected_item_count,
        requires_in_person_verification=packet.requires_in_person_verification,
    )
