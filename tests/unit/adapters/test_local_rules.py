"""The local rule-based reader (CURAAI_MODEL_BACKEND=local, the demo default).

1. The pure rules, on every MockChart message and scripted reply.
2. All six MockChart patients through the REAL default wiring (app/main.py), answering
   CuraAI's follow-ups with MockChart's own scripted replies, the way the page does.
"""

import json
import re
import tempfile
from datetime import date
from pathlib import Path

import pytest

from curaai.adapters.model.local_rules import (
    LocalRulesTransport, answer, find_onset, find_symptoms, find_trend, flag_matches, relevant_item_ids,
)
from curaai.adapters.persistence import read_audit_log
from curaai.app.main import Config, build_container
from curaai.domain.symptom_catalog import DEFAULT_SYMPTOM_CATALOG
from tests.fixtures.mockchart import SCRIPTED_REPLIES, fhir_bundles

ALLOWED = set(DEFAULT_SYMPTOM_CATALOG.ids())
OCT16, OCT27 = date(2026, 10, 16), date(2026, 10, 27)


def first_message(pid):
    comm = next(e["resource"] for e in fhir_bundles()[pid]["entry"] if e["resource"]["resourceType"] == "Communication")
    return comm["payload"][0]["contentString"], comm["sent"]


# ---- 1. pure rules on MockChart's own words ------------------------------------------------------
@pytest.mark.parametrize("pid, symptoms, onset, approx, trend", [
    ("p1", {"cough"}, date(2026, 10, 9), True, "worsening"),                       # "No fever" is skipped
    ("p2", {"dizziness", "nausea"}, None, False, None),                            # "lately": no date
    ("p3", {"palpitations", "tremor"}, date(2026, 10, 9), False, None),            # "since last Friday"
    ("p4", {"cough", "fever", "hoarseness"}, date(2026, 10, 14), False, None),     # "since Wednesday"; "breathing ok"
    ("p5", {"chest_pain", "shortness_of_breath", "sweating"}, OCT16, True, None),  # "about an hour ago"
    ("p6", {"headache"}, None, False, None),                                       # "again": no date
])
def test_reads_each_first_message(pid, symptoms, onset, approx, trend):
    text, _ = first_message(pid)
    assert set(find_symptoms(text, ALLOWED)) == symptoms
    assert find_onset(text, OCT16) == (onset, approx)
    assert find_trend(text) == trend


@pytest.mark.parametrize("pid, onset", [
    ("p1", date(2026, 10, 9)), ("p2", date(2026, 10, 5)), ("p3", date(2026, 10, 9)),
    ("p4", date(2026, 10, 14)), ("p6", date(2026, 10, 2)),
])
def test_reads_the_onset_replies(pid, onset):
    assert find_onset(SCRIPTED_REPLIES[pid]["onset"], OCT27)[0] == onset


@pytest.mark.parametrize("pid, trend", [
    ("p1", "worsening"), ("p2", "unchanged"), ("p3", "worsening"),
    ("p4", "unchanged"), ("p5", "worsening"), ("p6", "worsening"),
])
def test_reads_the_trend_replies(pid, trend):
    assert find_trend(SCRIPTED_REPLIES[pid]["trend"]) == trend


def test_relative_words_only_count_as_an_onset_when_the_text_is_about_starting():
    assert find_onset("About the same, maybe slightly better today.", OCT27) == (None, False)
    assert find_onset("almost every other day now instead of once a week", OCT27) == (None, False)
    assert find_onset("It started yesterday", OCT27) == (date(2026, 10, 26), False)
    assert find_onset("began a couple weeks ago", OCT27) == (date(2026, 10, 13), True)


def test_dates_never_land_in_the_future():
    assert find_onset("started December 20th", OCT27)[0] == date(2025, 12, 20)
    assert find_onset("started 12/20", OCT27)[0] == date(2025, 12, 20)


def test_negation_and_unknown_symptoms():
    assert find_symptoms("No chest pain, but I get lightheaded", ALLOWED) == ["lightheadedness"]
    assert find_symptoms("I have a cough", {"fever"}) == []          # only ids the request allowed


def test_relevant_items_and_flags_use_labels_only():
    items = [{"item_id": "m1", "label": "Lisinopril"}, {"item_id": "m2", "label": "Atorvastatin"},
             {"item_id": "l1", "label": "Potassium"}, {"item_id": "l2", "label": "Hemoglobin A1c"}]
    assert relevant_item_ids({"cough"}, items) == ["m1", "l1"]
    meds = [{"item_id": "s", "label": "Sertraline"}, {"item_id": "c", "label": "Cyclobenzaprine"},
            {"item_id": "o", "label": "Omeprazole"}]
    flags = flag_matches({"dizziness"}, meds, {"possible_adverse_effect", "possible_interaction"})
    assert {"item_id": "s", "flag_id": "possible_interaction"} in flags
    assert {"item_id": "c", "flag_id": "possible_adverse_effect"} in flags
    assert not [f for f in flags if f["item_id"] == "o"]


