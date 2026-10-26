"""ModelOutputValidator: accept a model answer only if it uses what the core offered.

Rules (ADR-002, ADR-010, ADR-013):
  * every symptom id must be in the SymptomCatalog
  * every question id must be one of the eligible candidates the core supplied
  * every item id / flag id must be one the core supplied for this request
  * trend must be a Trend value; onset must be a real date, not after the
    message date and not older than MAX_ONSET_AGE_DAYS
  * any violation rejects the WHOLE answer; nothing is partially trusted

Prompt-injection text that tricks the model into returning something else ends
up here as an unknown id or a malformed value, and is rejected.
"""

from datetime import date, datetime, timedelta

from curaai.application.dto.model import FlagMatch, FollowUpChoice, ItemSelection, SymptomExtraction
from curaai.application.errors import ModelOutputRejected
from curaai.domain.symptom_catalog import SymptomCatalog
from curaai.domain.symptom_report import SymptomReport
from curaai.domain.values import Flag, ItemId, QuestionId, SymptomId, Trend

MAX_ONSET_AGE_DAYS = 365
_TREND_VALUES = {t.value: t for t in Trend}
_FLAG_VALUES = {f.value: f for f in Flag}


class ModelOutputValidator:
    def __init__(self, symptom_catalog: SymptomCatalog, max_onset_age_days: int = MAX_ONSET_AGE_DAYS) -> None:
        self._catalog = symptom_catalog
        self._max_age = timedelta(days=max_onset_age_days)

    # ---- ExtractSymptomsPort ------------------------------------------------
    def extraction(self, raw: SymptomExtraction, reference_date: date) -> SymptomReport:
        if not isinstance(raw, SymptomExtraction):
            raise ModelOutputRejected("extraction: wrong response type")
        ids = self._str_tuple(raw.symptom_ids, "extraction.symptom_ids")
        unknown = [i for i in ids if not self._catalog.contains(i)]
        if unknown:
            raise ModelOutputRejected(f"extraction: {len(unknown)} symptom id(s) not in catalog")

        trend = None
        if raw.trend is not None:
            if raw.trend not in _TREND_VALUES:
                raise ModelOutputRejected("extraction: trend is not an allowed value")
            trend = _TREND_VALUES[raw.trend]

        onset = raw.onset
        if onset is not None:
            if isinstance(onset, datetime) or not isinstance(onset, date):
                raise ModelOutputRejected("extraction: onset must be a calendar date")
            if onset > reference_date:
                raise ModelOutputRejected("extraction: onset is after the message date")
            if onset < reference_date - self._max_age:
                raise ModelOutputRejected("extraction: onset is implausibly old")

        if not isinstance(raw.onset_is_approx, bool):
            raise ModelOutputRejected("extraction: onset_is_approx must be a boolean")
        if raw.onset_is_approx and onset is None:
            raise ModelOutputRejected("extraction: approximate onset with no onset date")

        return SymptomReport(
            symptom_ids=frozenset(SymptomId(i) for i in ids),
            onset=onset,
            onset_is_approx=raw.onset_is_approx,
            trend=trend,
        )

    # ---- SelectFollowUpPort -------------------------------------------------
    def follow_up(self, raw: FollowUpChoice, eligible_ids: frozenset[str]) -> QuestionId:
        if not isinstance(raw, FollowUpChoice) or not isinstance(raw.question_id, str):
            raise ModelOutputRejected("follow_up: wrong response type")
        if raw.question_id not in eligible_ids:
            raise ModelOutputRejected("follow_up: question id was not offered")
        return QuestionId(raw.question_id)

    # ---- PickRelevantItemsPort ----------------------------------------------
    def selection(self, raw: ItemSelection, offered_ids: frozenset[str]) -> frozenset[ItemId]:
        if not isinstance(raw, ItemSelection):
            raise ModelOutputRejected("selection: wrong response type")
        ids = self._str_tuple(raw.item_ids, "selection.item_ids")
        if any(i not in offered_ids for i in ids):
            raise ModelOutputRejected("selection: item id was not offered")
        return frozenset(ItemId(i) for i in ids)

    # ---- MatchFlagsPort -----------------------------------------------------
    def flags(self, raw: tuple[FlagMatch, ...], offered_item_ids: frozenset[str],
              offered_flag_ids: frozenset[str]) -> dict[ItemId, frozenset[Flag]]:
        if not isinstance(raw, tuple) or not all(isinstance(m, FlagMatch) for m in raw):
            raise ModelOutputRejected("flags: wrong response type")
        result: dict[ItemId, set[Flag]] = {}
        for match in raw:
            if match.item_id not in offered_item_ids:
                raise ModelOutputRejected("flags: item id was not offered")
            if match.flag_id not in offered_flag_ids or match.flag_id not in _FLAG_VALUES:
                raise ModelOutputRejected("flags: flag id was not offered")
            result.setdefault(ItemId(match.item_id), set()).add(_FLAG_VALUES[match.flag_id])
        return {k: frozenset(v) for k, v in result.items()}

    @staticmethod
    def _str_tuple(value: object, name: str) -> tuple[str, ...]:
        if not isinstance(value, tuple) or not all(isinstance(v, str) for v in value):
            raise ModelOutputRejected(f"{name} must be a tuple of strings")
        return value
