"""CompletenessPolicy: is the symptom onset and trend present?"""

from curaai.domain.symptom_report import SymptomReport
from curaai.domain.values import MissingField


class CompletenessPolicy:
    """A sick message is complete when it states when symptoms began and how they are trending."""

    REQUIRED: frozenset[MissingField] = frozenset({MissingField.ONSET, MissingField.TREND})

    @staticmethod
    def missing(report: SymptomReport) -> frozenset[MissingField]:
        missing = set()
        if report.onset is None:
            missing.add(MissingField.ONSET)
        if report.trend is None:
            missing.add(MissingField.TREND)
        return frozenset(missing)

    @classmethod
    def is_complete(cls, report: SymptomReport) -> bool:
        return not cls.missing(report)
