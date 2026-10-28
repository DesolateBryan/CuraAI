"""Model adapters: the only code that calls the model, always through the gateway (ADR-001)."""

from curaai.adapters.model.bedrock_transport import BedrockConverseTransport, converse_request, parse_converse_response
from curaai.adapters.model.cost_guard import CostGuard
from curaai.adapters.model.gateway import ModelGateway, ModelPricing, VendorReply, VendorTransport
from curaai.adapters.model.gemini_transport import GeminiTransport, gemini_request, parse_gemini_response
from curaai.adapters.model.gateway_client import GatewayClient, GatewayReply, Prompt, case_id_from_request_id
from curaai.adapters.model.model_adapters import (
    GatewayExtractSymptoms, GatewayMatchFlags, GatewayPickRelevantItems, GatewaySelectFollowUp,
)
from curaai.adapters.model.redaction import redact_identifiers

__all__ = [
    "BedrockConverseTransport", "CostGuard", "GatewayClient", "GatewayExtractSymptoms", "GatewayMatchFlags",
    "GatewayPickRelevantItems", "GatewayReply", "GeminiTransport", "gemini_request", "parse_gemini_response", "GatewaySelectFollowUp", "ModelGateway", "ModelPricing",
    "Prompt", "VendorReply", "VendorTransport", "case_id_from_request_id", "converse_request",
    "parse_converse_response", "redact_identifiers",
]
