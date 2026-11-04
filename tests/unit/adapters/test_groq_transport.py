"""GroqTransport with a fake HTTP poster (no network, no key needed), the full demo through
app/main.py with CURAAI_MODEL_BACKEND=groq, and the Groq part of the setup check."""

import tempfile
from pathlib import Path

import pytest

from curaai.adapters.model.groq_transport import (
    DEFAULT_MODEL, GroqError, GroqTransport, groq_models, groq_request, parse_groq_response,
)
from curaai.adapters.model.local_rules import answer as rules_answer
from curaai.adapters.persistence import read_audit_log
from curaai.app.check import FAIL, OK, run_checks
from curaai.app.main import Config, build_container
from tests.fixtures.mockchart import SCRIPTED_REPLIES, fhir_bundles

KEY = "gsk_test-key-NOT-REAL-123"


def groq_response(text, prompt_tokens=380, completion_tokens=45, model="openai/gpt-oss-20b"):
    return {"id": "chatcmpl-1", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}}


class FakeGroq:
    """Answers like Groq would, using the local reader's rules on the same request."""

    def __init__(self, errors=(), models=(DEFAULT_MODEL, "llama-x", "whisper-large-v3")):
        self.calls, self.errors, self.models, self.timeouts = [], list(errors), list(models), []

    def post_json(self, url, headers, body, timeout_s):
        self.calls.append((url, dict(headers), body))
        self.timeouts.append(timeout_s)
        if self.errors:
            raise self.errors.pop(0)
        return groq_response(rules_answer(body["messages"][1]["content"]), model=body["model"])

    def get_json(self, url, headers, timeout_s):
        assert url.endswith("/models") and headers == {"Authorization": f"Bearer {KEY}"}
        return {"object": "list", "data": [{"id": m, "object": "model"} for m in self.models]}


# ---- request / response shape -------------------------------------------------------------------
def test_request_is_json_mode_with_low_reasoning_and_room_to_answer():
    body = groq_request("openai/gpt-oss-20b", "SYSTEM", "USER", 60)
    assert body["messages"] == [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "USER"}]
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 1024 and body["reasoning_effort"] == "low"
    assert body["include_reasoning"] is False
    other = groq_request("qwen/some-model", "S", "U", 300, reasoning_effort=None)
    assert "reasoning_effort" not in other and "include_reasoning" not in other


def test_curaai_prompts_mention_json_as_groq_requires():
    from curaai.adapters.model import prompts
    assert "JSON" in prompts._COMMON


