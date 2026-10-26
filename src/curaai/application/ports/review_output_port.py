"""ReviewOutputPort: hands the finished case to the physician-facing presenter."""

from abc import ABC, abstractmethod

from curaai.application.dto.review import ReviewResponse


class ReviewOutputPort(ABC):
    @abstractmethod
    def present(self, response: ReviewResponse) -> None:
        """Format and publish the review for the physician."""
