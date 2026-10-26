"""Pure functions: build_prompt and parse_response, one pair per model port (ADR-014).

Tested with canned raw strings (valid, malformed, prompt-injection) and no SDK.
"""

from curaai.application.dto.model import ExtractionRequest, SymptomExtraction

PROMPT_VERSION = "extract-v0"


def build_extraction_prompt(request: ExtractionRequest) -> str:
    raise NotImplementedError("Ring 3 stub")


def parse_extraction_response(raw: str) -> SymptomExtraction:
    """Parse JSON into the DTO. Malformed text raises ModelUnavailable; the core validator does the rest."""
    raise NotImplementedError("Ring 3 stub")
