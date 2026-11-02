"""python -m curaai.app.check: plain-words setup report. No network: Gemini and the port are faked."""

import tempfile
from pathlib import Path

from curaai.adapters.model.gemini_transport import GeminiError
from curaai.app.check import FAIL, OK, WARN, mask, run_checks

PAGE = "MockChart – test.html"


def folder(tmp, env_text=None, page=True):
    root = Path(tmp)
    if env_text is not None:
        (root / ".env").write_text(env_text, encoding="utf-8")
    if page:
        (root / PAGE).write_text("<html><body>MockEpic</body></html>", encoding="utf-8")
    return root


class Poster:
    """Fake Google: `lookup_error` fails the fast model lookup, `error` fails the test answer."""

    def __init__(self, error=None, lookup_error=None):
        self.error, self.lookup_error, self.calls, self.lookups = error, lookup_error, 0, 0
        self.timeouts = []

    def get_json(self, url, headers, timeout_s):
        self.lookups += 1
        if self.lookup_error:
            raise self.lookup_error
        return {"name": "models/gemini-x"}

    def post_json(self, url, headers, body, timeout_s):
        self.calls += 1
        self.timeouts.append(timeout_s)
        if self.error:
            raise self.error
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}], "modelVersion": "gemini-x"}


class Clock:
    """Each read moves time forward by `step` seconds."""

    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def by_name(checks):
    return {c.name: c for c in checks}


def test_defaults_with_no_env_file_are_ready_but_say_so():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp)
        c = by_name(run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False))
        assert c[".env file"].status == WARN and "Copy .env.example" in c[".env file"].detail
        assert c["model backend"].detail.startswith("local rule-based reader")
        assert c["port"].status == OK and c["MockChart page"].status == OK


def test_old_server_on_the_port_is_called_out():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=local\n")
        c = by_name(run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: True))
        assert c["port"].status == WARN and "old CuraAI server" in c["port"].detail


def test_bad_settings_fail_with_the_reason():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=gemini\n")              # no key
        checks = run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False)
        assert checks[-1].status == FAIL and "CURAAI_GEMINI_API_KEY is required" in checks[-1].detail


def test_gemini_key_is_tested_and_never_printed():
    key = "AIzaSECRET-abcd"
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, f"CURAAI_MODEL_BACKEND=gemini\nCURAAI_GEMINI_API_KEY={key}\n")
        poster = Poster()
        checks = run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False, gemini_poster=poster)
        c = by_name(checks)
        assert c["Gemini connection"].status == OK and poster.lookups == 1
        assert c["Gemini test call"].status == OK and poster.calls == 1
        assert poster.timeouts == [60.0]                            # same wait the demo uses
        assert "...abcd" in c["model backend"].detail
        assert not any(key in ch.detail for ch in checks)


def gemini_run(root, poster, clock=None, env=None):
    kw = {"clock": clock} if clock else {}
    return by_name(run_checks(root / ".env", env or {}, cwd=root, port_probe=lambda h, p: False,
                              gemini_poster=poster, **kw))


def test_gemini_errors_point_at_the_right_fix():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=gemini\nCURAAI_GEMINI_API_KEY=AIzaWRONGKEY99\n")
        bad_key = gemini_run(root, Poster(lookup_error=GeminiError("Gemini HTTP 400: API key not valid", status=400)))
        assert bad_key["Gemini connection"].status == FAIL and "aistudio.google.com" in bad_key["Gemini connection"].detail
        assert "Gemini test call" not in bad_key                    # no point generating text with a bad key
        wrong_model = gemini_run(root, Poster(lookup_error=GeminiError("Gemini HTTP 404: not found", status=404)))
        assert "model name is wrong" in wrong_model["Gemini connection"].detail
        blocked = gemini_run(root, Poster(lookup_error=GeminiError("Gemini sent no answer within 15 s (timed out)",
                                                                   timed_out=True)))
        assert "can't reach Google" in blocked["Gemini connection"].detail
        assert "hotspot" in blocked["Gemini connection"].detail


def test_a_slow_model_is_told_apart_from_a_blocked_network():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=gemini\nCURAAI_GEMINI_API_KEY=AIzaKEY0000\n")
        slow = gemini_run(root, Poster(error=GeminiError("Gemini sent no answer within 60 s (timed out)", timed_out=True)))
        assert slow["Gemini connection"].status == OK
        assert slow["Gemini test call"].status == FAIL and "CURAAI_GEMINI_TIMEOUT_S" in slow["Gemini test call"].detail
        limit = gemini_run(root, Poster(error=GeminiError("Gemini HTTP 429: quota", status=429)))
        assert "limit" in limit["Gemini test call"].detail


def test_answer_time_is_shown_and_a_slow_answer_warns():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=gemini\nCURAAI_GEMINI_API_KEY=AIzaKEY0000\n")
        quick = gemini_run(root, Poster(), clock=Clock(1.0))
        assert quick["Gemini test call"].status == OK and "answered in 1.0 s" in quick["Gemini test call"].detail
        sluggish = gemini_run(root, Poster(), clock=Clock(40.0))
        assert sluggish["Gemini test call"].status == WARN and "lighter model" in sluggish["Gemini test call"].detail


def test_timeout_setting_is_read_from_env():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=gemini\nCURAAI_GEMINI_API_KEY=AIzaKEY0000\nCURAAI_GEMINI_TIMEOUT_S=120\n")
        poster = Poster()
        gemini_run(root, poster)
        assert poster.timeouts == [120.0]


def test_terminal_variables_that_override_env_are_reported():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=local\n")
        c = by_name(run_checks(root / ".env", {"CURAAI_MODEL_BACKEND": "none"}, cwd=root, port_probe=lambda h, p: False))
        assert c["environment"].status == WARN and "CURAAI_MODEL_BACKEND" in c["environment"].detail
        assert c["model backend"].detail.startswith("none")


def test_missing_page_fails():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=local\n", page=False)
        c = by_name(run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False))
        assert c["MockChart page"].status == FAIL


def test_mask():
    assert mask("") == "NOT SET" and mask("abc") == "set" and mask("AIzaXYZ12345") == "set (ends in ...2345)"
