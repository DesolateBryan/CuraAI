"""OpenFdaAdapter: DrugDbPort over api.fda.gov/drug/label.json (humble: one HTTP GET).

The openFDA JSON -> DrugRecord mapping lives in a pure function next to it.
Only the drug name is sent, never patient data.
"""

from curaai.application.dto.drug import DrugQuery, DrugRecord
from curaai.application.ports.drug_db_port import DrugDbPort


class OpenFdaAdapter(DrugDbPort):
    def __init__(self, http_client: object, base_url: str = "https://api.fda.gov/drug/label.json") -> None:
        self._http = http_client
        self._base_url = base_url

    def lookup(self, query: DrugQuery) -> DrugRecord | None:
        raise NotImplementedError("Ring 3 stub")
