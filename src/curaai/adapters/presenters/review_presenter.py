"""ReviewPresenter: ReviewResponse -> ReviewView (display-ready strings only).

Decides section order, row order against onset, date formatting, the
"patient-reported" tag, the "approximate" onset wording, the in-person
verification banner and the source reference on every row. The view only
loops, escapes and fills slots (ADR-014).
"""

from dataclasses import dataclass

from curaai.application.dto.review import ReviewResponse
from curaai.application.ports.review_output_port import ReviewOutputPort


@dataclass(frozen=True)
class ViewRow:
    date: str
    text: str
    source_ref: str
    origin_label: str


@dataclass(frozen=True)
class ReviewView:
    patient_label: str
    onset: str
    banner: str | None
    sections: tuple[tuple[str, tuple[ViewRow, ...]], ...]


class ReviewPresenter(ReviewOutputPort):
    def __init__(self, sink: object) -> None:
        self._sink = sink

    def present(self, response: ReviewResponse) -> None:
        raise NotImplementedError("Ring 3 stub")
