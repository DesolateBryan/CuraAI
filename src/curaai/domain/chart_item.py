"""ChartItem: one medication change, lab result or encounter, exactly as documented.

ADR-004: detail is verbatim. Nothing in the core trims, rewords or summarizes it.
ADR-012: an item without a source_ref cannot exist.
"""

from dataclasses import dataclass
from datetime import date

from curaai.domain.errors import MissingSourceReference
from curaai.domain.lookback import LookbackWindow
from curaai.domain.values import ChartItemKind, ItemId, require_text


@dataclass(frozen=True)
class ChartItem:
    item_id: ItemId
    kind: ChartItemKind
    date: date                 # start date (meds), result date (labs), visit date (encounters)
    title: str                 # short label: drug name, lab name, encounter type
    detail: str                # verbatim documented text
    source_ref: str            # pointer back to the original EHR entry
    author: str | None = None
    end_date: date | None = None
    flag: str | None = None    # abnormal flag as documented, e.g. "H" or "L"
    code: str | None = None
    code_system: str | None = None
    stopped: bool = False      # discontinued, even when the EHR gives no end date

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise MissingSourceReference(f"chart item {self.item_id!r} has no source_ref")
        require_text(self.item_id, "ChartItem.item_id")
        require_text(self.title, "ChartItem.title")
        if not isinstance(self.detail, str) or self.detail == "":
            raise ValueError("ChartItem.detail must be the documented text")
        if self.stopped and self.kind is not ChartItemKind.MEDICATION:
            raise ValueError("only medications can be stopped")
        if self.end_date is not None and self.end_date < self.date:
            raise ValueError("ChartItem end_date is before its date")

    def is_change_within(self, window: LookbackWindow) -> bool:
        """True if the item was started, resulted, seen, or stopped inside the window."""
        return window.contains(self.date) or (self.end_date is not None and window.contains(self.end_date))

    def is_active_medication_on(self, day: date) -> bool:
        return (
            self.kind is ChartItemKind.MEDICATION
            and not self.stopped
            and self.date <= day
            and (self.end_date is None or self.end_date > day)
        )
