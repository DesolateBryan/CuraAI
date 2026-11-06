"""Presenters: turn ReviewResponse into a display-ready ReviewView (ADR-014)."""

from curaai.adapters.presenters.gate_presenter import GateView, gate_view_to_dict, present_gate
from curaai.adapters.presenters.html_view import render_gate_html, render_review_html
from curaai.adapters.presenters.review_presenter import (
    InMemoryReviewSink, ReviewPresenter, ReviewSink, ReviewView, ViewRow, ViewSection, present_review, review_view_to_dict,
)

__all__ = ["GateView", "InMemoryReviewSink", "ReviewPresenter", "ReviewSink", "ReviewView", "ViewRow", "ViewSection",
           "gate_view_to_dict", "present_gate", "present_review", "render_gate_html", "render_review_html",
           "review_view_to_dict"]
