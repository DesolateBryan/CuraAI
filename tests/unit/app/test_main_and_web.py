"""app/main.py wiring and the framework-free WebController, through the REAL composition root.

Only the vendor is faked (a fake boto3 bedrock-runtime client). FastAPI is not needed here;
tests/unit/adapters/test_routers.py covers the thin HTTP layer when FastAPI is installed.
"""

import json
import tempfile
from pathlib import Path

import pytest

from curaai.adapters.persistence import read_audit_log
from curaai.adapters.web.controller import parse_message_body
from curaai.adapters.web.page import BRIDGE_TAG, inject_bridge
from curaai.app.main import Config, build_container, load_env_file
from tests.fixtures.mockchart import PATIENTS, fhir_bundles

SENT = {"p1": "2026-10-16T11:42:00Z", "p2": "2026-10-16T12:15:00Z", "p5": "2026-10-16T15:20:00Z"}


def body(pid, text=None, sent_at=None, message_id=None, bundle=True):
    return {"message_id": message_id or f"{pid}-1", "patient_id": pid, "sent_at": sent_at or SENT[pid],
            "text": text or PATIENTS[pid]["message"][1], "origin": "patient",
            **({"fhir_bundle": fhir_bundles()[pid]} if bundle else {})}


class FakeBedrock:
    """Stands in for boto3's bedrock-runtime client; answers by reading the request JSON."""

    def __init__(self, extractions):
        self.extractions = list(extractions)
        self.calls = 0

    def converse(self, **kw):
        self.calls += 1
        data = json.loads(kw["messages"][0]["content"][0]["text"])
        if "patient_message" in data:
            text = self.extractions.pop(0) if self.extractions else '{"symptom_ids": []}'
        elif "candidate_question_ids" in data:
            text = json.dumps({"question_id": sorted(data["candidate_question_ids"])[0]})
        elif "medications" in data:
            text = '{"matches": []}'
        else:
            text = '{"item_ids": []}'
        return {"output": {"message": {"content": [{"text": text}]}}, "usage": {"inputTokens": 500, "outputTokens": 30}}


def container(tmp, backend="none", extractions=(), **env):
    config = Config.from_env({"CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "audit.jsonl"),
                              "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00",
                              "CURAAI_MODEL_BACKEND": backend,
                              **({"CURAAI_BEDROCK_MODEL_ID": "test-model"} if backend == "bedrock" else {}), **env})
    fake = FakeBedrock(extractions)
    return build_container(config, bedrock_client=fake if backend == "bedrock" else None), fake


# ---- Config ------------------------------------------------------------------------------------
def test_config_defaults_run_with_no_cloud_account():
    c = Config.from_env({})
    assert (c.ehr_adapter, c.drug_adapter, c.model_backend) == ("mock_epic", "mock", "local")


@pytest.mark.parametrize("env", [
    {"CURAAI_MODEL_BACKEND": "gpt"},
    {"CURAAI_DRUG_ADAPTER": "firstdatabank"},
    {"CURAAI_EHR_ADAPTER": "epic"},
    {"CURAAI_MODEL_BACKEND": "bedrock"},                    # no model id
    {"CURAAI_PORT": "eighty"},
    {"CURAAI_DAILY_BUDGET_USD": "lots"},
])
def test_bad_settings_fail_fast_with_a_clear_message(env):
    with pytest.raises(ValueError):
        Config.from_env(env)


def test_env_file_reader():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / ".env"
        p.write_text("# comment\nCURAAI_MODEL_BACKEND=none   # inline\nCURAAI_PORT='9000'\nBROKEN LINE\n", encoding="utf-8")
        assert load_env_file(p) == {"CURAAI_MODEL_BACKEND": "none", "CURAAI_PORT": "9000"}
        assert load_env_file(Path(tmp) / "missing.env") == {}


# ---- request parsing -------------------------------------------------------------------------------
@pytest.mark.parametrize("bad, why", [
    (None, "not an object"),
    ({**body("p1"), "text": "   "}, "empty text"),
    ({**body("p1"), "text": "x" * 5001}, "too long"),
    ({**body("p1"), "sent_at": "2026-10-16T07:42:00"}, "no timezone"),
    ({**body("p1"), "sent_at": "yesterday"}, "not ISO"),
    ({**body("p1"), "patient_id": ""}, "no patient"),
    ({**body("p1"), "fhir_bundle": {"resourceType": "Patient"}}, "not a Bundle"),
])
def test_bad_request_bodies_are_rejected(bad, why):
    with pytest.raises(ValueError):
        parse_message_body(bad)


