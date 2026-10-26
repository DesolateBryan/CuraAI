"""Drug database adapters: read-only, openFDA and the MockChart list (ADR-005)."""

from curaai.adapters.drug.http_client import UrllibHttpClient
from curaai.adapters.drug.mock_drug_adapter import MockDrugAdapter, load_mockchart_drugs, mockchart_drug_records
from curaai.adapters.drug.openfda_adapter import (
    HttpClient, HttpNotFound, OpenFdaAdapter, build_label_url, openfda_to_drug_record,
)

__all__ = [
    "HttpClient", "HttpNotFound", "MockDrugAdapter", "OpenFdaAdapter", "UrllibHttpClient",
    "build_label_url", "load_mockchart_drugs", "mockchart_drug_records", "openfda_to_drug_record",
]
