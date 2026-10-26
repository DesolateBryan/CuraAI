"""redact_identifiers: pure PII scrubbing applied by the gateway before text leaves (ADR-001).

What it removes from patient text: email addresses, phone numbers, SSN-shaped
numbers, URLs, and long digit runs (MRNs, account numbers).
What it deliberately KEEPS: dates and short numbers, because onset dates ("Oct 9",
"10/09") and doses ("40 mg") are exactly what the model has to read.
Names are not removed: reliable name detection needs an NER model, which is a
known gap to close before any real PHI is processed (ADR-006).
"""

import re

_PATTERNS = (
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("URL", re.compile(r"\bhttps?://\S+", re.IGNORECASE)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")),
    # 6+ digit runs, but not parts of dates (10/09/2026, 2026-10-09) or decimals (1234567.5)
    ("ID", re.compile(r"(?<![\d/-])(?<!\d\.)\d{6,}(?![\d/-])(?!\.\d)")),
)


def redact_identifiers(text: str) -> tuple[str, int]:
    count = 0
    for label, pattern in _PATTERNS:
        text, n = pattern.subn(f"[{label}]", text)
        count += n
    return text, count
