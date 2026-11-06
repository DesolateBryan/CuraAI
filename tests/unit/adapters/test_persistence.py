"""Contract tests: the test fakes and the real adapters must behave the same (M2: "one contract test
against the real store"). Plus the JSONL serializer and a full pipeline run on the real adapters."""

import json
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from curaai.adapters.persistence import (
    InMemoryConversationStore, JsonlAuditLog, audit_event_from_json, audit_event_to_json, read_audit_log,
)
from curaai.application.dto.audit import AuditEvent
from curaai.application.dto.conversation import ConversationSnapshot
from curaai.application.dto.messaging import InboundMessage
from curaai.application.dto.model import SymptomExtraction
from curaai.application.ports import AuditLogPort, ConversationStorePort
from curaai.application.use_cases import PipelineOutcome
from tests import fakes
from tests.compose import build
from tests.fixtures.mockchart import inbound

TZ = timezone(timedelta(hours=-4))
T0 = datetime(2026, 10, 16, 8, 0, tzinfo=TZ)


def snap(case_id, patient_id="p1", state="awaiting_patient", sent=T0):
    return ConversationSnapshot(
        case_id=case_id, patient_id=patient_id, state=state,
        messages=(InboundMessage(case_id, patient_id, sent, "I feel dizzy"),),
        symptom_ids=("dizziness",), onset=None, onset_is_approx=False, trend=None, follow_ups=(),
        model_calls=1, lookups=0, ai_disabled=False, incomplete_reason=None)


# ---- ConversationStorePort contract ---------------------------------------------------
STORES = [fakes.InMemoryConversationStore, InMemoryConversationStore]


@pytest.mark.parametrize("make", STORES)
def test_store_contract_get_put_replace(make):
    store: ConversationStorePort = make()
    assert store.get_open("p1") is None
    store.put(snap("c1"))
    assert store.get_open("p1").case_id == "c1"
    store.put(snap("c1", state="handed_off"))                 # same case, replaced
    assert store.get_open("p1") is None                       # closed cases are not "open"


@pytest.mark.parametrize("make", STORES)
def test_store_contract_is_per_patient(make):
    store = make()
    store.put(snap("c1", patient_id="p1"))
    store.put(snap("c2", patient_id="p2", state="screening"))
    assert store.get_open("p2").case_id == "c2"
    assert store.get_open("p3") is None


@pytest.mark.parametrize("make", STORES)
def test_store_contract_lists_only_cases_waiting_on_the_patient(make):
    store = make()
    store.put(snap("c1", "p1", "awaiting_patient"))
    store.put(snap("c2", "p2", "handed_off_incomplete"))
    store.put(snap("c3", "p3", "ready"))
    assert [s.case_id for s in store.list_awaiting_patient()] == ["c1"]


def test_real_store_prefers_the_newest_open_case_and_is_thread_safe():
    store = InMemoryConversationStore()
    store.put(snap("old", sent=T0))
    store.put(snap("new", sent=T0 + timedelta(hours=1)))
    assert store.get_open("p1").case_id == "new"

    def writer(n):
        for i in range(200):
            store.put(snap(f"t{n}-{i}", patient_id=f"q{n}"))
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(store.list_awaiting_patient()) == 2 + 8 * 200


# ---- AuditLogPort contract --------------------------------------------------------------
def event(n=1, **detail):
    return AuditEvent(at=T0 + timedelta(seconds=n), actor="pipeline", action=f"step_{n}", subject_id="c1",
                      detail=detail or {"n": n})


def test_serializer_round_trips_and_is_one_line():
    e = event(detail_text="dizzy · nauseous", count=2, ok=True, missing=None)
    line = audit_event_to_json(e)
    assert "\n" not in line and json.loads(line)["v"] == 1
    assert audit_event_from_json(line) == e


def test_jsonl_log_appends_in_order_and_never_rewrites():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "logs" / "audit.jsonl"
        log: AuditLogPort = JsonlAuditLog(path)
        log.record(event(1))
        first_line = path.read_text(encoding="utf-8")
        JsonlAuditLog(path).record(event(2))                  # a second instance (restart) appends too
        assert path.read_text(encoding="utf-8").startswith(first_line)
        assert [e.action for e in read_audit_log(path)] == ["step_1", "step_2"]


def test_jsonl_log_has_no_update_or_delete():
    public = {n for n in dir(JsonlAuditLog) if not n.startswith("_")}
    assert public == {"record"}


def test_jsonl_lines_stay_whole_under_concurrent_writes():
    with tempfile.TemporaryDirectory() as tmp:
        log = JsonlAuditLog(Path(tmp) / "audit.jsonl")
        threads = [threading.Thread(target=lambda n=n: [log.record(event(n)) for _ in range(50)]) for n in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(read_audit_log(Path(tmp) / "audit.jsonl")) == 300


# ---- full pipeline on the real persistence adapters ----------------------------------------
def test_pipeline_survives_a_follow_up_round_trip_on_real_store_and_audit_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        h = build(extractor=fakes.FakeExtractSymptoms(
                      SymptomExtraction(("dizziness", "nausea"), None, False, None),
                      SymptomExtraction((), date(2026, 10, 5), True, "unchanged")),
                  store=InMemoryConversationStore(), audit_log=JsonlAuditLog(path))

        assert h.trigger.on_patient_message(inbound("p2")).outcome is PipelineOutcome.FOLLOW_UP_SENT
        h.clock.advance(hours=1)
        reply = inbound("p2", text="Started Oct 5, about the same.", sent_at=h.clock.now(), message_id="r1")
        assert h.trigger.on_patient_message(reply).outcome is PipelineOutcome.PACKET_DELIVERED

        actions = [e.action for e in read_audit_log(path)]
        assert actions[0] == "case_opened" and actions[-2:] == ["review_packet_delivered", "hitl_gate_opened"]
        assert "follow_up_sent" in actions and "patient_reply_received" in actions
        raw = path.read_text(encoding="utf-8")
        assert "dizzy and kind of nauseous" not in raw            # patient text is not written to the audit log
