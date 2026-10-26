"""Composition root (ADR-015). Stub: the wiring order is fixed here, bodies come in Ring 3/4 pass.

build() will:
    1. read Config once from the environment (adapter choice, endpoints, keys; no secrets in repo)
    2. construct the vendor SDK client (boto3 bedrock-runtime) -> BedrockConverseTransport
       -> ModelGateway (redaction, pricing, audit) -> CostGuard (adapters/model)
    3. construct the four Gateway* model adapters, each wrapped in its Logged* decorator
    4. construct MockEpicAdapter (one config `if` selects EpicEhrAdapter later),
       OpenFdaAdapter or MockDrugAdapter, JsonlAuditLog, InMemoryConversationStore,
       SystemClock, ReviewPresenter, MockEpicMessagingAdapter
    5. construct ModelOutputValidator and the use cases, injecting ports by constructor
    6. construct PipelineTrigger and the FastAPI app, then hand off to Uvicorn

tests/compose.py is the second composition root; it wires fakes into the same use cases.
"""


def build() -> object:
    raise NotImplementedError("Ring 4 stub")


if __name__ == "__main__":
    build()
