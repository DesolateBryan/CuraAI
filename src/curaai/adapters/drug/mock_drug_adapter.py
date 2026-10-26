"""MockDrugAdapter: DrugDbPort over the small built-in drug list from MockChart."""

from curaai.application.dto.drug import DrugQuery, DrugRecord
from curaai.application.ports.drug_db_port import DrugDbPort


class MockDrugAdapter(DrugDbPort):
    def __init__(self, records: dict[str, DrugRecord]) -> None:
        self._records = records

    def lookup(self, query: DrugQuery) -> DrugRecord | None:
        raise NotImplementedError("Ring 3 stub")
