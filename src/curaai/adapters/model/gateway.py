"""ModelGateway: the internal model gateway from ADR-001, running in-process for the prototype.

Responsibilities, all in this one place so the rest of the system never sees a vendor:
  * PII redaction of everything sent (redact_identifiers), count logged
  * prompt versioning: every call is logged with Prompt.version
  * pricing: token usage -> cost_usd with injected ModelPricing
  * audit (ADR-007): request id, port, prompt version, model, tokens, cost,
    redactions, latency, and the raw model output, for replaying a case; on a
    failure, the vendor's reason (scrubbed of identifiers) so the fallback is explainable
  * vendor swap: the VendorTransport is injected; Bedrock today (bedrock_transport.py)

The gateway as a separate service is deferred (ADR-017). When that happens, an
HTTP GatewayClient replaces this class in app/main.py.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from curaai.adapters.model.gateway_client import GatewayReply, Prompt
from curaai.adapters.model.redaction import redact_identifiers
from curaai.application.dto.audit import AuditEvent
from curaai.application.errors import ModelUnavailable
from curaai.application.ports.audit_log_port import AuditLogPort
from curaai.application.ports.clock_port import ClockPort

MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPricing:
    """USD per million tokens. Placeholder values until the vendor quote (M1 ROI sketch)."""

    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (Decimal(input_tokens) * self.input_usd_per_mtok
                + Decimal(output_tokens) * self.output_usd_per_mtok) / MTOK


@dataclass(frozen=True)
class VendorReply:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class VendorTransport(Protocol):
    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply: ...


class ModelGateway:
    def __init__(self, transport: VendorTransport, pricing: ModelPricing,
                 audit_log: AuditLogPort, clock: ClockPort) -> None:
        self._transport = transport
        self._pricing = pricing
        self._audit = audit_log
        self._clock = clock

    def complete(self, prompt: Prompt) -> GatewayReply:
        user, redactions = redact_identifiers(prompt.user)
        system, more = redact_identifiers(prompt.system)
        redactions += more
        started = time.monotonic()
        try:
            reply = self._transport.send(system, user, prompt.max_output_tokens)
        except Exception as exc:                       # vendor SDK errors never cross this line
            reason, _ = redact_identifiers(str(exc))
            self._log(prompt, "model_gateway_error", latency_ms=_ms(started), redactions=redactions,
                      error=type(exc).__name__, message=reason[:300])
            raise ModelUnavailable(f"model gateway: {type(exc).__name__}") from exc

        cost = self._pricing.cost(reply.input_tokens, reply.output_tokens)
        self._log(prompt, "model_gateway_call", latency_ms=_ms(started), redactions=redactions,
                  model=reply.model, input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                  cost_usd=float(cost), raw_output=reply.text)
        return GatewayReply(reply.text, reply.input_tokens, reply.output_tokens, cost, reply.model, redactions)

    def _log(self, prompt: Prompt, action: str, **detail) -> None:
        self._audit.record(AuditEvent(
            at=self._clock.now(), actor="model_gateway", action=action, subject_id=prompt.case_id,
            detail={"request_id": prompt.request_id, "port": prompt.port, "prompt_version": prompt.version, **detail},
        ))


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