def test_page_gets_the_bridge_script_once():
    html = inject_bridge("<html><body><p>chart</p></body></html>")
    assert html.endswith(BRIDGE_TAG + "</body></html>")
    assert inject_bridge(html) == html


# ---- full wiring, no model backend: the ADR-011 fallback path -------------------------------------------
def test_no_model_backend_still_delivers_the_fixed_chart_pull():
    with tempfile.TemporaryDirectory() as tmp:
        k, _ = container(tmp)
        r = k.controller.post_message(body("p1"))
        assert r.status == 200 and r.body["outcome"] == "packet_delivered"
        review = k.controller.get_review_json(r.body["case_id"])
        assert review.status == 200
        assert "AI screening was unavailable" in " ".join(review.body["notices"])
        html = k.controller.get_review_html(r.body["case_id"])
        assert html.media_type == "text/html" and "Verify in person before prescribing" in html.body
        actions = [e.action for e in read_audit_log(Path(tmp) / "audit.jsonl")]
        assert "model_gateway_error" in actions and actions[-1] == "review_packet_delivered"
        assert k.page_html and "MockEpic" in k.page_html


def test_http_status_codes():
    with tempfile.TemporaryDirectory() as tmp:
        k, _ = container(tmp)
        assert k.controller.post_message({"nope": 1}).status == 400
        assert k.controller.post_message({**body("p1"), "origin": "physician"}).status == 422
        assert k.controller.post_message(body("p2", bundle=False)).status == 503      # no FHIR posted yet
        assert k.controller.get_review_json("unknown").status == 404
        assert k.controller.get_latest_for_patient("p9").status == 404


# ---- full wiring with Bedrock (client faked): follow-up through the outbox ----------------------------
def test_whitaker_follow_up_goes_out_through_the_outbox_and_the_reply_completes_the_case():
    with tempfile.TemporaryDirectory() as tmp:
        k, fake = container(tmp, "bedrock", extractions=[
            '{"symptom_ids": ["dizziness", "nausea"], "onset": null, "onset_is_approx": false, "trend": null}',
            '{"symptom_ids": [], "onset": "2026-10-05", "onset_is_approx": true, "trend": "unchanged"}',
        ])
        first = k.controller.post_message(body("p2"))
        assert first.body["outcome"] == "follow_up_sent" and first.body["review_url"] is None

        (question,) = k.controller.get_outbox(None).body["follow_ups"]
        assert question["patient_id"] == "p2" and question["question_id"] == "ask_onset"
        assert question["sender_label"] == "Automated question from CuraAI"
        assert question["display_text"] == f"Automated question from CuraAI: {question['text']}"
        assert question["text"] == "When did these symptoms first start? An approximate date is fine."
        assert k.controller.get_outbox(None).body["follow_ups"] == []                # drained

        reply = k.controller.post_message(body("p2", text=PATIENTS["p2"]["reply"], message_id="p2-2",
                                               sent_at="2026-10-16T12:20:00Z", bundle=False))
        assert reply.body["outcome"] == "packet_delivered" and reply.body["case_id"] == first.body["case_id"]
        latest = k.controller.get_latest_for_patient("p2").body
        assert latest["outcome"] == "packet_delivered"
        assert latest["review_url"] == f"/reviews/{first.body['case_id']}"
        view = k.controller.get_review_json(first.body["case_id"]).body
        assert view["onset"] == "Around Oct 5, 2026 (approximate, patient-reported)"
        assert fake.calls >= 3


def test_sweep_endpoint_hands_off_expired_cases():
    with tempfile.TemporaryDirectory() as tmp:
        k, _ = container(tmp, "bedrock", extractions=['{"symptom_ids": ["dizziness"]}'],
                         CURAAI_CLOCK_NOW="")                                     # real clock
        k.controller.post_message(body("p2", sent_at="2026-10-16T12:15:00Z"))
        assert k.controller.sweep().body == {"handed_off": []}                    # not yet 24 h
