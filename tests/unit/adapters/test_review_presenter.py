"""ReviewPresenter with plain data (no UI imports), plus one smoke test for the humble HTML view."""

from dataclasses import replace
from datetime import date

from curaai.adapters.presenters import (
    InMemoryReviewSink, ReviewPresenter, present_review, render_review_html,
)
from curaai.adapters.presenters.review_presenter import BANNER, EMPTY_ROW_TEXT, format_offset
from curaai.application.dto.review import ReviewResponse, ReviewRow
from curaai.application.ports.review_output_port import ReviewOutputPort


def row(section, text, day=None, offset=None, origin="chart", **kw):
    return ReviewRow(section=section, text=text, source_ref=kw.pop("source_ref", f"src:{text[:8]}"), origin=origin,
                     title=kw.pop("title", None), day=day, days_from_anchor=offset, author=kw.pop("author", None),
                     documented_flag=kw.pop("documented_flag", None), flags=kw.pop("flags", ()),
                     ai_selected=kw.pop("ai_selected", False))


def response(**kw):
    base = dict(
        case_id="c1", patient_id="p1", status="prefetched", incomplete_reason=None,
        anchor_date=date(2026, 10, 9), window_start=date(2026, 9, 18), window_end=date(2026, 10, 16),
        onset=date(2026, 10, 9), onset_is_approx=True, trend="worsening", symptom_labels=("Cough",),
        rows=(
            row("patient_messages", "I've had a dry cough", date(2026, 10, 16), 7, origin="patient"),
            row("labs", "4.6 mmol/L (ref 3.5–5.1)", date(2026, 9, 22), -17, title="Potassium"),
            row("medication_changes", "40 mg PO daily · Increased from 20 mg", date(2026, 9, 22), -17,
                title="Lisinopril", flags=("possible_adverse_effect",), ai_selected=True),
            row("visits", "Diabetic eye exam.", date(2026, 9, 29), -10, title="Ophthalmology"),
            row("visits", "BP 148/92, home log elevated.", date(2026, 9, 22), -17, title="Office visit"),
            row("current_medications", "1000 mg PO BID", date(2024, 6, 3), -858, title="Metformin"),
            row("drug_information", "Dry cough, hyperkalemia", origin="drug_database", title="lisinopril: Adverse reactions"),
        ),
        ai_fallback=False, rejected_item_count=0, requires_in_person_verification=True,
    )
    return ReviewResponse(**{**base, **kw})


def section(view, key):
    return next(s for s in view.sections if s.key == key)


# ---- what the presenter decides ------------------------------------------------------
def test_section_order_is_fixed():
    keys = [s.key for s in present_review(response()).sections]
    assert keys == ["patient_messages", "medication_changes", "current_medications", "visits", "labs",
                    "drug_information"]


def test_rows_are_chronological_against_onset():
    visits = section(present_review(response()), "visits").rows
    assert [r.title for r in visits] == ["Office visit", "Ophthalmology"]
    assert [r.offset for r in visits] == ["17 days before onset", "10 days before onset"]


def test_dates_and_offsets_are_formatted_here():
    assert format_offset(-1, "onset") == "1 day before onset"
    assert format_offset(0, "onset") == "Same day as onset"
    assert format_offset(3, "first message") == "3 days after first message"
    labs = section(present_review(response()), "labs").rows
    assert labs[0].date == "Sep 22, 2026"


def test_current_medications_show_since_and_no_offset():
    (metformin,) = section(present_review(response()), "current_medications").rows
    assert (metformin.date, metformin.offset) == ("Since Jun 3, 2024", "")


def test_approximate_onset_and_patient_reported_wording():
    view = present_review(response())
    assert view.onset == "Around Oct 9, 2026 (approximate, patient-reported)"
    assert view.trend == "Getting worse (patient-reported)"
    exact = present_review(response(onset_is_approx=False))
    assert exact.onset == "Oct 9, 2026 (patient-reported)"
    (msg,) = section(view, "patient_messages").rows
    assert msg.origin_label == "Patient-reported"


def test_banner_is_always_present():
    assert present_review(response()).banners == (BANNER,)
    assert present_review(response(status="messages_only", incomplete_reason="timed_out",
                                   window_start=None, window_end=None)).banners == (BANNER,)


def test_ai_marks_and_flags_become_labels():
    (lisinopril,) = section(present_review(response()), "medication_changes").rows
    assert lisinopril.ai_tags == "AI: likely relevant; AI flag: possible adverse effect, see drug information"


def test_text_and_sources_pass_through_untouched():
    resp = response()
    view = present_review(resp)
    shown = {(r.text, r.source_ref) for s in view.sections for r in s.rows}
    assert {(r.text, r.source_ref) for r in resp.rows} <= shown


def test_empty_core_sections_say_none_found_and_empty_ai_section_is_hidden():
    resp = response(rows=tuple(r for r in response().rows if r.section != "labs"))
    view = present_review(resp)
    assert [r.text for r in section(view, "labs").rows] == [EMPTY_ROW_TEXT]
    assert "ai_suggested_lookups" not in [s.key for s in view.sections]


def test_messages_only_case_shows_no_chart_sections_and_explains_why():
    view = present_review(response(status="messages_only", incomplete_reason="timed_out", window_start=None,
                                   window_end=None, onset=None, onset_is_approx=False, trend=None,
                                   rows=(response().rows[0],)))
    assert [s.key for s in view.sections] == ["patient_messages"]
    assert view.status_label == "Incomplete: patient messages only"
    assert view.window == "No chart pull" and view.onset == "Not reported"
    assert "within 24 hours" in view.notices[0]


def test_ai_fallback_anchors_offsets_to_the_first_message():
    resp = response(onset=None, onset_is_approx=False, incomplete_reason="ai_unavailable", ai_fallback=True)
    view = present_review(resp)
    assert "first message" in section(view, "labs").rows[0].offset
    assert "21 days before first message" in view.window
    assert len(view.notices) == 1 and "AI screening was unavailable" in view.notices[0]


def test_withheld_records_are_announced():
    view = present_review(response(rejected_item_count=2))
    assert view.notices == ("2 chart or drug records were withheld because a source check failed. "
                            "See the audit log for case c1.",)


def test_presenter_is_the_review_output_port_and_publishes_to_the_sink():
    sink = InMemoryReviewSink()
    presenter = ReviewPresenter(sink)
    assert isinstance(presenter, ReviewOutputPort)
    presenter.present(response())
    assert sink.views["c1"].patient_label == "Patient p1"


# ---- humble view: one smoke test --------------------------------------------------------
def test_html_view_smoke_renders_every_row_and_escapes_text():
    hostile = row("visits", '<script>alert("x")</script> & notes', date(2026, 9, 30), -9, title="Visit")
    view = present_review(response(rows=response().rows + (hostile,)))
    html = render_review_html(view)
    assert html.startswith("<!doctype html>")
    assert BANNER in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    for s in view.sections:
        assert f'data-key="{s.key}"' in html
    assert html.count("<tr>") == sum(len(s.rows) + 1 for s in view.sections)
