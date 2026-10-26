"""GatewayClient (humble): send one payload to the internal model gateway, return the raw string.

No branching, no parsing. The vendor SDK client is constructed in app/main.py and injected.
"""


class GatewayClient:
    def __init__(self, sdk_client: object, endpoint: str) -> None:
        self._sdk = sdk_client
        self._endpoint = endpoint

    def complete(self, prompt_version: str, payload: str) -> str:
        raise NotImplementedError("Ring 3 stub: call the gateway through the injected SDK client")
