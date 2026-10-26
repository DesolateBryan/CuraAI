"""BedrockConverseTransport: VendorTransport over AWS Bedrock's Converse API (ADR-001 option 3).

The boto3 "bedrock-runtime" client is constructed ONLY in app/main.py and injected
here (ADR-015). This module never imports boto3, so tests run without it.
Temperature 0 keeps answers as repeatable as the vendor allows.

Switching vendors (e.g. Azure OpenAI) means writing another transport with the
same send() method and changing one line in app/main.py. No use case changes.
"""

from collections.abc import Mapping

from curaai.adapters.model.gateway import VendorReply


def converse_request(model_id: str, system: str, user: str, max_output_tokens: int,
                     temperature: float = 0.0) -> dict:
    """Pure: the keyword arguments for client.converse(...)."""
    return {
        "modelId": model_id,
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_output_tokens, "temperature": temperature},
    }


def parse_converse_response(response: Mapping, model_id: str) -> VendorReply:
    """Pure: Bedrock Converse response -> VendorReply."""
    content = (((response.get("output") or {}).get("message") or {}).get("content")) or []
    text = "".join(block.get("text", "") for block in content if isinstance(block, Mapping))
    usage = response.get("usage") or {}
    return VendorReply(text=text, input_tokens=int(usage.get("inputTokens", 0)),
                       output_tokens=int(usage.get("outputTokens", 0)), model=model_id)


class BedrockConverseTransport:
    def __init__(self, bedrock_runtime_client: object, model_id: str, temperature: float = 0.0) -> None:
        self._client = bedrock_runtime_client
        self._model_id = model_id
        self._temperature = temperature

    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        response = self._client.converse(
            **converse_request(self._model_id, system, user, max_output_tokens, self._temperature))
        return parse_converse_response(response, self._model_id)
