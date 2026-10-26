"""SymptomCatalog: the fixed list of symptoms the model must choose from.

The model never invents a symptom. It returns ids, and the core rejects any id
that is not in this catalog (ADR-002, ADR-013).
"""

from dataclasses import dataclass

from curaai.domain.errors import UnknownCatalogEntry
from curaai.domain.values import SymptomId, require_text


@dataclass(frozen=True)
class Symptom:
    id: SymptomId
    label: str

    def __post_init__(self) -> None:
        require_text(self.id, "Symptom.id")
        require_text(self.label, "Symptom.label")


@dataclass(frozen=True)
class SymptomCatalog:
    symptoms: tuple[Symptom, ...]

    def __post_init__(self) -> None:
        if not self.symptoms:
            raise ValueError("SymptomCatalog cannot be empty")
        ids = [s.id for s in self.symptoms]
        if len(ids) != len(set(ids)):
            raise ValueError("SymptomCatalog ids must be unique")

    def ids(self) -> frozenset[SymptomId]:
        return frozenset(s.id for s in self.symptoms)

    def contains(self, symptom_id: str) -> bool:
        return symptom_id in self.ids()

    def get(self, symptom_id: str) -> Symptom:
        for symptom in self.symptoms:
            if symptom.id == symptom_id:
                return symptom
        raise UnknownCatalogEntry(f"symptom not in catalog: {symptom_id!r}")


# DRAFT, pending clinician sign-off (ADR-009: catalog changes need a clinician).
# Seeded from the six MockChart test messages plus common sick-message complaints.
def _s(id_: str, label: str) -> Symptom:
    return Symptom(SymptomId(id_), label)


DEFAULT_SYMPTOM_CATALOG = SymptomCatalog((
    _s("cough", "Cough"),
    _s("fever", "Fever"),
    _s("sore_throat", "Sore throat"),
    _s("hoarseness", "Hoarse voice"),
    _s("shortness_of_breath", "Shortness of breath"),
    _s("wheezing", "Wheezing"),
    _s("chest_pain", "Chest pain or pressure"),
    _s("palpitations", "Racing or pounding heartbeat"),
    _s("tremor", "Shakiness or tremor"),
    _s("dizziness", "Dizziness"),
    _s("lightheadedness", "Lightheadedness"),
    _s("nausea", "Nausea"),
    _s("vomiting", "Vomiting"),
    _s("diarrhea", "Diarrhea"),
    _s("abdominal_pain", "Abdominal pain"),
    _s("headache", "Headache"),
    _s("vision_change", "Vision change"),
    _s("weakness", "Weakness"),
    _s("fatigue", "Fatigue"),
    _s("rash", "Rash"),
    _s("sweating", "Sweating"),
    _s("insomnia", "Trouble sleeping"),
))
