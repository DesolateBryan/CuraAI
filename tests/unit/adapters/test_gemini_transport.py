"""GeminiTransport with a fake HTTP poster (no network, no key needed), and the full pipeline
through app/main.py with CURAAI_MODEL_BACKEND=gemini.

The fake answers each request the way Gemini would: a generateContent response whose text is
JSON. To make those answers realistic it reuses the local reader's rules on the same request.
"""

import json
import tempfile
from pathlib import Path

import pytest

from curaai.adapters.model import GeminiTransport, gemini_request, parse_gemini_response
from curaai.adapters.model.gemini_transport import MIN_OUTPUT_TOKENS, GeminiError, gemini_url
from curaai.adapters.model.local_rules import answer as rules_answer
from curaai.adapters.persistence import read_audit_log
from curaai.app.main import Config, build_container
from tests.fixtures.mockchart import SCRIPTED_REPLIES, fhir_bundles

KEY = "test-key-NOT-REAL-123"


def gemini_response(text, prompt_tokens=420, out_tokens=35, thoughts=60, model="gemini-3.8-flash-001"):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": prompt_tokens, "candidatesTokenCount": out_tokens,
                              "thoughtsTokenCount": thoughts, "totalTokenCount": prompt_tokens + out_tokens + thoughts},
            "modelVersion": model}


class FakePoster:
    def __init__(self, error=None, reply=None):
        self.calls, self.error, self.reply = [], error, reply

    def post_json(self, url, headers, body, timeout_s):
        self.calls.append((url, dict(headers), body))
        if self.error:
            raise self.error
        if self.reply is not None:
            return self.reply
        return gemini_response(rules_answer(body["contents"][0]["parts"][0]["text"]))


# ---- request / response shape ----------------------------------------------------------------------
def test_request_asks_for_json_with_low_thinking_and_room_to_answer():
    body = gemini_request("SYSTEM", "USER", 300)
    assert body["systemInstruction"] == {"parts": [{"text": "SYSTEM"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "USER"}]}]
    assert body["generationConfig"] == {"responseMimeType": "application/json", "maxOutputTokens": MIN_OUTPUT_TOKENS,
                                        "thinkingConfig": {"thinkingLevel": "low"}}
    assert "thinkingConfig" not in gemini_request("S", "U", 300, thinking_level=None)["generationConfig"]
    assert "temperature" not in body["generationConfig"]


def test_key_goes_in_a_header_never_in_the_url():
    poster = FakePoster(reply=gemini_response('{"item_ids": []}'))
    GeminiTransport(KEY, poster=poster).send("S", '{"items": [], "symptom_ids": []}', 300)
    url, headers, _ = poster.calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    assert headers == {"x-goog-api-key": KEY} and KEY not in url
    assert KEY not in repr(GeminiTransport(KEY, poster=poster))


def test_response_text_usage_and_model_version_are_read():
    reply = parse_gemini_response(gemini_response('{"question_id": "ask_onset"}'), "gemini-3.8-flash")
    assert reply.text == '{"question_id": "ask_onset"}'
    assert (reply.input_tokens, reply.output_tokens, reply.model) == (420, 95, "gemini-3.8-flash-001")


def test_thought_parts_are_not_treated_as_the_answer():
    response = gemini_response("x")
    response["candidates"][0]["content"]["parts"] = [{"text": "let me think...", "thought": True},
                                                     {"text": '{"item_ids": []}'}]
    assert parse_gemini_response(response, "m").text == '{"item_ids": []}'


@pytest.mark.parametrize("response", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]},
    {"candidates": []},
])
def test_blocked_or_empty_answers_raise(response):
    with pytest.raises(GeminiError):
        parse_gemini_response(response, "m")


def test_model_name_is_url_safe():
    assert gemini_url("gemini-3.8-flash") .endswith("/models/gemini-3.8-flash:generateContent")
    assert "%2F" in gemini_url("x/../../evil")


# ---- through the real wiring ----------------------------------------------------------------------------
def container(tmp, poster):
    config = Config.from_env({"CURAAI_MODEL_BACKEND": "gemini", "CURAAI_GEMINI_API_KEY": KEY,
                              "CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "audit.jsonl"),
                              "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00"})
    return build_container(config, gemini_poster=poster)


def first_message(pid):
    comm = next(e["resource"] for e in fhir_bundles()[pid]["entry"] if e["resource"]["resourceType"] == "Communication")
    return comm["payload"][0]["contentString"], comm["sent"] + "-04:00"


def test_whitaker_end_to_end_through_gemini():
    with tempfile.TemporaryDirectory() as tmp:
        poster = FakePoster()
        k = container(tmp, poster)
        text, sent = first_message("p2")
        r = k.controller.post_message({"message_id": "p2-0", "patient_id": "p2", "sent_at": sent, "text": text,
                                       "fhir_bundle": fhir_bundles()["p2"]})
        for n, kind in enumerate(("onset", "trend"), start=1):
            if r.body["outcome"] != "follow_up_sent":
                break
            k.controller.get_outbox("p2")
            r = k.controller.post_message({"message_id": f"p2-{n}", "patient_id": "p2",
                                           "sent_at": f"2026-10-16T13:0{n}:00-04:00", "text": SCRIPTED_REPLIES["p2"][kind]})
        assert r.body["outcome"] == "packet_delivered"
        view = k.controller.get_review_json(r.body["case_id"]).body
        assert view["onset"].startswith("Around Oct 5, 2026") and view["window"].startswith("Sep 14, 2026")

        events = read_audit_log(Path(tmp) / "audit.jsonl")
        calls = [e for e in events if e.action == "model_gateway_call"]
        assert calls and {e.detail["model"] for e in calls} == {"gemini-3.8-flash-001"}
        assert all(e.detail["cost_usd"] > 0 for e in calls)
        raw_log = (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
        assert KEY not in raw_log                                    # the key never reaches the audit log
        assert "dizzy and kind of nauseous" not in json.dumps([c[2]["systemInstruction"] for c in poster.calls])


def test_gemini_outage_falls_back_to_the_fixed_chart_pull():
    with tempfile.TemporaryDirectory() as tmp:
        k = container(tmp, FakePoster(error=GeminiError("Gemini HTTP 429: quota exceeded")))
        text, sent = first_message("p1")
        r = k.controller.post_message({"message_id": "p1-0", "patient_id": "p1", "sent_at": sent, "text": text,
                                       "fhir_bundle": fhir_bundles()["p1"]})
        assert r.body["outcome"] == "packet_delivered"
        view = k.controller.get_review_json(r.body["case_id"]).body
        assert any("AI screening was unavailable" in n for n in view["notices"])
        errors = [e for e in read_audit_log(Path(tmp) / "audit.jsonl") if e.action == "model_gateway_error"]
        assert errors and errors[0].detail["error"] == "GeminiError"


def test_config_requires_a_key_and_accepts_the_standard_env_name():
    with pytest.raises(ValueError):
        Config.from_env({"CURAAI_MODEL_BACKEND": "gemini"})
    assert Config.from_env({"CURAAI_MODEL_BACKEND": "gemini", "GEMINI_API_KEY": "k"}).gemini_api_key == "k"
    assert KEY not in repr(Config.from_env({"CURAAI_MODEL_BACKEND": "gemini", "CURAAI_GEMINI_API_KEY": KEY}))
