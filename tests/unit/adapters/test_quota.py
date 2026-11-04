"""quota.py: PortRouter, ReplyCache, Pacer, and the full six-patient demo through app/main.py
with a fake Gemini, counting how many calls actually reach Google."""

import tempfile
import threading
from pathlib import Path

import pytest

from curaai.adapters.model.gateway import VendorReply
from curaai.adapters.model.gateway_client import Prompt
from curaai.adapters.model.local_rules import answer as rules_answer
from curaai.adapters.model.quota import Pacer, PortRouter, ReplyCache
from curaai.adapters.persistence import read_audit_log
from curaai.app.main import Config, build_container
from tests.fixtures.mockchart import SCRIPTED_REPLIES, fhir_bundles

KEY = "test-key-NOT-REAL-123"


class CountingTransport:
    def __init__(self, fail_first=0):
        self.calls, self.fail_first = 0, fail_first

    def send(self, system, user, max_output_tokens):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("busy")
        return VendorReply(f"answer {self.calls}", 100, 20, "gemini-x")


# ---- PortRouter ------------------------------------------------------------------------------
def test_router_sends_each_port_to_its_client():
    class Client:
        def __init__(self, name):
            self.name, self.ports = name, []

        def complete(self, prompt):
            self.ports.append(prompt.port)
            return self.name

    gemini, local = Client("gemini"), Client("local")
    router = PortRouter(local, {"extract_symptoms": gemini})
    for port in ("extract_symptoms", "select_follow_up", "pick_relevant_items", "match_flags"):
        router.complete(Prompt("c1:s:1", port, "v1", "S", "U"))
    assert gemini.ports == ["extract_symptoms"]
    assert local.ports == ["select_follow_up", "pick_relevant_items", "match_flags"]


# ---- ReplyCache --------------------------------------------------------------------------------
def test_same_request_is_answered_once_and_the_repeat_costs_nothing():
    inner = CountingTransport()
    cache = ReplyCache(inner)
    first = cache.send("S", "U", 300)
    again = cache.send("S", "U", 300)
    assert inner.calls == 1 and again.text == first.text
    assert (again.input_tokens, again.output_tokens, again.model) == (0, 0, "gemini-x (cached)")
    cache.send("S", "different", 300)
    cache.send("S", "U", 999)
    assert inner.calls == 3


def test_failures_are_not_cached():
    inner = CountingTransport(fail_first=1)
    cache = ReplyCache(inner)
    with pytest.raises(RuntimeError):
        cache.send("S", "U", 300)
    assert cache.send("S", "U", 300).text == "answer 2"


def test_cache_size_is_bounded():
    inner = CountingTransport()
    cache = ReplyCache(inner, max_entries=2)
    for u in ("a", "b", "c"):
        cache.send("S", u, 300)
    cache.send("S", "a", 300)                       # "a" was evicted, so it is asked again
    assert inner.calls == 4


# ---- Pacer -------------------------------------------------------------------------------------
class FakeTime:
    def __init__(self):
        self.now, self.waits = 100.0, []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.waits.append(round(s, 3))


def test_pacer_spaces_request_starts():
    t = FakeTime()
    pacer = Pacer(CountingTransport(), 6, clock=t.clock, sleep=t.sleep)   # one start every 10 s
    for _ in range(3):
        pacer.send("S", "U", 300)
    assert t.waits == [10.0, 20.0]
    t.now = 200.0                                                        # quiet for a while: no wait
    pacer.send("S", "U", 300)
    assert t.waits == [10.0, 20.0]


