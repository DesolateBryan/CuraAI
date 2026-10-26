# =============================================================================
# RING 1: ENTITIES (domain core)
#
# DEPENDENCY RULE: this package depends on NOTHING outside itself.
#   * Allowed imports: the Python standard library and curaai.domain.*
#   * Forbidden: curaai.application, curaai.adapters, curaai.app, any framework
#     (FastAPI, Pydantic), any SDK, any I/O (network, disk, database, clock).
#
# Everything here is immutable (frozen dataclasses, enums) and side-effect free.
# The current time is always passed in as an argument, never read from a clock.
# These are the rules auditors check (M1 sketch): fixed catalog, completeness,
# 3-week window, 24-hour timeout, approximate-onset marker, verbatim records.
# =============================================================================
"""CuraAI domain core (Ring 1)."""
