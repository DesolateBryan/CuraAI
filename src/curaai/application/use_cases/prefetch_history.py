"""PrefetchHistory: the fixed 3-week chart pull, plus optional validated AI help.

1. Baseline (deterministic, always runs, ADR-002):
     * medication changes, labs and encounters inside the LookbackWindow
     * the current active medication list
     * verbatim drug-database text for every medication CHANGED in the window
2. AI help (optional, capped, validated, ADR-002 / ADR-013):
     * PickRelevantItems marks rows relevant to the symptoms
     * MatchFlags attaches flags to medication rows
     * drug lookups for AI-selected current medications not already covered,
       shown in a separate AI_SUGGESTED_LOOKUPS section, max CaseLimits.max_lookups
   The model sees only item ids and short labels (drug or lab names), never chart text.

Any record that fails an entity check (e.g. no source_ref) or falls outside the
window is dropped, audited and counted, so the physician sees that rows were withheld.
"""

from dataclasses import dataclass

from curaai.application.dto.drug import DrugQuery
from curaai.application.dto.ehr import ActiveMedicationQuery, ChartItemRecord, ChartQuery
from curaai.application.dto.model import FlagMatchRequest, LabeledItem, SelectionRequest
from curaai.application.errors import ExternalSourceUnavailable, ModelOutputRejected, ModelUnavailable
from curaai.application.mapping import chart_item_from, drug_info_from
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort
from curaai.application.ports.drug_db_port import DrugDbPort
from curaai.application.ports.ehr_port import EhrPort
from curaai.application.ports.model_ports import MatchFlagsPort, PickRelevantItemsPort
from curaai.application.use_cases._audit import Auditor
from curaai.application.validation.model_output_validator import ModelOutputValidator
from curaai.domain.chart_item import ChartItem
from curaai.domain.conversation import Conversation
from curaai.domain.drug_info import DrugInfo
from curaai.domain.errors import DomainError
from curaai.domain.lookback import LookbackWindow
from curaai.domain.timeline import Section, TimelineEntry
from curaai.domain.values import ChartItemKind, Flag, ItemId

ACTOR = "prefetch_history"


@dataclass(frozen=True)
class PrefetchResult:
    conversation: Conversation            # updated budget / ai_disabled
    window: LookbackWindow
    entries: tuple[TimelineEntry, ...]
    rejected_item_count: int