def test_key_goes_in_the_authorization_header_never_the_url():
    poster = FakeGroq()
    GroqTransport(KEY, poster=poster).send("S", '{"items": [], "symptom_ids": []}', 300)
    url, headers, _ = poster.calls[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert headers == {"Authorization": f"Bearer {KEY}"} and KEY not in url
    assert KEY not in repr(GroqTransport(KEY, poster=poster))


def test_answer_usage_and_model_are_read():
    reply = parse_groq_response(groq_response('{"question_id": "ask_onset"}'), "m")
    assert (reply.text, reply.input_tokens, reply.output_tokens, reply.model) == (
        '{"question_id": "ask_onset"}', 380, 45, "openai/gpt-oss-20b")


@pytest.mark.parametrize("response", [{"choices": []}, {},
                                      {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
                                      {"choices": [{"message": {"content": None}}]}])
def test_empty_answers_raise(response):
    with pytest.raises(GroqError):
        parse_groq_response(response, "m")


# ---- retries and backup model (shared with Gemini) ----------------------------------------------------
def test_rate_limit_waits_as_long_as_groq_asks_then_succeeds():
    waits = []
    poster = FakeGroq(errors=[GroqError("Groq HTTP 429: Rate limit reached", status=429, retry_after_s=6.0)])
    GroqTransport(KEY, poster=poster, sleep=waits.append).send("S", '{"items": [], "symptom_ids": []}', 300)
    assert waits == [6.0] and len(poster.calls) == 2


def test_busy_main_model_switches_to_the_backup_but_a_bad_key_does_not():
    busy = [GroqError("Groq HTTP 503: over capacity", status=503)] * 3
    poster = FakeGroq(errors=busy)
    reply = GroqTransport(KEY, poster=poster, sleep=lambda s: None, fallback_model="llama-x").send(
        "S", '{"items": [], "symptom_ids": []}', 300)
    assert reply.model == "llama-x" and poster.calls[-1][2]["model"] == "llama-x"
    bad = FakeGroq(errors=[GroqError("Groq HTTP 401: Invalid API Key", status=401)])
    with pytest.raises(GroqError):
        GroqTransport(KEY, poster=bad, fallback_model="llama-x").send("S", "{}", 300)
    assert len(bad.calls) == 1


def test_model_list_is_read():
    assert groq_models(KEY, FakeGroq()) == sorted([DEFAULT_MODEL, "llama-x", "whisper-large-v3"])


# ---- through the real wiring ----------------------------------------------------------------------------
def container(tmp, poster, **env):
    config = Config.from_env({"CURAAI_MODEL_BACKEND": "groq", "CURAAI_GROQ_API_KEY": KEY,
                              "CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "audit.jsonl"),
                              "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00", **env})
    return build_container(config, groq_poster=poster, model_sleep=lambda s: None)


def run_patient(k, pid):
    bundle = fhir_bundles()[pid]
    comm = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Communication")
    r = k.controller.post_message({"message_id": f"{pid}-0", "patient_id": pid, "sent_at": comm["sent"] + "-04:00",
                                   "text": comm["payload"][0]["contentString"], "fhir_bundle": bundle})
    replies, n = iter(SCRIPTED_REPLIES.get(pid, {}).values()), 0
    while r.body["outcome"] == "follow_up_sent":
        n += 1
        k.controller.get_outbox(pid)
        r = k.controller.post_message({"message_id": f"{pid}-{n}", "patient_id": pid,
                                       "sent_at": f"2026-10-16T13:0{n}:00-04:00", "text": next(replies)})
    return r


@pytest.mark.parametrize("use_for", ["reading", "all"])
def test_whitaker_end_to_end_through_groq(use_for):
    with tempfile.TemporaryDirectory() as tmp:
        poster = FakeGroq()
        k = container(tmp, poster, CURAAI_AI_USE_FOR=use_for)
        r = run_patient(k, "p2")
        assert r.body["outcome"] == "packet_delivered"
        view = k.controller.get_review_json(r.body["case_id"]).body
        assert view["onset"].startswith("Around Oct 5, 2026") and view["window"].startswith("Sep 14, 2026")
        assert not any("AI screening was unavailable" in n for n in view["notices"])
        events = read_audit_log(Path(tmp) / "audit.jsonl")
        groq_ports = {e.detail["port"] for e in events
                      if e.action == "model_gateway_call" and e.detail["model"] == DEFAULT_MODEL}
        assert groq_ports == ({"extract_symptoms"} if use_for == "reading" else
                              {"extract_symptoms", "select_follow_up", "pick_relevant_items", "match_flags"})
        assert KEY not in (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")


def test_groq_outage_falls_back_to_the_fixed_chart_pull():
    with tempfile.TemporaryDirectory() as tmp:
        k = container(tmp, FakeGroq(errors=[GroqError("Groq HTTP 401: Invalid API Key", status=401)]))
        r = run_patient(k, "p1")
        view = k.controller.get_review_json(r.body["case_id"]).body
        assert any("AI screening was unavailable" in n for n in view["notices"])
        (error,) = [e for e in read_audit_log(Path(tmp) / "audit.jsonl") if e.action == "model_gateway_error"][:1]
        assert error.detail["error"] == "GroqError" and "Invalid API Key" in error.detail["message"]


def test_config_requires_a_key_and_accepts_the_standard_env_name():
    with pytest.raises(ValueError):
        Config.from_env({"CURAAI_MODEL_BACKEND": "groq"})
    assert Config.from_env({"CURAAI_MODEL_BACKEND": "groq", "GROQ_API_KEY": "k"}).groq_api_key == "k"
    assert KEY not in repr(Config.from_env({"CURAAI_MODEL_BACKEND": "groq", "CURAAI_GROQ_API_KEY": KEY}))


# ---- setup check -------------------------------------------------------------------------------------
def check(tmp, poster, extra=""):
    root = Path(tmp)
    (root / ".env").write_text(f"CURAAI_MODEL_BACKEND=groq\nCURAAI_GROQ_API_KEY={KEY}\n{extra}", encoding="utf-8")
    (root / "MockChart – test.html").write_text("<html></html>", encoding="utf-8")
    checks = run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False, groq_http=poster)
    return {c.name: c for c in checks}, checks


def test_check_passes_and_never_prints_the_key():
    with tempfile.TemporaryDirectory() as tmp:
        c, checks = check(tmp, FakeGroq())
        assert c["Groq connection"].status == OK and c["Groq test call"].status == OK
        assert "...-123" in c["model backend"].detail and not any(KEY in ch.detail for ch in checks)


def test_check_points_at_the_right_fix():
    with tempfile.TemporaryDirectory() as tmp:
        class Refused(FakeGroq):
            def get_json(self, url, headers, timeout_s):
                raise GroqError("Groq HTTP 401: Invalid API Key", status=401)
        assert "console.groq.com/keys" in check(tmp, Refused())[0]["Groq connection"].detail
        wrong = check(tmp, FakeGroq(), "CURAAI_GROQ_MODEL=no-such-model\n")[0]["Groq connection"]
        assert wrong.status == FAIL and "llama-x" in wrong.detail and "whisper" not in wrong.detail
        limit = check(tmp, FakeGroq(errors=[GroqError("Groq HTTP 429: tokens per day", status=429,
                                                      retry_after_s=0.001)] * 3))[0]["Groq test call"]
        assert limit.status == FAIL and "resets tomorrow" in limit.detail


# ---- every request names itself (Cloudflare blocks urllib's default "Python-urllib/3.x") ------------------
def test_requests_send_a_curaai_user_agent_not_pythons_default():
    import urllib.request

    from curaai.adapters.model.http_transport import USER_AGENT
    from curaai.adapters.model.groq_transport import groq_poster
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"data": []}'

    def fake_urlopen(request, timeout):
        seen.append({k.lower(): v for k, v in request.header_items()})
        return Response()

    real, urllib.request.urlopen = urllib.request.urlopen, fake_urlopen
    try:
        poster = groq_poster()
        poster.post_json("https://api.groq.com/openai/v1/chat/completions", {"Authorization": "Bearer k"}, {}, 5)
        poster.get_json("https://api.groq.com/openai/v1/models", {"Authorization": "Bearer k"}, 5)
    finally:
        urllib.request.urlopen = real
    assert [h["user-agent"] for h in seen] == [USER_AGENT, USER_AGENT]
    assert not USER_AGENT.startswith("Python-urllib") and seen[0]["authorization"] == "Bearer k"


def test_a_bare_403_is_not_called_a_bad_key():
    with tempfile.TemporaryDirectory() as tmp:
        class Blocked(FakeGroq):
            def get_json(self, url, headers, timeout_s):
                raise GroqError("Groq HTTP 403: Forbidden", status=403)
        detail = check(tmp, Blocked())[0]["Groq connection"].detail
        assert "git pull" in detail and "hotspot" in detail and "console.groq.com/keys" not in detail
