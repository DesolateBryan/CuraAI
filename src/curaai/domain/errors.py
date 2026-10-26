"""Domain errors. Raised when an entity would be built in a state the rules forbid."""


class DomainError(Exception):
    """Base class for every rule violation raised by Ring 1."""


class MissingSourceReference(DomainError):
    """A chart item, drug record or timeline entry has no source_ref (ADR-004, ADR-012)."""


class InvalidSymptomReport(DomainError):
    """A symptom report is internally inconsistent (e.g. approximate onset with no onset)."""


class UnknownCatalogEntry(DomainError):
    """An id was looked up that the fixed catalog does not contain."""


class InvalidConversationTransition(DomainError):
    """A conversation was asked to move to a state the workflow does not allow."""


class BudgetExceeded(DomainError):
    """A per-case cap from ADR-011 would be exceeded."""

    def __init__(self, limit_name: str) -> None:
        super().__init__(f"per-case limit reached: {limit_name}")
        self.limit_name = limit_name
