"""The four model adapters (M1 sketch). Each one: build_prompt -> GatewayClient.complete -> parse.

They are the only classes that talk to the model, and only through GatewayClient.
They hold no logic of their own: prompts and parsing are pure functions in
prompts.py, and every answer is validated by the core before use.
"""

from curaai.adapters.model.gateway_client import GatewayClient
from curaai.adapters.model.prompts import (
    build_extraction_prompt, build_flags_prompt, build_follow_up_prompt, build_pick_prompt,
    parse_extraction_response, parse_flags_response, parse_follow_up_response, parse_pick_response,
)
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
        return parse_extraction_response(self._client.complete(build_extraction_prompt(request)).text)


class GatewaySelectFollowUp(SelectFollowUpPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def select(self, request: FollowUpRequest) -> FollowUpChoice:
        return parse_follow_up_response(self._client.complete(build_follow_up_prompt(request)).text)


class GatewayPickRelevantItems(PickRelevantItemsPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def pick(self, request: SelectionRequest) -> ItemSelection:
        return parse_pick_response(self._client.complete(build_pick_prompt(request)).text)


class GatewayMatchFlags(MatchFlagsPort):
    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def match(self, request: FlagMatchRequest) -> tuple[FlagMatch, ...]:
        return parse_flags_response(self._client.complete(build_flags_prompt(request)).text)
