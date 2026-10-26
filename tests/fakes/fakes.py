from datetime import date, datetime, timedelta

from curaai.application.dto.audit import AuditEvent
from curaai.application.dto.conversation import AWAITING_PATIENT_VALUE, OPEN_STATE_VALUES, ConversationSnapshot
from curaai.application.dto.drug import DrugQuery, DrugRecord
from curaai.application.dto.ehr import ActiveMedicationQuery, ChartItemRecord, ChartQuery
from curaai.application.dto.messaging import OutboundFollowUp
from curaai.application.dto.model import (
    ExtractionRequest, FlagMatch, FlagMatchRequest, FollowUpChoice, FollowUpRequest,
    ItemSelection, SelectionRequest, SymptomExtraction,
)
from curaai.application.dto.review import ReviewResponse
from curaai.application.errors import ModelUnavailable
from curaai.application.ports import (
    AuditLogPort, ClockPort, ConversationStorePort, DrugDbPort, EhrPort, ExtractSymptomsPort,
    MatchFlagsPort, PatientMessagingPort, PickRelevantItemsPort, ReviewOutputPort, SelectFollowUpPort,
)


# ---- time -------------------------------------------------------------------
class FixedClock(ClockPort):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now = self._now + timedelta(**kwargs)


# ---- EHR and drug database ---------------------------------------------------
def _overlaps(r: ChartItemRecord, start: date, end: date) -> bool:
    return start <= r.date <= end or (r.end_date is not None and start <= r.end_date <= end)


class FakeEhr(EhrPort):
    def __init__(self, records: dict[str, tuple[ChartItemRecord, ...]]) -> None:
        self._records = records
        self.queries: list[object] = []

    def items_between(self, query: ChartQuery) -> tuple[ChartItemRecord, ...]:
        self.queries.append(query)
        return tuple(r for r in self._records.get(query.patient_id, ()) if _overlaps(r, query.from_date, query.to_date))

    def active_medications(self, query: ActiveMedicationQuery) -> tuple[ChartItemRecord, ...]:
        self.queries.append(query)
        return tuple(r for r in self._records.get(query.patient_id, ())
                     if r.kind == "medication" and not r.stopped and r.date <= query.on_date
                     and (r.end_date is None or r.end_date > query.on_date))


class FakeDrugDb(DrugDbPort):
    def __init__(self, records: dict[str, DrugRecord]) -> None:
        self._records = records
        self.queries: list[DrugQuery] = []

    def lookup(self, query: DrugQuery) -> DrugRecord | None:
        self.queries.append(query)
        name = query.drug_name.casefold()
        return next((r for key, r in self._records.items() if key in name), None)


# ---- model ports (scripted) ----------------------------------------------------
class FakeExtractSymptoms(ExtractSymptomsPort):
    """Returns scripted answers in order. An Exception in the script is raised instead."""

    def __init__(self, *script: SymptomExtraction | Exception) -> None:
        self._script = list(script)
        self.requests: list[ExtractionRequest] = []

    def extract(self, request: ExtractionRequest) -> SymptomExtraction:
        self.requests.append(request)
        if not self._script:
            raise ModelUnavailable("fake: script exhausted")
        answer = self._script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeSelectFollowUp(SelectFollowUpPort):
    """Picks `choice` if given, else the alphabetically first candidate."""

    def __init__(self, choice: str | Exception | None = None) -> None:
        self._choice = choice
        self.requests: list[FollowUpRequest] = []

    def select(self, request: FollowUpRequest) -> FollowUpChoice:
        self.requests.append(request)
        if isinstance(self._choice, Exception):
            raise self._choice
        return FollowUpChoice(self._choice or sorted(request.candidate_question_ids)[0])


class FakePickRelevantItems(PickRelevantItemsPort):
    """Selects items whose label is in `labels`; `raw_ids` returns ids verbatim (to test validation)."""

    def __init__(self, labels: set[str] = frozenset(), raw_ids: tuple[str, ...] | None = None) -> None:
        self._labels = {l.casefold() for l in labels}
        self._raw_ids = raw_ids
        self.requests: list[SelectionRequest] = []

    def pick(self, request: SelectionRequest) -> ItemSelection:
        self.requests.append(request)
        if self._raw_ids is not None:
            return ItemSelection(self._raw_ids)
        return ItemSelection(tuple(i.item_id for i in request.items if i.label.casefold() in self._labels))


class FakeMatchFlags(MatchFlagsPort):
    """`rules` maps a label to a flag id; every item with that label gets the flag."""

    def __init__(self, rules: dict[str, str] | None = None) -> None:
        self._rules = {k.casefold(): v for k, v in (rules or {}).items()}
        self.requests: list[FlagMatchRequest] = []

    def match(self, request: FlagMatchRequest) -> tuple[FlagMatch, ...]:
        self.requests.append(request)
        return tuple(FlagMatch(i.item_id, self._rules[i.label.casefold()])
                     for i in request.items if i.label.casefold() in self._rules)


# ---- outputs and stores -----------------------------------------------------------
class FakeMessaging(PatientMessagingPort):
    def __init__(self) -> None:
        self.sent: list[OutboundFollowUp] = []

    def send_follow_up(self, follow_up: OutboundFollowUp) -> None:
        self.sent.append(follow_up)


class FakeReviewOutput(ReviewOutputPort):
    def __init__(self) -> None:
        self.presented: list[ReviewResponse] = []

    def present(self, response: ReviewResponse) -> None:
        self.presented.append(response)


class InMemoryAuditLog(AuditLogPort):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[str]:
        return [e.action for e in self.events]


class InMemoryConversationStore(ConversationStorePort):
    def __init__(self) -> None:
        self.by_case: dict[str, ConversationSnapshot] = {}

    def get_open(self, patient_id: str) -> ConversationSnapshot | None:
        return next((s for s in self.by_case.values()
                     if s.patient_id == patient_id and s.state in OPEN_STATE_VALUES), None)

    def put(self, snapshot: ConversationSnapshot) -> None:
        self.by_case[snapshot.case_id] = snapshot

    def list_awaiting_patient(self) -> tuple[ConversationSnapshot, ...]:
        return tuple(s for s in self.by_case.values() if s.state == AWAITING_PATIENT_VALUE)
