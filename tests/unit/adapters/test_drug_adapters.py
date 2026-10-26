"""MockDrugAdapter, OpenFdaAdapter, and the full pipeline on real EHR + drug adapters."""

import json
from datetime import date
from pathlib import Path

import pytest

from curaai.adapters.drug import (
    HttpNotFound, MockDrugAdapter, OpenFdaAdapter, build_label_url, load_mockchart_drugs, openfda_to_drug_record,
)
from curaai.adapters.ehr import InMemoryBundleSource, MockEpicAdapter
from curaai.application.dto.drug import DrugQuery
from curaai.application.dto.model import SymptomExtraction
from curaai.application.errors import ExternalSourceUnavailable
from curaai.application.mapping import drug_info_from
from curaai.application.ports.drug_db_port import DrugDbPort
from tests.compose import build
from tests.fakes import FakeExtractSymptoms, FakePickRelevantItems
from tests.fixtures.mockchart import fhir_bundles, inbound

LISINOPRIL = json.loads((Path(__file__).parents[2] / "fixtures" / "openfda" / "lisinopril_search.json").read_text())


# ---- MockDrugAdapter ---------------------------------------------------------------
def mock():
    return MockDrugAdapter(load_mockchart_drugs())


def test_mock_list_matches_the_page_and_finds_drugs_inside_chart_names():
    a = mock()
    assert isinstance(a, DrugDbPort)
    assert a.lookup(DrugQuery("Ferrous sulfate")).drug_name == "ferrous"
    assert a.lookup(DrugQuery("Metoprolol succinate")).class_text == "Beta-blocker"
    assert a.lookup(DrugQuery("Warfarin")) is None


def test_mock_records_carry_the_pages_interaction_table_both_ways():
    lisinopril = mock().lookup(DrugQuery("Lisinopril"))
    assert "With ibuprofen (Moderate): NSAID can blunt BP control and raise kidney injury risk" in lisinopril.interactions_text
    ibuprofen = mock().lookup(DrugQuery("Ibuprofen"))
    assert "With lisinopril (Moderate)" in ibuprofen.interactions_text


def test_every_mock_record_passes_the_core_checks():
    for record in load_mockchart_drugs().values():
        assert drug_info_from(record).source_ref.startswith("mockchart:drug/")


# ---- openFDA: pure parts --------------------------------------------------------------
def test_url_sends_only_the_drug_name_quoted():
    url = build_label_url("Metoprolol succinate")
    assert url == ("https://api.fda.gov/drug/label.json?search=openfda.generic_name:%22Metoprolol%20succinate%22"
                   "+openfda.brand_name:%22Metoprolol%20succinate%22&limit=5")


def test_skips_combination_products_and_takes_the_exact_match():
    record = openfda_to_drug_record(LISINOPRIL, DrugQuery("Lisinopril"))
    assert record.source_ref == "openfda:spl/lisino-1111-synthetic@20240615"
    assert "combination" not in (record.adverse_text or "")


def test_label_text_is_verbatim_and_never_truncated():
    record = openfda_to_drug_record(LISINOPRIL, DrugQuery("lisinopril"))
    label = LISINOPRIL["results"][1]
    assert record.adverse_text == label["adverse_reactions"][0] and len(record.adverse_text) > 900
    assert record.boxed_warning_text == label["boxed_warning"][0]
    assert record.contraindications_text == label["contraindications"][0]
    assert record.interactions_text == "\n\n".join(label["drug_interactions"])
    assert record.class_text == "Angiotensin Converting Enzyme Inhibitor [EPC]"


def test_brand_name_lookup_works_and_near_misses_do_not():
    assert openfda_to_drug_record(LISINOPRIL, DrugQuery("Zestril")) is not None
    assert openfda_to_drug_record(LISINOPRIL, DrugQuery("Lisinopril 40 mg")) is None
    assert openfda_to_drug_record({"results": []}, DrugQuery("Lisinopril")) is None
    assert openfda_to_drug_record({"error": {"code": "NOT_FOUND"}}, DrugQuery("Lisinopril")) is None


