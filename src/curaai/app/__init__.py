# =============================================================================
# RING 4: FRAMEWORKS & DRIVERS / COMPOSITION ROOT
#
# DEPENDENCY RULE: main.py is the ONLY module allowed to import every ring and
# the vendor SDK. Nothing imports curaai.app. All wiring happens here (ADR-015).
# =============================================================================
"""CuraAI composition root (Ring 4)."""
