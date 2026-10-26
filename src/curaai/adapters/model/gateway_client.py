"""GatewayClient: the one interface model adapters use to reach the model (ADR-001).

Today the gateway runs in-process (ModelGateway). When it becomes a separate
service (deferred, ADR-017), an HTTP client implementing this same Protocol
replaces it in app/main.py and nothing else changes. CostGuard implements it
too, so it can wrap whichever client is in use.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Prompt:
    request_id: str        # "<case_id>:<step>:<n>", set by Ring 2
    port: str              # "extract_symptoms" | "select_follow_up" | "pick_relevant_items" | "match_flags"
    version: str           # prompt version, logged with every call (ADR-001, ADR-007)
    system: str            # fixed instructions, never patient text
    user: str              # the request data as JSON; may contain the patient's words
    max_output_tokens: int = 300

    @property
    def case_id(self) -> str:
        return case_id_from_request_id(self.request_id)


@dataclass(frozen=True)
class GatewayReply:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    model: str
    redactions: int


class GatewayClient(Protocol):
    def complete(self, prompt: Prompt) -> GatewayReply: ...


def case_id_from_request_id(request_id: str) -> str:
    """Ring 2 builds request ids as "<case_id>:<step>:<n>"; case ids never contain ':'."""
    parts = request_id.rsplit(":", 2)
    return parts[0] if len(parts) == 3 else request_id