class PrefetchHistory:
    def __init__(self, ehr: EhrPort, drug_db: DrugDbPort, picker: PickRelevantItemsPort,
                 flagger: MatchFlagsPort, validator: ModelOutputValidator,
                 audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._ehr = ehr
        self._drug_db = drug_db
        self._picker = picker
        self._flagger = flagger
        self._validator = validator
        self._clock = clock
        self._audit = Auditor(audit_log, clock)

    def execute(self, conversation: Conversation) -> PrefetchResult:
        case, patient = conversation.case_id, conversation.patient_id
        today = self._clock.today()
        anchor = conversation.anchor_date
        window = LookbackWindow.for_onset(anchor, today)

        # ---- 1. fixed baseline pull ------------------------------------------
        rejected = 0
        changes, n = self._accept(self._ehr.items_between(ChartQuery(patient, window.start, window.end)), case,
                                  keep=lambda i: i.is_change_within(window), why="outside_window")
        rejected += n
        current, n = self._accept(self._ehr.active_medications(ActiveMedicationQuery(patient, today)), case,
                                  keep=lambda i: i.is_active_medication_on(today), why="not_active")
        rejected += n
        self._audit(ACTOR, "chart_pulled", case, window_start=window.start.isoformat(),
                    window_end=window.end.isoformat(), changes=len(changes), current_meds=len(current))

        changed_meds = [i for i in changes if i.kind is ChartItemKind.MEDICATION]
        baseline_drugs, n = self._lookup_drugs(_distinct_titles(changed_meds), case)
        rejected += n

        # ---- 2. optional AI help ---------------------------------------------
        selected: frozenset[ItemId] = frozenset()
        flags: dict[ItemId, frozenset[Flag]] = {}
        ai_drugs: list[DrugInfo] = []
        all_items = _distinct_items(changes + current)
        if conversation.report.symptom_ids and all_items:
            conversation, selected = self._pick(conversation, all_items)
            meds = [i for i in all_items if i.kind is ChartItemKind.MEDICATION]
            if meds:
                conversation, flags = self._flag(conversation, meds)
            conversation, ai_drugs, n = self._ai_lookups(conversation, current, selected, baseline_drugs)
            rejected += n

        # ---- 3. timeline entries ---------------------------------------------
        def entry(item: ChartItem, section: Section | None = None) -> TimelineEntry:
            return TimelineEntry.from_chart_item(item, anchor, section=section,
                                                 ai_selected=item.item_id in selected,
                                                 flags=flags.get(item.item_id, frozenset()))

        entries: list[TimelineEntry] = [entry(i) for i in changes]
        entries += [entry(i, Section.CURRENT_MEDICATIONS) for i in current]
        for info in baseline_drugs:
            entries += TimelineEntry.from_drug_info(info)
        for info in ai_drugs:
            entries += TimelineEntry.from_drug_info(info, section=Section.AI_SUGGESTED_LOOKUPS)

        return PrefetchResult(conversation, window, tuple(entries), rejected)

    # ---- baseline helpers -------------------------------------------------------
    def _accept(self, records: tuple[ChartItemRecord, ...], case: str, keep, why: str) -> tuple[list[ChartItem], int]:
        accepted, rejected = [], 0
        for record in records:
            try:
                item = chart_item_from(record)
            except (DomainError, ValueError) as exc:
                rejected += 1
                self._audit(ACTOR, "chart_item_rejected", case, item_id=record.item_id, reason=str(exc))
                continue
            if not keep(item):
                rejected += 1
                self._audit(ACTOR, "chart_item_rejected", case, item_id=item.item_id, reason=why)
                continue
            accepted.append(item)
        return accepted, rejected

    def _lookup_drugs(self, names: list[str], case: str) -> tuple[list[DrugInfo], int]:
        infos, rejected = [], 0
        for name in names:
            try:
                record = self._drug_db.lookup(DrugQuery(name))
            except ExternalSourceUnavailable as exc:
                self._audit(ACTOR, "drug_lookup_failed", case, drug=name, error=str(exc))
                continue
            if record is None:
                self._audit(ACTOR, "drug_not_found", case, drug=name)
                continue
            try:
                infos.append(drug_info_from(record))
            except (DomainError, ValueError) as exc:
                rejected += 1
                self._audit(ACTOR, "drug_record_rejected", case, drug=name, reason=str(exc))
        return infos, rejected

    # ---- AI helpers ---------------------------------------------------------------
    def _pick(self, conv: Conversation, items: list[ChartItem]) -> tuple[Conversation, frozenset[ItemId]]:
        if not self._can_call(conv, "pick_relevant_items"):
            return self._off(conv), frozenset()
        request = SelectionRequest(
            request_id=f"{conv.case_id}:pick:{conv.budget.model_calls + 1}",
            symptom_ids=frozenset(conv.report.symptom_ids),
            items=tuple(LabeledItem(i.item_id, i.title) for i in items),
        )
        conv = conv.spend_model_call()
        offered = frozenset(i.item_id for i in items)
        try:
            selected = self._validator.selection(self._picker.pick(request), offered)
        except (ModelUnavailable, ModelOutputRejected) as exc:
            self._model_failed(conv, request.request_id, "pick_relevant_items", exc)
            return conv.disable_ai(), frozenset()
        self._audit("validator", "model_output_accepted", conv.case_id, request_id=request.request_id,
                    port="pick_relevant_items", selected=len(selected))
        return conv, selected

    def _flag(self, conv: Conversation, meds: list[ChartItem]) -> tuple[Conversation, dict[ItemId, frozenset[Flag]]]:
        if not self._can_call(conv, "match_flags"):
            return self._off(conv), {}
        flag_ids = frozenset(f.value for f in Flag)
        request = FlagMatchRequest(
            request_id=f"{conv.case_id}:flags:{conv.budget.model_calls + 1}",
            symptom_ids=frozenset(conv.report.symptom_ids),
            items=tuple(LabeledItem(i.item_id, i.title) for i in meds),
            flag_ids=flag_ids,
        )
        conv = conv.spend_model_call()
        try:
            flags = self._validator.flags(self._flagger.match(request), frozenset(i.item_id for i in meds), flag_ids)
        except (ModelUnavailable, ModelOutputRejected) as exc:
            self._model_failed(conv, request.request_id, "match_flags", exc)
            return conv.disable_ai(), {}
        self._audit("validator", "model_output_accepted", conv.case_id, request_id=request.request_id,
                    port="match_flags", flagged_items=len(flags))
        return conv, flags

    def _ai_lookups(self, conv: Conversation, current: list[ChartItem], selected: frozenset[ItemId],
                    covered: list[DrugInfo]) -> tuple[Conversation, list[DrugInfo], int]:
        wanted = [i for i in current if i.item_id in selected and not any(d.matches(i.title) for d in covered)]
        infos: list[DrugInfo] = []
        rejected = 0
        for name in _distinct_titles(wanted):
            if not conv.budget.can_lookup():
                self._audit(ACTOR, "ai_cap_reached", conv.case_id, limit="max_lookups")
                break
            conv = conv.spend_lookup()
            found, n = self._lookup_drugs([name], conv.case_id)
            infos += found
            rejected += n
        return conv, infos, rejected

    def _can_call(self, conv: Conversation, port: str) -> bool:
        if conv.ai_disabled:
            return False
        if not conv.budget.can_call_model():
            self._audit(ACTOR, "ai_cap_reached", conv.case_id, limit="max_model_calls", port=port)
            return False
        return True

    @staticmethod
    def _off(conv: Conversation) -> Conversation:
        return conv if conv.ai_disabled else conv.disable_ai()

    def _model_failed(self, conv: Conversation, request_id: str, port: str, exc: Exception) -> None:
        if isinstance(exc, ModelOutputRejected):
            self._audit("validator", "model_output_rejected", conv.case_id, request_id=request_id,
                        port=port, reason=exc.reason)
        else:
            self._audit(ACTOR, "model_unavailable", conv.case_id, request_id=request_id, port=port, error=str(exc))


def _distinct_titles(items: list[ChartItem]) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        seen.setdefault(item.title.casefold(), item.title)
    return list(seen.values())


def _distinct_items(items: list[ChartItem]) -> list[ChartItem]:
    seen: dict[str, ChartItem] = {}
    for item in items:
        seen.setdefault(item.item_id, item)
    return list(seen.values())
