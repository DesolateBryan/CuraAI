# =============================================================================
# RING 3: INTERFACE ADAPTERS
#
# DEPENDENCY RULE: may import curaai.application and curaai.domain (inward).
#   * Adapters never import each other (enforced by .importlinter).
#   * Adapters never construct their collaborators; Main (Ring 4) injects them.
#   * Only adapters/model/* may touch the model gateway; vendor SDK objects
#     never cross into Ring 2.
#
# STATUS: stubs only in this pass. Each class implements its port's signature
# and raises NotImplementedError. Rings 1-2 are fully tested through fakes.
# =============================================================================
"""CuraAI interface adapters (Ring 3)."""
