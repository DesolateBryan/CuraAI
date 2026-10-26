"""Presenters: turn ReviewResponse into a display-ready ReviewView (ADR-014)."""

from curaai.adapters.presenters.html_view import render_review_html
from curaai.adapters.presenters.review_presenter import (
    InMemoryReviewSink, ReviewPresenter, ReviewSink, ReviewView, ViewRow, ViewSection, present_review, review_view_to_dict,
)

__all__ = ["InMemoryReviewSink", "ReviewPresenter", "ReviewSink", "ReviewView", "ViewRow", "ViewSection",
           "present_review", "render_review_html", "review_view_to_dict"]
