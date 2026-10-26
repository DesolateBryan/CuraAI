"""ADR-009 / ADR-010: no port can write to the chart, order anything, or send free text."""

import inspect

import curaai.application.ports as ports
from curaai.application.dto.messaging import OutboundFollowUp

ALLOWED_METHODS = {
    "AuditLogPort": {"record"},                         # append-only
    "ClockPort": {"now"},
    "ConversationStorePort": {"get_open", "put", "list_awaiting_patient"},
    "DrugDbPort": {"lookup"},
    "EhrPort": {"items_between", "active_medications"},
    "ExtractSymptomsPort": {"extract"},
    "MatchFlagsPort": {"match"},
    "PatientMessagingPort": {"send_follow_up"},
    "PickRelevantItemsPort": {"pick"},
    "ReviewOutputPort": {"present"},
    "SelectFollowUpPort": {"select"},
}


def test_every_port_exposes_only_its_allow_listed_methods():
    found = {name: set(getattr(ports, name).__abstractmethods__) for name in ports.__all__}
    assert found == ALLOWED_METHODS


def test_ehr_and_drug_ports_have_no_write_shaped_methods():
    write_words = ("write", "create", "update", "delete", "order", "prescribe", "post", "put", "save")
    for port in (ports.EhrPort, ports.DrugDbPort):
        names = [n for n, _ in inspect.getmembers(port, inspect.isfunction)]
        assert not [n for n in names if any(w in n for w in write_words)], port.__name__


def test_outbound_follow_up_carries_a_catalog_question_id_and_a_required_automated_label():
    fields = set(OutboundFollowUp.__dataclass_fields__)
    assert fields == {"patient_id", "question_id", "text", "sender_label"}
    import pytest
    with pytest.raises(ValueError):
        OutboundFollowUp("p1", "ask_onset", "When did these symptoms first start?", "  ")
