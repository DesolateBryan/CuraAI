"""MockDrugAdapter: DrugDbPort over MockChart's built-in drug list (ADR-005).

The list (mockchart_drugs.json, next to this file) is captured from the page's
DB and IX tables, so the backend sees the same drug facts the page shows.
Name matching copies the page: a drug matches when its key appears in the
medication name ("Ferrous sulfate" -> "ferrous"). Read-only; no write methods.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from curaai.application.dto.drug import DrugQuery, DrugRecord
from curaai.application.ports.drug_db_port import DrugDbPort

DATA_FILE = Path(__file__).with_name("mockchart_drugs.json")


def mockchart_drug_records(data: Mapping) -> dict[str, DrugRecord]:
    """Pure: the page's tables -> one DrugRecord per drug key. Text is copied as-is."""
    lines: dict[str, list[str]] = {}
    for ix in data.get("interactions", ()):
        for this, other in ((ix["a"], ix["b"]), (ix["b"], ix["a"])):
            lines.setdefault(this, []).append(f"With {other} ({ix['severity']}): {ix['note']}")
    return {
        key: DrugRecord(
            drug_name=key,
            source_ref=f"mockchart:drug/{key}",
            class_text=entry.get("class"),
            adverse_text=entry.get("adverse"),
            interactions_text="\n".join(lines[key]) if key in lines else None,
        )
        for key, entry in data.get("drugs", {}).items()
    }


def load_mockchart_drugs(path: Path = DATA_FILE) -> dict[str, DrugRecord]:
    return mockchart_drug_records(json.loads(path.read_text(encoding="utf-8")))


class MockDrugAdapter(DrugDbPort):
    def __init__(self, records: Mapping[str, DrugRecord]) -> None:
        # longest key first, so a specific name wins over a shorter one it contains
        self._records = dict(sorted(records.items(), key=lambda kv: -len(kv[0])))

    def lookup(self, query: DrugQuery) -> DrugRecord | None:
        name = query.drug_name.casefold()
        return next((record for key, record in self._records.items() if key in name), None)
