"""TimelineEntry and ReviewPacket: findings placed on a timeline relative to symptom onset.

ADR-004: records appear exactly as documented, grouped into sections, with a
source on every row. There is deliberately no summary field anywhere.
How rows are ordered and formatted on screen is the presenter's job (ADR-014).
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum

from curaai.domain.chart_item import ChartItem
from curaai.domain.conversation import Conversation, ConversationState, IncompleteReason
from curaai.domain.completeness import CompletenessPolicy
from curaai.domain.drug_info import DrugInfo
from curaai.domain.errors import MissingSourceReference
from curaai.domain.sick_message import SickMessage
from curaai.domain.symptom_report import SymptomReport
from curaai.domain.values import ChartItemKind, Flag, ItemId, Origin, PatientId


class Section(Enum):
    PATIENT_MESSAGES = "patient_messages"
    MEDICATION_CHANGES = "medication_changes"
    CURRENT_MEDICATIONS = "current_medications"
    VISITS = "visits"
    LABS = "labs"
    DRUG_INFORMATION = "drug_information"
    AI_SUGGESTED_LOOKUPS = "ai_suggested_lookups"   # ADR-002: shown in a separately labeled section


SECTION_FOR_KIND = {
    ChartItemKind.MEDICATION: Section.MEDICATION_CHANGES,
    ChartItemKind.ENCOUNTER: Section.VISITS,
    ChartItemKind.LAB: Section.LABS,
}

_DRUG_FIELDS = (("class_text", "Drug class"), ("adverse_text", "Adverse reactions"),
                ("interactions_text", "Drug interactions"))


@dataclass(frozen=True)
class TimelineEntry:
    section: Section
    text: str                         # verbatim
    source_ref: str
    origin: Origin
    title: str | None = None
    day: date | None = None
    days_from_anchor: int | None = None   # negative = before onset
    author: str | None = None
    documented_flag: str | None = None    # e.g. "H" / "L" exactly as in the chart
    item_id: ItemId | None = None
    flags: frozenset[Flag] = frozenset()  # model-matched, validated by the core
    ai_selected: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise MissingSourceReference("every timeline entry needs a source_ref")
        if (self.section is Section.PATIENT_MESSAGES) != (self.origin is Origin.PATIENT):
            raise ValueError("patient words live only in PATIENT_MESSAGES, and that section holds only patient words")
        if (self.day is None) != (self.days_from_anchor is None):
            raise ValueError("day and days_from_anchor are set together")

    @classmethod
    def from_chart_item(cls, item: ChartItem, anchor: date, *, section: Section | None = None,
                        ai_selected: bool = False, flags: frozenset[Flag] = frozenset()) -> "TimelineEntry":
        return cls(
            section=section or SECTION_FOR_KIND[item.kind],
            text=item.detail,
            source_ref=item.source_ref,
            origin=Origin.CHART,
            title=item.title,
            day=item.date,
            days_from_anchor=(item.date - anchor).days,
            author=item.author,
            documented_flag=item.flag,
            item_id=item.item_id,
            flags=flags,
            ai_selected=ai_selected,
        )

    @classmethod
    def from_drug_info(cls, info: DrugInfo, *, section: Section = Section.DRUG_INFORMATION) -> tuple["TimelineEntry", ...]:
        """One entry per verbatim field, so nothing is merged or rewritten."""
        return tuple(
            cls(section=section, text=getattr(info, attr), source_ref=info.source_ref,
                origin=Origin.DRUG_DATABASE, title=f"{info.drug_name}: {label}",
                ai_selected=section is Section.AI_SUGGESTED_LOOKUPS)
            for attr, label in _DRUG_FIELDS if getattr(info, attr)
        )

    @classmethod
    def from_message(cls, message: SickMessage, anchor: date) -> "TimelineEntry":
        day = message.sent_at.date()
        return cls(section=Section.PATIENT_MESSAGES, text=message.text,
                   source_ref=f"message:{message.message_id}", origin=Origin.PATIENT,
                   day=day, days_from_anchor=(day - anchor).days)


class PacketStatus(Enum):
    PREFETCHED = "prefetched"         # chart history attached
    MESSAGES_ONLY = "messages_only"   # handed off without a chart pull


@dataclass(frozen=True)
class ReviewPacket:
    case_id: str
    patient_id: PatientId
    status: PacketStatus
    anchor_date: date
    report: SymptomReport
    entries: tuple[TimelineEntry, ...]
    incomplete_reason: IncompleteReason | None = None
    ai_fallback: bool = False
    rejected_item_count: int = 0
    requires_in_person_verification: bool = True   # ADR-006 / ADR-009 banner, always on

    def __post_init__(self) -> None:
        complete = CompletenessPolicy.is_complete(self.report)
        if self.status is PacketStatus.MESSAGES_ONLY:
            if self.incomplete_reason not in (IncompleteReason.TIMED_OUT, IncompleteReason.FOLLOW_UPS_EXHAUSTED):
                raise ValueError("a messages-only packet must say why it is incomplete")
            if any(e.section is not Section.PATIENT_MESSAGES for e in self.entries):
                raise ValueError("a messages-only packet carries no chart data")
        elif complete and self.incomplete_reason is not None:
            raise ValueError("a complete pre-fetched packet has no incomplete_reason")
        elif not complete and (self.incomplete_reason is not IncompleteReason.AI_UNAVAILABLE or not self.ai_fallback):
            raise ValueError("pre-fetch without onset and trend is allowed only as the AI fallback")
        if not self.requires_in_person_verification:
            raise ValueError("the in-person verification banner cannot be turned off")
        if self.rejected_item_count < 0:
            raise ValueError("rejected_item_count cannot be negative")

    # ---- factories that apply the handoff rules ------------------------------
    @classmethod
    def messages_only(cls, conversation: Conversation) -> "ReviewPacket":
        if conversation.state is not ConversationState.HANDED_OFF_INCOMPLETE:
            raise ValueError("messages-only packets are built for incomplete handoffs")
        anchor = conversation.anchor_date
        return cls(
            case_id=conversation.case_id, patient_id=conversation.patient_id,
            status=PacketStatus.MESSAGES_ONLY, anchor_date=anchor, report=conversation.report,
            entries=tuple(TimelineEntry.from_message(m, anchor) for m in conversation.messages),
            incomplete_reason=conversation.incomplete_reason, ai_fallback=conversation.ai_disabled,
        )

    @classmethod
    def prefetched(cls, conversation: Conversation, chart_entries: tuple[TimelineEntry, ...],
                   rejected_item_count: int = 0) -> "ReviewPacket":
        if conversation.state is not ConversationState.READY:
            raise ValueError("pre-fetched packets are built for cases that are READY")
        anchor = conversation.anchor_date
        complete = CompletenessPolicy.is_complete(conversation.report)
        messages = tuple(TimelineEntry.from_message(m, anchor) for m in conversation.messages)
        return cls(
            case_id=conversation.case_id, patient_id=conversation.patient_id,
            status=PacketStatus.PREFETCHED, anchor_date=anchor, report=conversation.report,
            entries=messages + chart_entries,
            incomplete_reason=None if complete else IncompleteReason.AI_UNAVAILABLE,
            ai_fallback=conversation.ai_disabled, rejected_item_count=rejected_item_count,
        )

    def entries_in(self, section: Section) -> tuple[TimelineEntry, ...]:
        return tuple(e for e in self.entries if e.section is section)
