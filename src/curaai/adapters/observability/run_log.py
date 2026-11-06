"""format_run_log: the audit log as a run log a person can read (Governance ADR 1 and ADR 2).

The audit log (JSONL, ADR-007) is the single source of truth; this pure function only
re-words it. One block per case, in the order cases started, one line per event:

    case p2-20261016130000  patient p2
      13:00:02  case opened
      13:00:03  AI extract_symptoms: openai/gpt-oss-20b, 412+38 tokens, $0.0001, 640 ms
      13:00:03  guardrail passed: extract_symptoms answer accepted by the validator
      ...
      13:00:05  HITL GATE: waiting for a physician's sign-off (patient reply blocked)
      13:04:10  HITL: dr-demo APPROVED, reply sent to the patient (84 chars)

then the ADR-008 numbers (case_metrics) and the HITL counts. Off-ramps (AI switched off,
fixed chart pull only) and failed guardrails are marked with "!!" so they stand out.
Patient message text never appears: the audit log does not hold it.

Shown at GET /runlog and by `python -m curaai.app.runlog`.
"""

from collections.abc import Iterable, Mapping

from curaai.adapters.observability.metrics import case_metrics
from curaai.application.dto.audit import AuditEvent

ALERT = "!!"
SKIP = frozenset({"model_port_call"})        # the gateway line already says the same, with more


def _describe(e: AuditEvent) -> str:
    d: Mapping = e.detail
    a = e.action
    port = d.get("port", "")
    if a == "case_opened":
        return f"case opened for patient {d.get('patient_id')}"
    if a == "patient_reply_received":
        return "patient replied to the automated question"
    if a == "model_gateway_call":
        return (f"AI {port}: {d.get('model')}, {d.get('input_tokens')}+{d.get('output_tokens')} tokens, "
                f"${float(d.get('cost_usd') or 0):.4f}, {d.get('latency_ms')} ms")
    if a == "model_gateway_error":
        return f"{ALERT} AI {port} failed: {d.get('message') or d.get('error')}"
    if a == "model_output_accepted":
        return f"guardrail passed: {port} answer accepted by the validator"
    if a == "model_output_rejected":
        return f"{ALERT} GUARDRAIL FAILED on {port}: {d.get('reason')} -> off-ramp: AI off for this case"
    if a == "model_unavailable":
        return f"{ALERT} AI unavailable{' for ' + port if port else ''} -> off-ramp: fixed chart pull continues"
    if a == "ai_cap_reached":
        return f"{ALERT} case cap reached ({d.get('limit')}) -> AI stops, fixed chart pull continues"
    if a == "cost_guard_tripped":
        return f"{ALERT} COST GUARD tripped ({d.get('limit')}, ${float(d.get('spent_usd') or 0):.4f} spent)"
    if a == "follow_up_sent":
        return (f"automated follow-up #{d.get('follow_up_number')} sent: {d.get('question_id')} "
                f"(missing {d.get('missing')}, chosen by {d.get('chosen_by')})")
    if a == "follow_up_timed_out":
        return f"{ALERT} no reply in 24 hours -> handed to the physician incomplete, no chart pull"
    if a == "chart_pulled":
        return (f"chart pulled {d.get('window_start')} to {d.get('window_end')}: "
                f"{d.get('changes')} changes, {d.get('current_meds')} current medications (read-only)")
    if a in ("chart_item_rejected", "drug_record_rejected"):
        return f"record withheld ({d.get('item_id') or d.get('drug')}): {d.get('reason')}"
    if a == "drug_not_found":
        return f"drug database has no entry for {d.get('drug')}"
    if a == "drug_lookup_failed":
        return f"drug lookup failed for {d.get('drug')}: {d.get('error')}"
    if a == "review_packet_delivered":
        extra = ", AI fallback" if d.get("ai_fallback") else ""
        return f"review packet delivered to the physician ({d.get('status')}, {d.get('rows')} rows{extra})"
    if a == "hitl_gate_opened":
        return "HITL GATE: waiting for a physician's sign-off (patient reply blocked until then)"
    if a == "hitl_decision":
        if d.get("decision") == "approve":
            return f"HITL: {d.get('physician')} APPROVED, reply sent to the patient ({d.get('reply_chars')} chars)"
        return f"HITL: {d.get('physician')} RETURNED the case, nothing sent to the patient"
    if a == "hitl_blocked":
        return (f"{ALERT} HITL BLOCKED: {d.get('reason')} (attempted by {d.get('attempted_by') or 'nobody'}), "
                "nothing sent")
    details = ", ".join(f"{k}={v}" for k, v in d.items() if k not in ("request_id", "raw_output"))
    return f"{a}{' (' + details + ')' if details else ''}"


def format_run_log(events: Iterable[AuditEvent], source: str = "audit log") -> str:
    events = list(events)
    if not events:
        return f"CuraAI run log ({source})\n\nNo events yet. Send a patient message, then reload this page.\n"
    cases: dict[str, list[AuditEvent]] = {}
    for e in events:
        cases.setdefault(e.subject_id, []).append(e)

    lines = [f"CuraAI run log ({source}): {len(events)} events, {len(cases)} cases", ""]
    for case_id, case_events in cases.items():
        patient = next((e.detail.get("patient_id") for e in case_events if e.action == "case_opened"), None)
        lines.append(f"case {case_id}" + (f"  patient {patient}" if patient else ""))
        for e in case_events:
            if e.action not in SKIP:
                lines.append(f"  {e.at.strftime('%H:%M:%S')}  {_describe(e)}")
        lines.append("")

    m = case_metrics(events)
    count = {a: sum(1 for e in events if e.action == a) for a in ("hitl_gate_opened", "hitl_decision", "hitl_blocked")}
    approved = sum(1 for e in events if e.action == "hitl_decision" and e.detail.get("decision") == "approve")
    lines += [
        "Summary (Governance ADR 2; rates per 100 cases)",
        f"  cases {m.cases}, review packets delivered {m.packets_delivered}",
        f"  off-ramp rate (handed off incomplete) {m.off_ramp_rate * 100:.1f}%, AI fallbacks {m.ai_fallbacks_per_100:.1f}",
        f"  failed guardrails {m.failed_guardrails_per_100:.1f}, follow-ups {m.follow_ups_per_100:.1f}, "
        f"timeouts {m.timeouts_per_100:.1f}, cost-guard trips {m.cost_guard_trips}",
        f"  AI calls {m.model_calls}, tokens {m.input_tokens}+{m.output_tokens}, cost ${m.cost_usd_total:.4f} "
        f"(${m.cost_usd_per_case:.4f} per case), median AI latency {m.median_model_latency_ms} ms",
        f"  HITL gates opened {count['hitl_gate_opened']}, decided {count['hitl_decision']} "
        f"({approved} approved, {count['hitl_decision'] - approved} returned), blocked attempts {count['hitl_blocked']}, "
        f"awaiting a physician {count['hitl_gate_opened'] - count['hitl_decision']}",
    ]
    return "\n".join(lines) + "\n"
