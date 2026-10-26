"""Completeness, 3-week lookback, 24-hour timeout, approximate marker, case caps."""

from datetime import date, datetime, timedelta, timezone

import pytest

from curaai.domain.case_budget import CaseBudget, CaseLimits
from curaai.domain.completeness import CompletenessPolicy
from curaai.domain.errors import BudgetExceeded, InvalidSymptomReport
from curaai.domain.follow_up_timeout import FollowUpTimeout
from curaai.domain.lookback import LookbackWindow
from curaai.domain.symptom_report import SymptomReport
from curaai.domain.values import MissingField, SymptomId, Trend

TZ = timezone(timedelta(hours=-4))


# ---- CompletenessPolicy ---------------------------------------------------------
def test_complete_when_onset_and_trend_present():
    report = SymptomReport(onset=date(2026, 10, 9), trend=Trend.WORSENING)
    assert CompletenessPolicy.missing(report) == frozenset()
    assert CompletenessPolicy.is_complete(report)


def test_reports_exactly_what_is_missing():
    assert CompletenessPolicy.missing(SymptomReport()) == {MissingField.ONSET, MissingField.TREND}
    assert CompletenessPolicy.missing(SymptomReport(onset=date(2026, 10, 9))) == {MissingField.TREND}


# ---- SymptomReport ----------------------------------------------------------------
def test_approximate_marker_requires_a_date():
    with pytest.raises(InvalidSymptomReport):
        SymptomReport(onset_is_approx=True)


def test_merge_fills_gaps_and_keeps_first_values():
    first = SymptomReport(symptom_ids=frozenset({SymptomId("dizziness")}), trend=Trend.UNCHANGED)
    reply = SymptomReport(symptom_ids=frozenset({SymptomId("nausea")}), onset=date(2026, 10, 5),
                          onset_is_approx=True, trend=Trend.WORSENING)
    merged = first.merge(reply)
    assert merged.symptom_ids == {"dizziness", "nausea"}
    assert merged.onset == date(2026, 10, 5) and merged.onset_is_approx
    assert merged.trend is Trend.UNCHANGED


# ---- LookbackWindow (team decision: onset - 21 days through today) ------------------
def test_window_runs_21_days_before_onset_through_today():
    window = LookbackWindow.for_onset(date(2026, 10, 9), today=date(2026, 10, 16))
    assert (window.start, window.end) == (date(2026, 9, 18), date(2026, 10, 16))
    assert window.contains(date(2026, 9, 18)) and window.contains(date(2026, 10, 16))
    assert not window.contains(date(2026, 9, 17))


def test_onset_cannot_be_in_the_future():
    with pytest.raises(ValueError):
        LookbackWindow.for_onset(date(2026, 10, 17), today=date(2026, 10, 16))


# ---- FollowUpTimeout ----------------------------------------------------------------
def test_timeout_is_exactly_24_hours():
    asked = datetime(2026, 10, 16, 9, 0, tzinfo=TZ)
    timeout = FollowUpTimeout()
    assert not timeout.is_expired(asked, asked + timedelta(hours=23, minutes=59))
    assert timeout.is_expired(asked, asked + timedelta(hours=24))


def test_timeout_requires_timezone_aware_times():
    with pytest.raises(ValueError):
        FollowUpTimeout().is_expired(datetime(2026, 10, 16, 9, 0), datetime(2026, 10, 17, 9, 0, tzinfo=TZ))


# ---- CaseBudget (ADR-011) -------------------------------------------------------------
def test_default_caps_match_adr_011():
    limits = CaseLimits()
    assert (limits.max_model_calls, limits.max_lookups, limits.max_follow_ups) == (6, 5, 2)


def test_budget_trips_at_the_cap_and_is_immutable():
    budget = CaseBudget(CaseLimits(max_follow_ups=1))
    spent = budget.record_follow_up()
    assert budget.follow_ups == 0 and spent.follow_ups == 1
    assert not spent.can_follow_up()
    with pytest.raises(BudgetExceeded) as info:
        spent.record_follow_up()
    assert info.value.limit_name == "max_follow_ups"