def test_pacer_books_distinct_slots_across_threads():
    t = FakeTime()
    pacer = Pacer(CountingTransport(), 60, clock=t.clock, sleep=t.sleep)  # one per second
    threads = [threading.Thread(target=pacer.send, args=("S", "U", 300)) for _ in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(t.waits) == [1.0, 2.0, 3.0, 4.0]


def test_pacer_rejects_zero():
    with pytest.raises(ValueError):
        Pacer(CountingTransport(), 0)


# ---- the whole demo: how many calls reach Google? -------------------------------------------------
class FakeGemini:
    def __init__(self):
        self.calls = 0

    def post_json(self, url, headers, body, timeout_s):
        self.calls += 1
        text = rules_answer(body["contents"][0]["parts"][0]["text"])
        return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 30}, "modelVersion": "gemini-x"}


def run_demo(k, tag=""):
    """Every MockChart patient: first message, then the scripted replies to any follow-ups."""
    outcomes = {}
    for pid, bundle in fhir_bundles().items():
        comm = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Communication")
        r = k.controller.post_message({"message_id": f"{pid}{tag}-0", "patient_id": pid, "sent_at": comm["sent"] + "-04:00",
                                       "text": comm["payload"][0]["contentString"], "fhir_bundle": bundle})
        replies = iter(SCRIPTED_REPLIES.get(pid, {}).values())
        n = 0
        while r.body["outcome"] == "follow_up_sent":
            n += 1
            k.controller.get_outbox(pid)
            r = k.controller.post_message({"message_id": f"{pid}{tag}-{n}", "patient_id": pid,
                                           "sent_at": f"2026-10-16T13:0{n}:00-04:00", "text": next(replies)})
        outcomes[pid] = r.body["outcome"]
    return outcomes


def demo(tmp, **env):
    config = Config.from_env({"CURAAI_MODEL_BACKEND": "gemini", "CURAAI_GEMINI_API_KEY": KEY,
                              "CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "audit.jsonl"),
                              "CURAAI_CLOCK_NOW": "2026-10-16T13:00:00-04:00", **env})
    google, waits = FakeGemini(), []
    return build_container(config, gemini_poster=google, model_sleep=waits.append), google, waits


def test_reading_only_mode_cuts_gemini_calls_and_still_finishes_every_case():
    with tempfile.TemporaryDirectory() as tmp:
        k_all, google_all, _ = demo(tmp, CURAAI_AI_USE_FOR="all", CURAAI_AI_MAX_PER_MINUTE="0")
        all_outcomes = run_demo(k_all)
    with tempfile.TemporaryDirectory() as tmp:
        k, google, waits = demo(tmp)                                   # defaults: reading only, 8 per minute
        outcomes = run_demo(k)
        events = read_audit_log(Path(tmp) / "audit.jsonl")
    assert outcomes == all_outcomes and set(outcomes.values()) == {"packet_delivered"}
    assert (google.calls, google_all.calls) == (16, 30)                 # one full demo run
    gemini_ports = {e.detail["port"] for e in events if e.action == "model_gateway_call" and e.detail["model"] == "gemini-x"}
    assert gemini_ports == {"extract_symptoms"}
    # 8/min = one start every 7.5 s. The fake sleep doesn't move time, so each wait is 7.5 s longer
    assert len(waits) == google.calls - 1 and round(waits[1] - waits[0], 1) == 7.5


def test_rerunning_the_demo_costs_no_new_gemini_calls():
    with tempfile.TemporaryDirectory() as tmp:
        k, google, _ = demo(tmp, CURAAI_AI_MAX_PER_MINUTE="0")
        run_demo(k)
        first = google.calls
        again = run_demo(k, tag="-rerun")                              # the same messages screened again
        assert set(again.values()) == {"packet_delivered"}
        assert first > 0 and google.calls == first


def test_settings_are_validated():
    with pytest.raises(ValueError):
        Config.from_env({"CURAAI_AI_USE_FOR": "some"})
    with pytest.raises(ValueError):
        Config.from_env({"CURAAI_AI_MAX_PER_MINUTE": "-1"})
    c = Config.from_env({"CURAAI_AI_USE_FOR": "ALL", "CURAAI_AI_MAX_PER_MINUTE": "0"})
    assert (c.ai_use_for, c.ai_max_per_minute) == ("all", 0.0)
