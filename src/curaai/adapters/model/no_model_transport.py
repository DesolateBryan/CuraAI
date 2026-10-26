"""NoModelTransport: a VendorTransport with no model behind it (CURAAI_MODEL_BACKEND=none).

Every call fails, so the gateway raises ModelUnavailable and Ring 2 runs the
ADR-011 fallback: AI off for the case, fixed chart pull anchored to the message
date, doctor notified. Lets the whole system run with no cloud account.
"""

from curaai.adapters.model.gateway import VendorReply


class ModelBackendDisabled(RuntimeError):
    pass


class NoModelTransport:
    def send(self, system: str, user: str, max_output_tokens: int) -> VendorReply:
        raise ModelBackendDisabled("no model backend configured (CURAAI_MODEL_BACKEND=none)")
