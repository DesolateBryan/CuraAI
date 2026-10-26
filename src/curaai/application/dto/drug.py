"""Drug database boundary (read-only). openFDA JSON and license keys stay behind the adapter."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DrugQuery:
    drug_name: str
    code: str | None = None


@dataclass(frozen=True)
class DrugRecord:
    drug_name: str
    source_ref: str
    class_text: str | None = None
    adverse_text: str | None = None
    interactions_text: str | None = None
    boxed_warning_text: str | None = None
    contraindications_text: str | None = None
