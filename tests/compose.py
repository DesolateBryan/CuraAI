"""Test composition root (ADR-015): the same use cases as app/main.py, wired to fakes and a fixed clock.

This is the Testing API (CS302 Lab 5): the only test module that constructs ports.
Tests call build(...) and drive the system through PipelineTrigger and
RecordPhysicianDecision, never through UI selectors. Every model port is a fake, so
business-rule tests never call a live model (tests/conftest.py also blocks the network).
"""

from dataclasses import dataclass, field
from datetime import datetime

from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.conversation_store_port import ConversationStorePort
from curaai.application.ports.drug_db_port import DrugDbPort
from curaai.application.ports.ehr_port import EhrPort
from curaai.application.ports.review_output_port import ReviewOutputPort
from curaai.application.ports.model_ports import (
    ExtractSymptomsPort, MatchFlagsPort, PickRelevantItemsPort, SelectFollowUpPort,
)
from curaai.application.use_cases import (
    AssembleReviewPacket, PipelineTrigger, PrefetchHistory, RecordPhysicianDecision, RequestFollowUp,
    ScreenSickMessage,
)
from curaai.application.validation import ModelOutputValidator
from curaai.domain.case_budget import CaseLimits
from curaai.domain.follow_up_catalog import DEFAULT_FOLLOW_UP_CATALOG
from curaai.domain.follow_up_timeout import FollowUpTimeout
from curaai.domain.symptom_catalog import DEFAULT_SYMPTOM_CATALOG
from tests.fakes import (
    FakeDrugDb, FakeEhr, FakeExtractSymptoms, FakeMatchFlags, FakeMessaging, FakePhysicianReplies,
    FakePickRelevantItems, FakeReviewGates, FakeReviewOutput, FakeSelectFollowUp, FixedClock, InMemoryAuditLog,
    InMemoryConversationStore,
)

APPROVERS = frozenset({"dr-demo"})
from tests.fixtures.mockchart import NOW, PATIENTS, chart_records, drug_records


@dataclass
class Harness:
    trigger: PipelineTrigger
    clock: FixedClock
    ehr: EhrPort
    drug_db: DrugDbPort
    extractor: ExtractSymptomsPort
    selector: SelectFollowUpPort
    picker: PickRelevantItemsPort
    flagger: MatchFlagsPort
    messaging: FakeMessaging
    review: ReviewOutputPort
    audit: AuditLogPort
    store: ConversationStorePort
    prefetch: PrefetchHistory = field(repr=False)
    decisions: RecordPhysicianDecision = field(repr=False, default=None)
    gates: FakeReviewGates = field(repr=False, default=None)
    replies: FakePhysicianReplies = field(repr=False, default=None)


def build(*, extractor: ExtractSymptomsPort | None = None, selector: SelectFollowUpPort | None = None,
          picker: PickRelevantItemsPort | None = None, flagger: MatchFlagsPort | None = None,
          ehr: EhrPort | None = None, drug_db: DrugDbPort | None = None,
          review_output: ReviewOutputPort | None = None,
          store: ConversationStorePort | None = None, audit_log: AuditLogPort | None = None, limits: CaseLimits = CaseLimits(), now: datetime = NOW) -> Harness:
    clock = FixedClock(now)
    ehr = ehr or FakeEhr({pid: chart_records(pid) for pid in PATIENTS})
    drug_db = drug_db or FakeDrugDb(drug_records())
    extractor = extractor or FakeExtractSymptoms()
    selector = selector or FakeSelectFollowUp()
    picker = picker or FakePickRelevantItems()
    flagger = flagger or FakeMatchFlags()
    messaging, review = FakeMessaging(), review_output or FakeReviewOutput()
    audit = audit_log or InMemoryAuditLog()
    store = store or InMemoryConversationStore()

    validator = ModelOutputValidator(DEFAULT_SYMPTOM_CATALOG)
    screen = ScreenSickMessage(extractor, validator, DEFAULT_SYMPTOM_CATALOG, audit, clock)
    follow_up = RequestFollowUp(selector, validator, DEFAULT_FOLLOW_UP_CATALOG, messaging, audit, clock)
    prefetch = PrefetchHistory(ehr, drug_db, picker, flagger, validator, audit, clock)
    gates, replies = FakeReviewGates(), FakePhysicianReplies()
    assemble = AssembleReviewPacket(review, gates, DEFAULT_SYMPTOM_CATALOG, audit, clock)
    trigger = PipelineTrigger(store, screen, follow_up, prefetch, assemble, audit, clock,
                              limits=limits, timeout=FollowUpTimeout())
    decisions = RecordPhysicianDecision(gates, replies, APPROVERS, audit, clock)

    return Harness(trigger, clock, ehr, drug_db, extractor, selector, picker, flagger,
                   messaging, review, audit, store, prefetch, decisions, gates, replies)
