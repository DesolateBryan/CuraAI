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
    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def post_json(self, url, headers, body, timeout_s):
        self.calls += 1
        if self.error:
            raise self.error
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}], "modelVersion": "gemini-x"}


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
        assert c["Gemini test call"].status == OK and poster.calls == 1
        assert "...abcd" in c["model backend"].detail
        assert not any(key in ch.detail for ch in checks)


def test_gemini_errors_point_at_the_right_fix():
    with tempfile.TemporaryDirectory() as tmp:
        root = folder(tmp, "CURAAI_MODEL_BACKEND=gemini\nCURAAI_GEMINI_API_KEY=AIzaWRONGKEY99\n")
        bad_key = by_name(run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False,
                                     gemini_poster=Poster(GeminiError("Gemini HTTP 400: API key not valid"))))
        assert bad_key["Gemini test call"].status == FAIL and "aistudio.google.com" in bad_key["Gemini test call"].detail
        offline = by_name(run_checks(root / ".env", {}, cwd=root, port_probe=lambda h, p: False,
                                     gemini_poster=Poster(GeminiError("Gemini unreachable: timed out"))))
        assert "internet connection" in offline["Gemini test call"].detail


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
