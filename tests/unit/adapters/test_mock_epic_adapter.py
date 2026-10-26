"""MockEpicAdapter as an EhrPort, and the full pipeline running on real MockChart FHIR."""

from datetime import date

import pytest

from curaai.adapters.ehr import InMemoryBundleSource, MockEpicAdapter
from curaai.application.dto.ehr import ActiveMedicationQuery, ChartQuery
from curaai.application.dto.model import SymptomExtraction
from curaai.application.errors import ExternalSourceUnavailable
from curaai.application.ports.ehr_port import EhrPort
from curaai.application.use_cases import PipelineOutcome
from tests.compose import build
from tests.fakes import FakeExtractSymptoms, FakePickRelevantItems
from tests.fixtures.mockchart import fhir_bundles

KEY = "mock-curaai-key-0000"


def adapter(**bundles):
    return MockEpicAdapter(InMemoryBundleSource(bundles or fhir_bundles()), api_key=KEY)


def test_is_an_ehr_port_and_hides_its_key():
    a = adapter()
    assert isinstance(a, EhrPort)
    assert KEY not in repr(a)
    with pytest.raises(ValueError):
        MockEpicAdapter(InMemoryBundleSource(), api_key="")


def test_window_query_returns_only_items_dated_inside_it():
    items = adapter().items_between(ChartQuery("p1", date(2026, 9, 18), date(2026, 10, 16)))
    assert {i.item_id for i in items} == {"p1-mr1", "p1-ob0", "p1-ob1", "p1-ob2", "p1-en0", "p1-en1"}


def test_active_medications_exclude_stopped_doses():
    meds = adapter().active_medications(ActiveMedicationQuery("p1", date(2026, 10, 16)))
    assert {(m.title, m.detail.split(" · ")[0]) for m in meds} == {
        ("Lisinopril", "40 mg PO daily"), ("Metformin", "1000 mg PO BID"), ("Atorvastatin", "40 mg PO nightly")}


def test_patient_with_no_posted_bundle_is_reported_unavailable():
    with pytest.raises(ExternalSourceUnavailable):
        adapter(p1=fhir_bundles()["p1"]).items_between(ChartQuery("p2", date(2026, 9, 1), date(2026, 10, 16)))


def test_malformed_bundle_is_reported_unavailable():
    with pytest.raises(ExternalSourceUnavailable):
        adapter(p1={"resourceType": "Patient"}).items_between(ChartQuery("p1", date(2026, 9, 1), date(2026, 10, 16)))


# ---- end to end: real FHIR through the whole pipeline -------------------------------
def test_pipeline_on_real_mockchart_fhir_for_ellison():
    h = build(ehr=adapter(),
              extractor=FakeExtractSymptoms(SymptomExtraction(("cough",), date(2026, 10, 9), True, "worsening")),
              picker=FakePickRelevantItems({"Lisinopril"}))
    from tests.fixtures.mockchart import inbound
    assert h.trigger.on_patient_message(inbound("p1")).outcome is PipelineOutcome.PACKET_DELIVERED

    packet = h.review.presented[-1]
    refs = {r.source_ref for r in packet.rows if r.origin == "chart"}
    assert "MedicationRequest/p1-mr1" in refs                  # the 09-22 dose increase
    assert "MedicationRequest/p1-mr0" not in refs              # stopped 20 mg: not current, no known stop date
    assert "Observation/p1-ob3" not in refs                    # July LDL, outside the window
    assert packet.rejected_item_count == 0
    current = [r.text for r in packet.rows if r.section == "current_medications"]
    assert "20 mg PO daily · Dose increased: home BP log elevated" not in current


def test_pipeline_on_real_mockchart_fhir_for_boateng_includes_same_day_stat_results():
    from tests.fixtures.mockchart import inbound
    h = build(ehr=adapter(),
              extractor=FakeExtractSymptoms(SymptomExtraction(("chest_pain", "shortness_of_breath", "sweating"),
                                                              date(2026, 10, 16), False, "worsening")))
    h.trigger.on_patient_message(inbound("p5"))
    labs = {r.title: r for r in h.review.presented[-1].rows if r.section == "labs"}
    assert labs["Troponin I"].text == "0.08 ng/mL (ref <0.04)" and labs["Troponin I"].documented_flag == "H"
    assert labs["Troponin I"].days_from_anchor == 0
