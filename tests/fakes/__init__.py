"""Fake adapters for tests. They implement the real ports, record every call, and do no I/O."""

from tests.fakes.fakes import (
    FakeDrugDb, FakeEhr, FakeExtractSymptoms, FakeMatchFlags, FakeMessaging,
    FakePickRelevantItems, FakeReviewOutput, FakeSelectFollowUp, FixedClock,
    InMemoryAuditLog, InMemoryConversationStore,
)

__all__ = [
    "FakeDrugDb", "FakeEhr", "FakeExtractSymptoms", "FakeMatchFlags", "FakeMessaging",
    "FakePickRelevantItems", "FakeReviewOutput", "FakeSelectFollowUp", "FixedClock",
    "InMemoryAuditLog", "InMemoryConversationStore",
]