def test_label_without_a_set_id_gets_an_empty_source_so_the_core_rejects_it():
    stripped = json.loads(json.dumps(LISINOPRIL))
    for r in stripped["results"]:
        r.pop("set_id"), r.pop("id")
    record = openfda_to_drug_record(stripped, DrugQuery("Lisinopril"))
    assert record.source_ref == ""
    with pytest.raises(Exception):
        drug_info_from(record)


# ---- openFDA: humble adapter ----------------------------------------------------------
class FakeHttp:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.urls = response, error, []

    def get_json(self, url, timeout_s):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.response


def test_adapter_makes_one_get_and_maps_the_answer():
    http = FakeHttp(LISINOPRIL)
    record = OpenFdaAdapter(http).lookup(DrugQuery("Lisinopril"))
    assert record.drug_name == "LISINOPRIL" and len(http.urls) == 1


def test_404_means_not_found_and_other_failures_mean_unavailable():
    assert OpenFdaAdapter(FakeHttp(error=HttpNotFound("x"))).lookup(DrugQuery("Lisinopril")) is None
    with pytest.raises(ExternalSourceUnavailable):
        OpenFdaAdapter(FakeHttp(error=TimeoutError("timed out"))).lookup(DrugQuery("Lisinopril"))


# ---- end to end: MockEpicAdapter + MockDrugAdapter through the whole pipeline ---------
def test_pipeline_with_real_ehr_and_drug_adapters_for_whitaker():
    h = build(
        ehr=MockEpicAdapter(InMemoryBundleSource(fhir_bundles()), api_key="mock-curaai-key-0000"),
        drug_db=mock(),
        extractor=FakeExtractSymptoms(SymptomExtraction(("dizziness", "nausea"), date(2026, 10, 5), True, "unchanged")),
        picker=FakePickRelevantItems({"Omeprazole"}),
    )
    h.trigger.on_patient_message(inbound("p2"))
    packet = h.review.presented[-1]

    drug_rows = {r.title: r for r in packet.rows if r.section == "drug_information"}
    # meds changed in the window (onset Oct 5 - 21 d = Sep 14): sertraline increase, cyclobenzaprine, ibuprofen
    assert {t.split(":")[0] for t in drug_rows} == {"sertraline", "cyclobenzaprine", "ibuprofen"}
    assert drug_rows["sertraline: Adverse reactions"].text == "Nausea, dizziness, low sodium, serotonin syndrome"
    assert "With cyclobenzaprine (Major): Serotonin syndrome risk" in drug_rows["sertraline: Drug interactions"].text
    assert all(r.source_ref.startswith("mockchart:drug/") for r in drug_rows.values())
    # omeprazole was not changed in the window: it comes only from the AI-suggested lookup, labeled separately
    ai_rows = [r for r in packet.rows if r.section == "ai_suggested_lookups"]
    assert {r.title.split(":")[0] for r in ai_rows} == {"omeprazole"}
    assert packet.rejected_item_count == 0


def test_full_stack_review_for_ellison_renders_through_the_real_presenter():
    from curaai.adapters.presenters import InMemoryReviewSink, ReviewPresenter, render_review_html
    from tests.fakes import FakeMatchFlags
    sink = InMemoryReviewSink()
    h = build(
        ehr=MockEpicAdapter(InMemoryBundleSource(fhir_bundles()), api_key="mock-curaai-key-0000"),
        drug_db=mock(),
        extractor=FakeExtractSymptoms(SymptomExtraction(("cough",), date(2026, 10, 9), True, "worsening")),
        flagger=FakeMatchFlags({"Lisinopril": "possible_adverse_effect"}),
        review_output=ReviewPresenter(sink),
    )
    h.trigger.on_patient_message(inbound("p1"))

    (view,) = sink.views.values()
    meds = next(s for s in view.sections if s.key == "medication_changes").rows
    assert [(m.date, m.offset, m.title) for m in meds] == [("Sep 22, 2026", "17 days before onset", "Lisinopril")]
    assert "Dry cough, hyperkalemia, angioedema, dizziness" in render_review_html(view)
