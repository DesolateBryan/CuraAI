"""fhir_to_chart_items against FHIR captured from the real MockChart page, plus edge cases."""

import copy
from datetime import date

import pytest

from curaai.adapters.ehr import fhir_to_chart_items
from tests.fixtures.mockchart import PATIENTS, chart_records, fhir_bundles

BUNDLES = fhir_bundles()


def by_id(patient_id):
    return {r.item_id: r for r in fhir_to_chart_items(BUNDLES[patient_id], patient_id).records}


def test_maps_meds_labs_and_encounters_and_leaves_demographics_and_messages_behind():
    records = fhir_to_chart_items(BUNDLES["p1"], "p1").records
    assert sorted(r.kind for r in records) == ["encounter"] * 3 + ["lab"] * 4 + ["medication"] * 4
    assert not [r for r in records if "Ellison" in r.detail or "4821307" in r.detail]   # no Patient data
    assert not [r for r in records if "cough" in r.detail]                              # no Communication text


def test_text_is_verbatim_and_every_record_points_at_its_fhir_resource():
    r = by_id("p1")
    assert r["p1-en1"].detail == ("BP 148/92, home log elevated. Increase lisinopril to 40 mg daily. "
                                  "Recheck BMP in 2 weeks.")
    assert r["p1-mr1"].detail == "40 mg PO daily · Increased from 20 mg"
    assert r["p1-ob0"].detail == "7.4 % (ref 4.0–5.6)" and r["p1-ob0"].flag == "H"
    assert r["p1-mr1"].source_ref == "MedicationRequest/p1-mr1"
    assert r["p1-ob0"].source_ref == "Observation/p1-ob0"
    assert r["p1-en0"].source_ref == "Encounter/p1-en0"
    assert r["p1-en0"].author == "Dr. L. Okafor"


def test_stopped_status_is_carried_even_though_the_mock_omits_end_dates():
    r = by_id("p1")
    assert r["p1-mr0"].stopped and r["p1-mr0"].end_date is None      # lisinopril 20 mg
    assert not r["p1-mr1"].stopped


def test_matches_the_hand_written_fixture_apart_from_end_dates():
    """Parity check: the captured FHIR and tests/fixtures/mockchart.py describe the same chart."""
    fields = ("item_id", "kind", "date", "title", "detail", "source_ref", "author", "flag", "stopped")
    for pid in PATIENTS:
        mapped = {tuple(getattr(r, f) for f in fields) for r in fhir_to_chart_items(BUNDLES[pid], pid).records}
        expected = {tuple(getattr(r, f) for f in fields) for r in chart_records(pid)}
        assert mapped == expected, pid


def test_another_patients_resources_never_cross():
    bundle = copy.deepcopy(BUNDLES["p1"])
    bundle["entry"] += BUNDLES["p2"]["entry"]
    mapping = fhir_to_chart_items(bundle, "p1")
    assert {r.item_id[:2] for r in mapping.records} == {"p1"}
    assert mapping.skipped_other_patient == 10


def test_resource_without_an_id_gets_an_empty_source_so_the_core_rejects_it():
    bundle = copy.deepcopy(BUNDLES["p1"])
    del next(e for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation")["resource"]["id"]
    assert [r.source_ref for r in fhir_to_chart_items(bundle, "p1").records if r.kind == "lab"].count("") == 1


def test_entered_in_error_is_excluded_and_unreadable_resources_are_counted():
    bundle = copy.deepcopy(BUNDLES["p1"])
    resources = [e["resource"] for e in bundle["entry"]]
    next(r for r in resources if r["resourceType"] == "Encounter")["status"] = "entered-in-error"
    next(r for r in resources if r["resourceType"] == "Observation")["effectiveDateTime"] = "not a date"
    mapping = fhir_to_chart_items(bundle, "p1")
    assert (mapping.skipped_entered_in_error, mapping.skipped_unreadable) == (1, 1)
    assert len(mapping.records) == 9


def test_standard_fhir_shapes_beyond_the_mock_are_understood():
    bundle = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "MedicationRequest", "id": "m1", "status": "active",
                      "subject": {"reference": "Patient/x"},
                      "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                                                "code": "314076", "display": "lisinopril 10 MG Oral Tablet"}]},
                      "authoredOn": "2026-09-01T10:30:00-04:00",
                      "dosageInstruction": [{"text": "10 mg daily",
                                             "timing": {"repeat": {"boundsPeriod": {"end": "2026-10-01"}}}}]}},
        {"resource": {"resourceType": "Observation", "id": "o1", "status": "final",
                      "subject": {"reference": "Patient/x"}, "code": {"text": "Potassium"},
                      "effectiveDateTime": "2026-09-02T08:00:00Z",
                      "valueQuantity": {"value": 5.6, "unit": "mmol/L"},
                      "interpretation": [{"coding": [{"code": "H"}]}]}},
    ]}
    med, lab = fhir_to_chart_items(bundle, "x").records
    assert (med.title, med.code, med.date, med.end_date) == ("lisinopril 10 MG Oral Tablet", "314076",
                                                             date(2026, 9, 1), date(2026, 10, 1))
    assert (lab.detail, lab.flag) == ("5.6 mmol/L", "H")


def test_rejects_something_that_is_not_a_bundle():
    with pytest.raises(ValueError):
        fhir_to_chart_items({"resourceType": "Patient"}, "p1")
