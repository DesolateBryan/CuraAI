"""The four narrow model ports (M1 sketch, ADR-013).

Each one can be versioned, tested and swapped on its own (ISP). Implementations
live in adapters/model and talk to the model ONLY through the gateway.
On failure an implementation raises application.errors.ModelUnavailable.
"""

from abc import ABC, abstractmethod

from curaai.application.dto.model import (
    ExtractionRequest,
    FlagMatch,
    FlagMatchRequest,
    FollowUpChoice,
    FollowUpRequest,
    ItemSelection,
    SelectionRequest,
    SymptomExtraction,
)


class ExtractSymptomsPort(ABC):
    @abstractmethod
    def extract(self, request: ExtractionRequest) -> SymptomExtraction:
        """Read the patient's message and return catalog symptom ids, onset and trend."""


class SelectFollowUpPort(ABC):
    @abstractmethod
    def select(self, request: FollowUpRequest) -> FollowUpChoice:
        """Pick one question id from the candidates the core supplied."""


class PickRelevantItemsPort(ABC):
    @abstractmethod
    def pick(self, request: SelectionRequest) -> ItemSelection:
        """Return the ids of the labeled items most relevant to the symptoms."""


class MatchFlagsPort(ABC):
    @abstractmethod
    def match(self, request: FlagMatchRequest) -> tuple[FlagMatch, ...]:
        """Attach flags from the supplied set to the supplied item ids."""
