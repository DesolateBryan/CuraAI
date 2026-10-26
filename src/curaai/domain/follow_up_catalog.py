"""FollowUpCatalog: the only questions CuraAI may send to a patient.

ADR-009: the AI may send follow-up questions only from a clinician-approved
catalog, never free text. A question is eligible only if everything it asks for
is actually missing, so the patient is asked only about the missing details.
"""

from dataclasses import dataclass

from curaai.domain.errors import UnknownCatalogEntry
from curaai.domain.values import MissingField, QuestionId, require_text


@dataclass(frozen=True)
class FollowUpQuestion:
    id: QuestionId
    asks_for: frozenset[MissingField]
    text: str

    def __post_init__(self) -> None:
        require_text(self.id, "FollowUpQuestion.id")
        require_text(self.text, "FollowUpQuestion.text")
        if not self.asks_for:
            raise ValueError("a follow-up question must ask for at least one missing field")


@dataclass(frozen=True)
class FollowUpCatalog:
    questions: tuple[FollowUpQuestion, ...]

    def __post_init__(self) -> None:
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("FollowUpCatalog ids must be unique")
        covered = frozenset().union(*(q.asks_for for q in self.questions)) if self.questions else frozenset()
        if covered != frozenset(MissingField):
            raise ValueError("FollowUpCatalog must cover every MissingField")

    def get(self, question_id: str) -> FollowUpQuestion:
        for question in self.questions:
            if question.id == question_id:
                return question
        raise UnknownCatalogEntry(f"follow-up question not in catalog: {question_id!r}")

    def eligible(self, missing: frozenset[MissingField]) -> tuple[FollowUpQuestion, ...]:
        """Questions that ask only about fields that are actually missing."""
        return tuple(q for q in self.questions if q.asks_for <= missing)

    def best_for(self, missing: frozenset[MissingField]) -> FollowUpQuestion:
        """Deterministic choice used when the model is unavailable: widest coverage, then id."""
        candidates = self.eligible(missing)
        if not candidates:
            raise UnknownCatalogEntry(f"no catalog question for {sorted(m.value for m in missing)}")
        return sorted(candidates, key=lambda q: (-len(q.asks_for), q.id))[0]


# Team decision (2026-10-26): every follow-up is labeled as automated, so a patient never
# mistakes a CuraAI question for a message written by their doctor. EHR adapters must show it.
AUTOMATED_SENDER_LABEL = "Automated question from CuraAI"

# DRAFT, pending clinician sign-off (ADR-009).
DEFAULT_FOLLOW_UP_CATALOG = FollowUpCatalog((
    FollowUpQuestion(
        QuestionId("ask_onset"),
        frozenset({MissingField.ONSET}),
        "When did these symptoms first start? An approximate date is fine.",
    ),
    FollowUpQuestion(
        QuestionId("ask_trend"),
        frozenset({MissingField.TREND}),
        # Worded without "start"/"when" so it reads as a trend question on its own
        "Have your symptoms been getting better, getting worse, or staying about the same?",
    ),
    FollowUpQuestion(
        QuestionId("ask_onset_and_trend"),
        frozenset({MissingField.ONSET, MissingField.TREND}),
        "When did these symptoms first start (an approximate date is fine), and since then "
        "have they gotten better, gotten worse, or stayed about the same?",
    ),
))
