"""FastAPI routers (humble). Imported only by app/main.py.

POST /api/messages : body = message + FHIR bundle from the MockChart page.
    The raw fhir_bundle never passes this adapter (M2 crossing table); it is
    handed to the MockEpic adapter's bundle source, and only an InboundMessage
    reaches PipelineTrigger.on_patient_message.
"""


def build_router(trigger: object) -> object:
    raise NotImplementedError("Ring 3 stub: create an APIRouter that calls the injected trigger")
