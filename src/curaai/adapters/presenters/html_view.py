"""render_review_html: the humble view. ReviewView in, one self-contained HTML page out.

Rules (ADR-014): no conditionals, no sorting, no date formatting, no labels,
no truncation. It loops, escapes and fills slots. One smoke test covers it.
"""

from html import escape

from curaai.adapters.presenters.gate_presenter import GateForm, GateView
from curaai.adapters.presenters.review_presenter import ReviewView, ViewRow, ViewSection

_CSS = """
:root{--bg:#f3f5f8;--card:#fff;--tx:#1b2430;--mu:#5d6b7c;--bd:#d9e0e8;--ac:#1a6bb5;--warn:#7a1f1f;--note:#fff3c4}
@media (prefers-color-scheme:dark){:root{--bg:#12171d;--card:#1b232c;--tx:#e6ebf0;--mu:#9aa7b5;--bd:#2f3b47;--ac:#5aa6ea;--note:#4a4217}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 "Segoe UI",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
header{background:var(--card);border:1px solid var(--bd);border-top:3px solid var(--ac);padding:12px 14px;margin-bottom:10px}
header h1{margin:0 0 6px;font-size:18px;color:var(--ac)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;margin:0}dt{color:var(--mu)}dd{margin:0}
.banner{background:var(--warn);color:#fff;padding:9px 12px;font-weight:600;margin-bottom:8px}
.notice{background:var(--note);border:1px solid var(--bd);padding:8px 12px;margin-bottom:8px}
section{background:var(--card);border:1px solid var(--bd);margin-bottom:12px}
section h2{margin:0;padding:7px 12px;font-size:13px;color:var(--ac);border-bottom:1px solid var(--bd)}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:760px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--bd);vertical-align:top}
th{color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.03em}
td.text{white-space:pre-wrap}.mu{color:var(--mu);font-size:12px}
.gate{background:var(--card);border:2px solid var(--ac);padding:12px 14px;margin-bottom:12px}
.gate h2{margin:0 0 4px;font-size:15px;color:var(--ac)}.gate p{margin:0 0 8px}
.gate label{display:block;font-weight:600;margin:6px 0 2px}
.gate input,.gate textarea{width:100%;font:inherit;padding:6px;border:1px solid var(--bd);background:var(--bg);color:var(--tx)}
.gate button{font:inherit;padding:6px 12px;margin:8px 8px 0 0;cursor:pointer}
.gate .err{color:#c0392b;font-weight:600}
"""

# Posts the decision as JSON, then reloads so the panel shows the result (or the refusal).
_GATE_JS = """
async function curaaiDecide(caseId, decision){
  const f = document.getElementById("gate-" + caseId), err = f.querySelector(".err");
  const body = {decision, physician_id: f.physician.value, reply_text: decision === "approve" ? f.reply.value : ""};
  const res = await fetch("/api/reviews/" + encodeURIComponent(caseId) + "/decision",
    {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (res.ok) { location.reload(); return; }
  err.textContent = "Not sent: " + ((await res.json()).error || res.status);
}
"""

_COLUMNS = ("Date", "Relative to anchor", "Item", "As documented", "Author / source", "Flag", "AI", "Origin", "Source ref")


def render_gate_html(gate: GateView) -> str:
    forms = "".join(_gate_form(f) for f in gate.forms)
    return (f'<section class="gate" id="hitl-gate"><h2>{escape(gate.status_label)}</h2>'
            f"<p>{escape(gate.detail)}</p>{forms}</section>")


def _gate_form(f: GateForm) -> str:
    case = escape(f.case_id, quote=True)
    return (f'<form id="gate-{case}" onsubmit="return false">'
            f'<label for="physician">Physician id</label>'
            f'<input id="physician" name="physician" value="{escape(f.physician_default, quote=True)}" autocomplete="off">'
            f'<label for="reply">Reply to the patient (sent only if you approve)</label>'
            f'<textarea id="reply" name="reply" rows="3"></textarea>'
            f'<button type="button" data-case="{case}" data-decision="approve" '
            f'onclick="curaaiDecide(this.dataset.case, this.dataset.decision)">Approve and send reply</button>'
            f'<button type="button" data-case="{case}" data-decision="return" '
            f'onclick="curaaiDecide(this.dataset.case, this.dataset.decision)">Return to clinic queue (send nothing)</button>'
            f'<div class="err" role="alert"></div></form>')


def render_review_html(view: ReviewView, gate_html: str = "") -> str:
    banners = "".join(f'<div class="banner">{escape(b)}</div>' for b in view.banners)
    notices = "".join(f'<div class="notice">{escape(n)}</div>' for n in view.notices)
    facts = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in (
        ("Status", view.status_label), ("Symptoms", view.symptoms), ("Onset", view.onset),
        ("Trend", view.trend), ("Chart window", view.window), ("Case", view.case_id)))
    sections = "".join(_section(s) for s in view.sections)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>CuraAI Review</title><style>{_CSS}</style><script>{_GATE_JS}</script></head><body><main>"
            f"{banners}<header><h1>{escape(view.patient_label)}</h1><dl>{facts}</dl></header>"
            f"{gate_html}{notices}{sections}</main></body></html>")


def _section(section: ViewSection) -> str:
    head = "".join(f"<th>{c}</th>" for c in _COLUMNS)
    body = "".join(_row(r) for r in section.rows)
    return (f'<section data-key="{escape(section.key)}"><h2>{escape(section.title)}</h2>'
            f'<div class="tw"><table><tr>{head}</tr>{body}</table></div></section>')


def _row(r: ViewRow) -> str:
    cells = (r.date, r.offset, r.title, r.text, r.author, r.documented_flag, r.ai_tags, r.origin_label, r.source_ref)
    classes = ("", "mu", "", "text", "mu", "", "mu", "mu", "mu")
    return "<tr>" + "".join(f'<td class="{c}">{escape(v)}</td>' for c, v in zip(classes, cells)) + "</tr>"
