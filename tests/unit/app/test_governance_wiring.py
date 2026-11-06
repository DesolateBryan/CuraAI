"""Governance, wired and visible, through the REAL composition root (app/main.py).

    * the HITL gate fires on the consequential path (a reply to the patient) and the
      physician's decision goes through the web layer, the outbox and the audit log
    * the run log (GET /runlog, python -m curaai.app.runlog) is readable and shows the
      model calls, the guardrail, the off-ramp and the HITL gate
    * Main is honest: governance configuration comes from Main, and nothing outside Main
      creates an object across a boundary
"""

import ast
import inspect
import tempfile
from pathlib import Path

import pytest

from curaai.adapters.persistence import read_audit_log
from curaai.app import runlog
from curaai.app.main import Config, build_container
from tests.unit.app.test_main_and_web import body, container

SRC = Path(__file__).resolve().parents[3] / "src" / "curaai"
REPLY = "Please come in Thursday morning so we can check your blood pressure."


def delivered(tmp, backend="local", pid="p1", **env):
    k, _ = container(tmp, backend, **env)
    r = k.controller.post_message(body(pid))
    assert r.body["outcome"] == "packet_delivered"
    return k, r.body["case_id"]


# ---- HITL gate over HTTP --------------------------------------------------------------------------
def test_review_shows_the_open_gate_and_only_an_approver_can_release_a_reply():
    with tempfile.TemporaryDirectory() as tmp:
        k, case = delivered(tmp)
        review = k.controller.get_review_json(case).body
        assert review["physician_review"]["status"] == "awaiting_physician"
        page = k.controller.get_review_html(case).body
        assert "Awaiting physician sign-off" in page and "Approve and send reply" in page

        blocked = k.controller.post_decision(case, {"decision": "approve", "physician_id": "CuraAI", "reply_text": REPLY})
        assert blocked.status == 403 and blocked.body["reason"] == "not_an_approver"
        assert k.controller.get_outbox("p1").body == {"follow_ups": []}            # nothing left CuraAI

        ok = k.controller.post_decision(case, {"decision": "approve", "physician_id": "dr-demo", "reply_text": REPLY})
        assert ok.status == 200 and ok.body["physician_review"]["status"] == "approved"
        (item,) = k.controller.get_outbox("p1").body["follow_ups"]
        assert item["question_id"] == "physician_reply" and item["text"] == REPLY
        assert item["display_text"] == f"Reply approved by dr-demo: {REPLY}"

        again = k.controller.post_decision(case, {"decision": "return", "physician_id": "dr-demo"})
        assert again.status == 409
        assert "Approved by dr-demo" in k.controller.get_review_html(case).body

        actions = [e.action for e in read_audit_log(Path(tmp) / "audit.jsonl")]
        assert actions.count("hitl_gate_opened") == 1 and actions.count("hitl_decision") == 1
        assert actions.count("hitl_blocked") == 2
        assert REPLY not in (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad, status", [(None, 400), ({"decision": 1, "physician_id": "dr-demo"}, 400),
                                         ({"decision": "approve", "physician_id": "dr-demo", "reply_text": 5}, 400),
                                         ({"decision": "approve", "physician_id": "dr-demo", "reply_text": " "}, 422)])
def test_bad_decision_bodies(bad, status):
    with tempfile.TemporaryDirectory() as tmp:
        k, case = delivered(tmp)
        assert k.controller.post_decision(case, bad).status == status
        assert k.controller.post_decision("nope", {"decision": "approve", "physician_id": "dr-demo",
                                                   "reply_text": REPLY}).status == 404


def test_approver_list_comes_from_main():
    with tempfile.TemporaryDirectory() as tmp:
        k, case = delivered(tmp, CURAAI_HITL_APPROVERS="dr-lee, dr-patel")
        assert k.controller.post_decision(case, {"decision": "return", "physician_id": "dr-demo"}).status == 403
        assert k.controller.post_decision(case, {"decision": "return", "physician_id": "dr-patel"}).status == 200
    with pytest.raises(ValueError):
        Config.from_env({"CURAAI_HITL_APPROVERS": " , "})


# ---- readable run log ----------------------------------------------------------------------------------
def test_run_log_shows_the_ai_call_the_guardrail_and_the_hitl_gate():
    with tempfile.TemporaryDirectory() as tmp:
        k, case = delivered(tmp, "local", "p1")
        k.controller.post_decision(case, {"decision": "approve", "physician_id": "dr-demo", "reply_text": REPLY})
        text = k.controller.get_run_log()
        assert text.media_type == "text/plain"
        log = text.body
        assert f"case {case}  patient p1" in log
        assert "AI extract_symptoms: local-rules" in log
        assert "guardrail passed: extract_symptoms answer accepted by the validator" in log
        assert "HITL GATE: waiting for a physician's sign-off" in log
        assert "HITL: dr-demo APPROVED, reply sent to the patient" in log
        assert "HITL gates opened 1, decided 1 (1 approved, 0 returned)" in log
        assert REPLY not in log and body("p1")["text"] not in log          # no patient or physician text


