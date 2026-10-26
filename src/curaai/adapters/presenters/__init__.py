"""Presenters: turn ReviewResponse into a display-ready ReviewView (ADR-014)."""

from curaai.adapters.presenters.html_view import render_review_html
from curaai.adapters.presenters.review_presenter import (
    InMemoryReviewSink, ReviewPresenter, ReviewSink, ReviewView, ViewRow, ViewSection, present_review,
)

__all__ = ["InMemoryReviewSink", "ReviewPresenter", "ReviewSink", "ReviewView", "ViewRow", "ViewSection",
           "present_review", "render_review_html"]
