"""The four model adapters. Each: build_prompt -> GatewayClient.complete -> parse_response."""

from curaai.adapters.model.gateway_client import GatewayClient
from curaai.application.dto.model import (
    ExtractionRequest, FlagMatch, FlagMatchRequest, FollowUpChoice, FollowUpRequest,
    ItemSelection, SelectionRequest, SymptomExtraction,
)
from curaai.application.ports.model_ports import (
    ExtractSymptomsPort, MatchFlagsPort, PickRelevantItemsPort, SelectFollowUpPort,
)


class GatewayExtractSymptoms(ExtractSymptomsPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def extract(self, request: ExtractionRequest) -> SymptomExtraction:
        raise NotImplementedError("Ring 3 stub")


class GatewaySelectFollowUp(SelectFollowUpPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def select(self, request: FollowUpRequest) -> FollowUpChoice:
        raise NotImplementedError("Ring 3 stub")


class GatewayPickRelevantItems(PickRelevantItemsPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def pick(self, request: SelectionRequest) -> ItemSelection:
        raise NotImplementedError("Ring 3 stub")


class GatewayMatchFlags(MatchFlagsPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def match(self, request: FlagMatchRequest) -> tuple[FlagMatch, ...]:
        raise NotImplementedError("Ring 3 stub")
