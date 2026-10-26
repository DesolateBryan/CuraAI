# =============================================================================
# RING 2: USE CASES (application layer)
#
# DEPENDENCY RULE: this package may import ONLY curaai.domain and itself.
#   * Allowed: Python standard library, curaai.domain.*, curaai.application.*
#   * Forbidden: curaai.adapters, curaai.app, FastAPI, Pydantic, any vendor SDK,
#     any concrete EHR / drug database / model client.
#
# This ring OWNS the ports (abstract interfaces in ports/) and the DTOs that cross
# them (dto/). Outer rings implement the ports; this ring never constructs them.
# Use cases sequence the workflow and add no business rules of their own; the
# rules live in Ring 1. The only exception is model-output validation, which
# checks what the model returned against the sets the core supplied.
# =============================================================================
"""CuraAI application layer (Ring 2)."""
