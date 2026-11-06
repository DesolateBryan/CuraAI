"""present_gate: a case's HITL gate (PhysicianReview) -> GateView, made only of strings.

Every display decision about the sign-off panel is made here (ADR-014): the status line,
the explanation, and whether the decision form is offered (only while the gate is open).
The view loops over `forms` (empty once decided), so it never branches.
"""

from dataclasses import dataclass

from curaai.domain.physician_review import GateStatus, PhysicianReview

_EXPLAIN = ("CuraAI never replies to the patient. Only a physician on the approver list can approve a reply, "
            "and nothing is sent until they do.")


@dataclass(frozen=True)
class GateForm:
    case_id: str
    physician_default: str


@dataclass(frozen=True)
class GateView:
    status: str                    # machine value for JSON: awaiting_physician | approved | returned | none
    status_label: str
    detail: str
    forms: tuple[GateForm, ...]    # one form while awaiting a physician, none after


def present_gate(review: PhysicianReview | None, physician_default: str) -> GateView:
    if review is None:
        return GateView("none", "No sign-off needed yet", "The review packet has not been delivered.", ())
    if review.status is GateStatus.AWAITING_PHYSICIAN:
        return GateView(review.status.value, "Awaiting physician sign-off (HITL gate)", _EXPLAIN,
                        (GateForm(review.case_id, physician_default),))
    at = review.decided_at
    when = f"{at:%b} {at.day}, {at:%Y %H:%M}" if at else ""      # no %-d: it fails on Windows
    if review.status is GateStatus.APPROVED:
        return GateView(review.status.value, f"Approved by {review.physician_id}",
                        f"{when}. Reply sent to the patient: \"{review.reply_text}\"", ())
    return GateView(review.status.value, f"Returned by {review.physician_id}",
                    f"{when}. Nothing was sent to the patient; the case is back in the clinic queue.", ())


def gate_view_to_dict(view: GateView) -> dict:
    return {"status": view.status, "status_label": view.status_label, "detail": view.detail,
            "awaiting_physician": bool(view.forms)}
