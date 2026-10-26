from datetime import date, datetime, timedelta, timezone

import pytest

from curaai.domain.case_budget import CaseLimits
from curaai.domain.conversation import Conversation, ConversationState, IncompleteReason, NextStep
from curaai.domain.errors import InvalidConversationTransition
from curaai.domain.sick_message import SickMessage
from curaai.domain.symptom_report import SymptomReport
from curaai.domain.timeline import PacketStatus, ReviewPacket, Section, TimelineEntry
from curaai.domain.values import MessageId, MissingField, Origin, PatientId, QuestionId, Trend

TZ = timezone(timedelta(hours=-4))
T0 = datetime(2026, 10, 16, 8, 15, tzinfo=TZ)
BOTH = frozenset({MissingField.ONSET, MissingField.TREND})


def msg(i=1, at=T0, text="I feel dizzy"):
    return SickMessage(MessageId(f"m{i}"), PatientId("p2"), at, text)


def test_new_case_starts_screening_with_message_as_anchor():
    conv = Conversation.start(msg())
    assert conv.state is ConversationState.SCREENING
    assert conv.anchor_date == date(2026, 10, 16)
    assert conv.case_id == "m1"


def test_decide_follow_up_then_exhaust():
    conv = Conversation.start(msg(), CaseLimits(max_follow_ups=1))
    assert conv.decide(BOTH) is NextStep.ASK_FOLLOW_UP
    conv = conv.record_follow_up(QuestionId("ask_onset_and_trend"), T0)
    assert conv.state is ConversationState.AWAITING_PATIENT
    conv = conv.receive_reply(msg(2, T0 + timedelta(hours=1), "not sure"))
    assert conv.decide(BOTH) is NextStep.HAND_OFF_INCOMPLETE
    done = conv.hand_off_incomplete()
    assert done.incomplete_reason is IncompleteReason.FOLLOW_UPS_EXHAUSTED and not done.is_open


def test_complete_or_ai_off_goes_straight_to_prefetch():
    conv = Conversation.start(msg())
    assert conv.decide(frozenset()) is NextStep.PREFETCH
    assert conv.disable_ai().decide(BOTH) is NextStep.PREFETCH


def test_timeout_only_after_24_hours_and_only_while_waiting():
    conv = Conversation.start(msg()).record_follow_up(QuestionId("ask_onset"), T0)
    assert not conv.is_expired(T0 + timedelta(hours=23))
    with pytest.raises(InvalidConversationTransition):
        conv.expire(T0 + timedelta(hours=23))
    expired = conv.expire(T0 + timedelta(hours=24))
    assert expired.state is ConversationState.HANDED_OFF_INCOMPLETE
    assert expired.incomplete_reason is IncompleteReason.TIMED_OUT


def test_illegal_transitions_are_refused():
    conv = Conversation.start(msg())
    with pytest.raises(InvalidConversationTransition):
        conv.receive_reply(msg(2))
    with pytest.raises(InvalidConversationTransition):
        conv.mark_handed_off()


def test_onset_moves_the_anchor():
    conv = Conversation.start(msg()).with_report(SymptomReport(onset=date(2026, 10, 5), trend=Trend.UNCHANGED))
    assert conv.anchor_date == date(2026, 10, 5)


# ---- TimelineEntry / ReviewPacket -------------------------------------------------
def test_patient_words_are_always_labeled_patient():
    entry = TimelineEntry.from_message(msg(), anchor=date(2026, 10, 5))
    assert entry.origin is Origin.PATIENT and entry.section is Section.PATIENT_MESSAGES
    assert entry.days_from_anchor == 11
    with pytest.raises(ValueError):
        TimelineEntry(section=Section.LABS, text="x", source_ref="Observation/1", origin=Origin.PATIENT)


def test_messages_only_packet_has_no_chart_rows_and_keeps_the_banner():
    conv = Conversation.start(msg()).record_follow_up(QuestionId("ask_onset"), T0).expire(T0 + timedelta(days=1))
    packet = ReviewPacket.messages_only(conv)
    assert packet.status is PacketStatus.MESSAGES_ONLY
    assert {e.section for e in packet.entries} == {Section.PATIENT_MESSAGES}
    assert packet.requires_in_person_verification


def test_prefetch_without_onset_is_only_allowed_as_ai_fallback():
    ready = Conversation.start(msg()).mark_ready()
    with pytest.raises(ValueError):
        ReviewPacket.prefetched(ready, ())          # AI still on, onset unknown: refused
    packet = ReviewPacket.prefetched(Conversation.start(msg()).disable_ai().mark_ready(), ())
    assert packet.incomplete_reason is IncompleteReason.AI_UNAVAILABLE and packet.ai_fallback


def test_banner_cannot_be_switched_off():
    conv = Conversation.start(msg()).with_report(SymptomReport(onset=date(2026, 10, 5), trend=Trend.UNCHANGED))
    good = ReviewPacket.prefetched(conv.mark_ready(), ())
    with pytest.raises(ValueError):
        ReviewPacket(**{**good.__dict__, "requires_in_person_verification": False})
