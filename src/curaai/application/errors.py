"""Errors that cross ports. Adapters raise these; use cases catch them."""


class ApplicationError(Exception):
    """Base class for Ring 2 errors."""


class ModelUnavailable(ApplicationError):
    """A model port could not produce an answer (timeout, vendor error, cost guard trip)."""


class ModelOutputRejected(ApplicationError):
    """The model answered, but the core validator refused the answer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ExternalSourceUnavailable(ApplicationError):
    """The EHR or drug database could not be read."""


class RejectedInboundMessage(ApplicationError):
    """An inbound message failed the intake checks (e.g. it did not come from the patient)."""


class UnknownCase(ApplicationError):
    """No review packet (and so no HITL gate) exists for this case id."""
