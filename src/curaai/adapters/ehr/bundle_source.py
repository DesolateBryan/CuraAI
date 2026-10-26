"""Where MockEpicAdapter gets FHIR bundles from.

ADR-005: the MockChart page posts each patient's FHIR bundle to the backend.
The web router (later pass) receives an InMemoryBundleSource by injection and
calls put(); the adapter only reads. Bundles are kept in memory, never on disk.
"""

from collections.abc import Mapping
from typing import Protocol


class BundleSource(Protocol):
    def bundle_for(self, patient_id: str) -> Mapping | None: ...


class InMemoryBundleSource:
    def __init__(self, bundles: Mapping[str, Mapping] | None = None) -> None:
        self._bundles: dict[str, Mapping] = dict(bundles or {})

    def put(self, patient_id: str, bundle: Mapping) -> None:
        self._bundles[patient_id] = bundle

    def bundle_for(self, patient_id: str) -> Mapping | None:
        return self._bundles.get(patient_id)