def test_run_log_marks_the_off_ramp_when_the_ai_backend_fails():
    with tempfile.TemporaryDirectory() as tmp:
        k, case = delivered(tmp, "none", "p1")
        log = k.controller.get_run_log().body
        assert "!! AI extract_symptoms failed" in log and "-> off-ramp: fixed chart pull continues" in log
        assert "review packet delivered to the physician" in log and "AI fallback" in log


def test_web_run_log_shows_only_this_server_session():
    with tempfile.TemporaryDirectory() as tmp:
        delivered(tmp)                                       # an earlier server run wrote to the same file
        k, case = delivered(tmp)
        assert k.controller.get_run_log().body.count("case opened") == 1


def test_run_log_command(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        delivered(tmp)
        delivered(tmp, "none", "p5")                         # AI off, so p5 goes straight to a packet
        assert runlog.main([str(Path(tmp) / "audit.jsonl"), "--last", "1"]) == 0
        out = capsys.readouterr().out
        assert "1 cases" in out and "patient p5" in out and "patient p1" not in out
        assert runlog.main([str(Path(tmp) / "missing.jsonl")]) == 1


# ---- Main is honest ---------------------------------------------------------------------------------------
def test_governance_configuration_is_owned_by_main():
    from curaai.application.use_cases import PipelineTrigger
    params = inspect.signature(PipelineTrigger).parameters
    assert params["limits"].default is inspect.Parameter.empty      # no silent default caps in Ring 2
    assert params["timeout"].default is inspect.Parameter.empty
    with tempfile.TemporaryDirectory() as tmp:
        config = Config.from_env({"CURAAI_AUDIT_LOG_PATH": str(Path(tmp) / "a.jsonl"), "CURAAI_MAX_MODEL_CALLS": "3",
                                  "CURAAI_MAX_FOLLOW_UPS": "1", "CURAAI_MAX_CASE_COST_USD": "0.10",
                                  "CURAAI_FOLLOW_UP_TIMEOUT_HOURS": "12"})
        k = build_container(config)
        assert k.trigger._limits.max_model_calls == 3 and k.trigger._limits.max_follow_ups == 1
        assert str(k.trigger._limits.max_cost_usd) == "0.10" and k.trigger._timeout.duration.total_seconds() == 12 * 3600
    for bad in ({"CURAAI_MAX_LOOKUPS": "-1"}, {"CURAAI_FOLLOW_UP_TIMEOUT_HOURS": "0"}):
        with pytest.raises(ValueError):
            Config.from_env(bad)


def test_model_transports_cannot_build_their_own_http_client():
    from curaai.adapters.model.gemini_transport import GeminiTransport
    from curaai.adapters.model.groq_transport import GroqTransport
    for cls in (GeminiTransport, GroqTransport):
        assert inspect.signature(cls).parameters["poster"].default is inspect.Parameter.empty, cls.__name__


def _constructed_classes(path: Path) -> set[str]:
    """CamelCase names called like constructors in a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id[:1].isupper()}


def _adapter_classes() -> set[str]:
    names = set()
    for path in (SRC / "adapters").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names |= {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    return names


def test_nothing_outside_main_constructs_an_adapter():
    adapters = _adapter_classes() - {"GeminiError", "GroqError", "ModelHttpError", "Check"}
    offenders = {}
    for path in (SRC / "app").glob("*.py"):
        if path.name in ("main.py", "__init__.py"):
            continue
        made = _constructed_classes(path) & adapters
        if made:
            offenders[path.name] = sorted(made)
    for ring in ("domain", "application"):                     # inner rings cannot even import adapters
        for path in (SRC / ring).rglob("*.py"):
            made = _constructed_classes(path) & adapters
            if made:
                offenders[path.relative_to(SRC).as_posix()] = sorted(made)
    assert offenders == {}


def test_each_adapter_package_constructs_only_its_own_classes():
    """Adapters never import each other (import-linter), so any adapter built inside an adapter
    package must be one of its own: e.g. the model package never creates a web or EHR object."""
    for package in (SRC / "adapters").iterdir():
        if not package.is_dir() or package.name.startswith("__"):
            continue
        own = {n.name for p in package.rglob("*.py") for n in ast.parse(p.read_text(encoding="utf-8")).body
               if isinstance(n, ast.ClassDef)}
        foreign = (_adapter_classes() - own) & set().union(*(_constructed_classes(p) for p in package.rglob("*.py")))
        assert foreign == set(), (package.name, foreign)
