# =============================================================================
# RING 3: INTERFACE ADAPTERS
#
# DEPENDENCY RULE: may import curaai.application and curaai.domain (inward).
#   * Adapters never import each other (enforced by .importlinter).
#   * Adapters never construct their collaborators; Main (Ring 4) injects them.
#   * Only adapters/model/* may touch the model gateway; vendor SDK objects
#     never cross into Ring 2.
#
# Every adapter is tested: pure mappers with fixed data, humble I/O classes with fakes,
# and contract tests where a test fake and a real adapter must agree.
# =============================================================================
"""CuraAI interface adapters (Ring 3)."""