def test_transport_answers_like_a_model_and_costs_nothing():
    request = json.dumps({"message_date": "2026-10-16", "allowed_symptom_ids": sorted(ALLOWED),
                          "patient_message": first_message("p1")[0]})
    reply = LocalRulesTransport().send("system", request, 300)
    assert json.loads(reply.text)["onset"] == "2026-10-09"
    assert (reply.input_tokens, reply.output_tokens, reply.model) == (0, 0, "local-rules-v1")
    assert answer(json.dumps({"missing": ["onset", "trend"],
                              "candidate_question_ids": ["ask_onset", "ask_onset_and_trend", "ask_trend"]})) \
        == '{"question_id": "ask_onset_and_trend"}'


# ---- 2. all six patients through the real default wiring -----------------------------------------------
def answer_like_mockchart(pid, question_text):
    """MockChart's page picks its scripted reply from keywords in the question (its `intent` function)."""
    if re.search(r"appoint|schedul|come in|see you|visit", question_text, re.I):
        return "appt"
    if re.search(r"when|start|begin|onset|how long", question_text, re.I):
        return SCRIPTED_REPLIES[pid]["onset"]
    if re.search(r"better|worse|same|improv|trend|chang", question_text, re.I):
        return SCRIPTED_REPLIES[pid]["trend"]
    return "def"


EXPECTED = {   # pid: (onset, window start, a chart row that must be in the review)
    "p1": ("Around Oct 9, 2026", "Sep 18, 2026", "MedicationRequest/p1-mr1"),   # lisinopril 40 mg, Sep 22
    "p2": ("Around Oct 5, 2026", "Sep 14, 2026", "MedicationRequest/p2-mr1"),   # sertraline 100 mg, Oct 1
    "p3": ("Oct 9, 2026", "Sep 18, 2026", "MedicationRequest/p3-mr1"),          # levothyroxine 88 mcg, Sep 18
    "p4": ("Oct 14, 2026", "Sep 23, 2026", "MedicationRequest/p4-mr0"),         # current albuterol
    "p5": ("Around Oct 16, 2026", "Sep 25, 2026", "Observation/p5-ob0"),        # troponin, same day
    "p6": ("Around Oct 2, 2026", "Sep 11, 2026", "MedicationRequest/p6-mr1"),   # current sumatriptan
}


@pytest.mark.parametrize("pid", sorted(EXPECTED))
def test_default_demo_reads_the_message_asks_for_whats_missing_and_pulls_the_right_chart(pid):
    with tempfile.TemporaryDirectory() as tmp:
        k = build_container(Config.from_env({"CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "audit.jsonl"),
                                             "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00"}))
        text, sent = first_message(pid)
        r = k.controller.post_message({"message_id": f"{pid}-0", "patient_id": pid, "sent_at": sent + "-04:00",
                                       "text": text, "fhir_bundle": fhir_bundles()[pid]})
        for n in range(1, 3):                                         # at most two follow-ups
            if r.body["outcome"] != "follow_up_sent":
                break
            (question,) = k.controller.get_outbox(pid).body["follow_ups"]
            assert question["display_text"].startswith("Automated question from CuraAI: ")
            reply = answer_like_mockchart(pid, question["display_text"])
            r = k.controller.post_message({"message_id": f"{pid}-{n}", "patient_id": pid,
                                           "sent_at": "2026-10-16T13:0%d:00-04:00" % n, "text": reply})

        assert r.body["outcome"] == "packet_delivered", r.body
        view = k.controller.get_review_json(r.body["case_id"]).body
        onset, window_start, must_have = EXPECTED[pid]
        assert view["onset"].startswith(onset)
        assert view["window"].startswith(window_start)
        assert "Not reported" not in view["trend"]
        assert must_have in {row["source_ref"] for s in view["sections"] for row in s["rows"]}
        assert not any("AI screening was unavailable" in n for n in view["notices"])
        models = {e.detail.get("model") for e in read_audit_log(Path(tmp) / "audit.jsonl")
                  if e.action == "model_gateway_call"}
        assert models == {"local-rules-v1"}


def test_ellison_gets_the_lisinopril_cough_flag():
    with tempfile.TemporaryDirectory() as tmp:
        k = build_container(Config.from_env({"CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "a.jsonl"),
                                             "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00"}))
        text, sent = first_message("p1")
        r = k.controller.post_message({"message_id": "p1-0", "patient_id": "p1", "sent_at": sent + "-04:00",
                                       "text": text, "fhir_bundle": fhir_bundles()["p1"]})
        view = k.controller.get_review_json(r.body["case_id"]).body
        meds = next(s for s in view["sections"] if s["key"] == "medication_changes")["rows"]
        (lisinopril,) = [m for m in meds if m["title"] == "Lisinopril"]
        assert lisinopril["date"] == "Sep 22, 2026" and lisinopril["offset"] == "17 days before onset"
        assert "possible adverse effect" in lisinopril["ai_tags"]
