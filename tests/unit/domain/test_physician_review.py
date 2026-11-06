"""PhysicianReview: the HITL gate's rules (Governance ADR 3). Pure domain, no ports."""

from datetime import datetime, timezone

import pytest

from curaai.domain.errors import HitlRejected
from curaai.domain.physician_review import (
    MAX_REPLY_CHARS, Decision, GateStatus, PhysicianReview, physician_sender_label,
)

AT = datetime(2026, 10, 16, 17, 0, tzinfo=timezone.utc)
APPROVERS = frozenset({"dr-demo", "dr-lee"})


def gate():
    return PhysicianReview.open("c1", "p2", AT)


def reason(fn):
    with pytest.raises(HitlRejected) as info:
        fn()
    return info.value.reason


def test_a_new_gate_waits_for_a_physician():
    g = gate()
    assert g.status is GateStatus.AWAITING_PHYSICIAN and g.is_open and g.physician_id is None


def test_an_approver_can_approve_with_a_reply_once():
    done = gate().decide(Decision.APPROVE, " dr-demo ", "  Please come in Thursday.  ", AT, APPROVERS)
    assert (done.status, done.physician_id, done.reply_text, done.decided_at) == (
        GateStatus.APPROVED, "dr-demo", "Please come in Thursday.", AT)
    assert reason(lambda: done.decide(Decision.RETURN, "dr-lee", None, AT, APPROVERS)) == "already_decided"


def test_a_return_sends_nothing():
    done = gate().decide(Decision.RETURN, "dr-lee", "", AT, APPROVERS)
    assert done.status is GateStatus.RETURNED and done.reply_text is None
    assert reason(lambda: gate().decide(Decision.RETURN, "dr-lee", "hi", AT, APPROVERS)) == "return_with_text"


@pytest.mark.parametrize("who", ["", "  ", "nurse-kim", "CuraAI", "dr-demo2"])
def test_only_listed_approvers_can_decide(who):
    assert reason(lambda: gate().decide(Decision.APPROVE, who, "ok", AT, APPROVERS)) == "not_an_approver"


def test_an_approval_needs_a_real_reply():
    assert reason(lambda: gate().decide(Decision.APPROVE, "dr-demo", "   ", AT, APPROVERS)) == "empty_reply"
    long = "x" * (MAX_REPLY_CHARS + 1)
    assert reason(lambda: gate().decide(Decision.APPROVE, "dr-demo", long, AT, APPROVERS)) == "reply_too_long"


def test_a_refused_decision_leaves_the_gate_open():
    g = gate()
    reason(lambda: g.decide(Decision.APPROVE, "intruder", "hi", AT, APPROVERS))
    assert g.is_open


def test_times_must_be_timezone_aware_and_the_label_names_the_physician():
    with pytest.raises(ValueError):
        PhysicianReview.open("c1", "p2", datetime(2026, 10, 16, 17, 0))
    assert physician_sender_label("dr-demo") == "Reply approved by dr-demo"
    assert "automated" not in physician_sender_label("dr-demo").lower()
